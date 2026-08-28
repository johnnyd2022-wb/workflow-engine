"""Read-through cache for /api/core/system-findings, split by check cost.

The endpoint feeds the /core banner and the Notifications page, and /core hits it on every
load. Its checks split cleanly:

- **expired_materials** runs a DAG traversal per expired-with-stock raw material (~1.3s /
  hundreds of queries on a real org) and is purely DATE-driven -- it only changes when a
  raw material crosses `expiry_date < date.today()`, evaluated in NZ local time. That one
  is CACHED here: fresh until the next Pacific/Auckland midnight, invalidated immediately
  by any inventory/execution/process mutation, recomputed single-flight (a pg
  transaction-scoped advisory lock keyed on the org, so a burst of /core loads runs it
  once). It effectively runs ~once per NZ day per active org.

- **untracked_items / output_expiry / output_ready_date / compliant.<module>** are cheap
  (no DAG -- targeted queries + date math) and some are sub-day time-sensitive
  (output_expiry supports an `hours` unit). Those run LIVE on every request so the banner
  reflects them in real time.

The merged `{findings, system_status}` is round-tripped through Flask's JSON provider once
so the response shape is identical whether the expensive part came from cache or compute.
"""

import hashlib
import json
from datetime import UTC, datetime, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo

import sqlalchemy as sa

from app.observability import get_logger

logger = get_logger(__name__)

# Only these check ids are cached (the DAG-heavy, date-driven ones). Everything else the
# CoreChecksRunner registers runs live on every request.
_CACHED_CHECK_IDS = frozenset({"expired_materials"})

# Freshness of the cached (expensive) slice: until the next Pacific/Auckland midnight,
# hard-capped at 25h for DST / clock-jump safety.
_LOCAL_TZ = ZoneInfo("Pacific/Auckland")
_MAX_AGE = timedelta(hours=25)
TTL = _MAX_AGE  # kept as a module symbol for callers/tests wanting "the freshness ceiling"

# Event-type prefixes whose mutations can change what the cached check reports.
_INVALIDATING_PREFIXES = ("inventory_item.", "execution.", "process.")


def _last_local_midnight(now: datetime) -> datetime:
    """UTC instant of the most recent Pacific/Auckland midnight at or before ``now``."""
    local = now.astimezone(_LOCAL_TZ)
    return local.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(UTC)


def _lock_key(org_id: UUID) -> int:
    """Deterministic signed int64 for pg_advisory_xact_lock, namespaced to this feature."""
    digest = hashlib.blake2b(f"{org_id}:system_findings".encode(), digest_size=8).digest()
    return int.from_bytes(digest, "big", signed=True)


def _fetch(session):
    from app.core.db.models.system_findings_cache import SystemFindingsCache

    # org_id filter is applied automatically by the TenantScoped global filter; be
    # explicit anyway so this is correct if that filter is ever bypassed.
    return session.query(SystemFindingsCache).first()


def _fresh(row, now: datetime) -> bool:
    if not row or row.stale:
        return False
    computed_at = row.computed_at
    if computed_at.tzinfo is None:
        computed_at = computed_at.replace(tzinfo=UTC)
    return computed_at >= _last_local_midnight(now) and (now - computed_at) < _MAX_AGE


def _result_to_dict(r) -> dict:
    return {"check_id": r.check_id, "flagged": r.flagged, "message": r.message, "data": r.data}


def _dict_to_result(d: dict):
    from app.core.backend.corechecks import CheckResult

    return CheckResult(
        check_id=d["check_id"], flagged=bool(d.get("flagged")), message=d.get("message"), data=d.get("data")
    )


def _compute_expensive(org_id: UUID, session) -> list[dict]:
    """Run only the cached (DAG-heavy) checks; return their results as plain-JSON dicts."""
    from flask import json as flask_json

    from app.core.backend.corechecks import CoreChecksRunner

    runner = CoreChecksRunner(org_id=org_id, session=session)
    out = []
    for cid in _CACHED_CHECK_IDS:
        r = runner.run_check(cid)
        if r is not None:
            out.append(_result_to_dict(r))
    # Normalise Decimal/UUID/datetime out now so _upsert's json.dumps is safe and the
    # cached bytes match what jsonify would produce.
    return flask_json.loads(flask_json.dumps(out))


def _run_live(org_id: UUID, session) -> list:
    """Run every registered check that is NOT cached, fresh. Returns [CheckResult]."""
    from app.core.backend.corechecks import CoreChecksRunner

    runner = CoreChecksRunner(org_id=org_id, session=session)
    results = []
    for cid in runner._checks:  # noqa: SLF001 -- the runner has no public id iterator
        if cid in _CACHED_CHECK_IDS:
            continue
        try:
            r = runner.run_check(cid)
        except Exception:
            logger.exception("live system check %s failed for org %s", cid, org_id)
            continue
        if r is not None:
            results.append(r)
    return results


def _upsert(session, org_id: UUID, expensive_results: list[dict], now: datetime) -> None:
    session.execute(
        sa.text(
            """
            INSERT INTO system_findings_cache (id, org_id, payload, computed_at, stale)
            VALUES (gen_random_uuid(), :org_id, CAST(:payload AS jsonb), :now, false)
            ON CONFLICT (org_id) DO UPDATE
            SET payload = EXCLUDED.payload, computed_at = EXCLUDED.computed_at, stale = false
            """
        ),
        {"org_id": str(org_id), "payload": json.dumps({"results": expensive_results}), "now": now},
    )


def _cached_expensive(org_id: UUID, session) -> list[dict]:
    """The cached (DAG-heavy) check results as plain-JSON dicts. Read-through with
    single-flight recompute; safe to call concurrently."""
    now = datetime.now(UTC)
    row = _fetch(session)
    if _fresh(row, now):
        return row.payload.get("results", [])

    key = _lock_key(org_id)
    got_lock = session.execute(sa.text("SELECT pg_try_advisory_xact_lock(:k)"), {"k": key}).scalar()
    if not got_lock:
        # Another request is recomputing. Serve the stale copy if we have one; else wait.
        if row is not None:
            return row.payload.get("results", [])
        session.execute(sa.text("SELECT pg_advisory_xact_lock(:k)"), {"k": key})
        row = _fetch(session)
        if row is not None:
            return row.payload.get("results", [])

    row = _fetch(session)  # double-check: someone may have written just before we locked
    if _fresh(row, now):
        return row.payload.get("results", [])

    results = _compute_expensive(org_id, session)
    try:
        _upsert(session, org_id, results, now)
        session.commit()  # persist AND release the xact advisory lock
    except Exception:
        session.rollback()
        logger.exception("Failed to write system_findings_cache for org %s", org_id)
    return results


def get_or_compute(org_id: UUID, session) -> dict:
    """The full `{findings, system_status}` payload: the DAG-heavy checks from the per-org
    cache, the cheap checks recomputed live, merged."""
    from flask import json as flask_json

    from app.core.backend.system_status import build_system_status_payload

    cached_results = [_dict_to_result(d) for d in _cached_expensive(org_id, session)]
    live_results = _run_live(org_id, session)
    results = cached_results + live_results

    findings = []
    for r in results:
        if not r.flagged or not r.message:
            continue
        finding = {"text": r.message, "check_id": r.check_id}
        if r.data is not None:
            finding["data"] = r.data
        findings.append(finding)

    system_status = build_system_status_payload(org_id, session, results)
    return flask_json.loads(flask_json.dumps({"findings": findings, "system_status": system_status}))


def prewarm(org_id: UUID, session) -> None:
    """Force-recompute the cached (expensive) slice for one org. Used by the scheduled
    just-after-NZ-midnight warm job so the first user of the day never eats the DAG cost."""
    now = datetime.now(UTC)
    key = _lock_key(org_id)
    if not session.execute(sa.text("SELECT pg_try_advisory_xact_lock(:k)"), {"k": key}).scalar():
        return  # someone is already computing it
    results = _compute_expensive(org_id, session)
    try:
        _upsert(session, org_id, results, now)
        session.commit()
    except Exception:
        session.rollback()
        logger.exception("prewarm system_findings_cache failed for org %s", org_id)


def mark_stale(session, org_id: UUID, event_type: str) -> None:
    """Called by EventWriter after a mutation. Marks the cached slice stale so the next
    request recomputes it. Guarded -- a cache-bookkeeping failure must never fail a
    mutation."""
    if not event_type or not event_type.startswith(_INVALIDATING_PREFIXES):
        return
    try:
        session.execute(
            sa.text("UPDATE system_findings_cache SET stale = true WHERE org_id = :org_id AND stale = false"),
            {"org_id": str(org_id)},
        )
    except Exception:
        logger.exception("Failed to mark system_findings_cache stale for org %s", org_id)
