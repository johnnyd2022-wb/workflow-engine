"""Read-through cache for /api/core/system-findings.

The check suite (CoreChecksRunner + build_system_status_payload) runs a DAG traversal per
expired-with-stock raw material -- on a real org that is ~1.3s and hundreds of queries,
and /core hits the endpoint on every load. This module serves the last computed payload
from `system_findings_cache` and only recomputes when the row is missing, was computed
before the last NZ midnight (the date-driven checks roll over there), or was marked
``stale`` by a mutation.

Recompute is single-flight: a pg transaction-scoped advisory lock keyed on the org means
a burst of /core loads for one org runs the suite once, not once per request. The lock
auto-releases on commit/rollback, so a failed request cannot leak it.
"""

import hashlib
import json
from datetime import UTC, datetime, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo

import sqlalchemy as sa

from app.observability import get_logger

logger = get_logger(__name__)

# Every inventory/execution/process mutation invalidates the row immediately (mark_stale).
# The only thing left for a time-based backstop to catch is the DATE-driven check
# (expired_materials: `expiry_date < date.today()`), which the app evaluates in NZ local
# time and which therefore only changes at NZ midnight. So a cached payload stays fresh
# until the next Pacific/Auckland midnight -- the expensive DAG traversal then runs about
# once per NZ day per active org instead of on every /core load. `_MAX_AGE` is a hard
# ceiling (DST-safe) in case a clock jump makes the midnight math misbehave.
_LOCAL_TZ = ZoneInfo("Pacific/Auckland")
_MAX_AGE = timedelta(hours=25)

# Kept as a module symbol: tests and any external caller that wants "the freshness
# window" get the hard ceiling.
TTL = _MAX_AGE

# Event-type prefixes whose mutations can change what the checks report.
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
    # Fresh only if computed on/after the last NZ midnight AND not absurdly old.
    return computed_at >= _last_local_midnight(now) and (now - computed_at) < _MAX_AGE


def _compute(org_id: UUID, session) -> dict:
    """Run the check suite and normalise the result to plain JSON types.

    The payload carries Decimal/UUID/datetime values from the check data; round-tripping
    it through Flask's JSON provider (the same one jsonify uses) once here means the
    cache-miss response and every cache-hit response are byte-identical, and the raw
    json.dumps in _upsert cannot choke.
    """
    from flask import json as flask_json

    from app.core.backend.corechecks import CoreChecksRunner
    from app.core.backend.system_status import build_system_status_payload

    results = CoreChecksRunner(org_id=org_id, session=session).run_all_checks()
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


def _upsert(session, org_id: UUID, payload: dict, now: datetime) -> None:
    session.execute(
        sa.text(
            """
            INSERT INTO system_findings_cache (id, org_id, payload, computed_at, stale)
            VALUES (gen_random_uuid(), :org_id, CAST(:payload AS jsonb), :now, false)
            ON CONFLICT (org_id) DO UPDATE
            SET payload = EXCLUDED.payload, computed_at = EXCLUDED.computed_at, stale = false
            """
        ),
        {"org_id": str(org_id), "payload": json.dumps(payload), "now": now},
    )


def get_or_compute(org_id: UUID, session) -> dict:
    """Return the system-findings payload for ``org_id``, computing + caching it if the
    cached copy is missing / stale / expired. Safe to call concurrently."""
    now = datetime.now(UTC)
    row = _fetch(session)
    if _fresh(row, now):
        return row.payload

    key = _lock_key(org_id)
    got_lock = session.execute(sa.text("SELECT pg_try_advisory_xact_lock(:k)"), {"k": key}).scalar()
    if not got_lock:
        # Another request holds the lock and is (re)computing. Serve the stale copy now if
        # we have one; otherwise wait for the lock and read what that request wrote.
        if row is not None:
            return row.payload
        session.execute(sa.text("SELECT pg_advisory_xact_lock(:k)"), {"k": key})
        row = _fetch(session)
        if row is not None:
            return row.payload

    # We hold the lock. Re-check: another request may have written just before we locked.
    row = _fetch(session)
    if _fresh(row, now):
        return row.payload

    payload = _compute(org_id, session)
    try:
        _upsert(session, org_id, payload, now)
        session.commit()  # persist the row AND release the xact advisory lock
    except Exception:
        session.rollback()
        logger.exception("Failed to write system_findings_cache for org %s", org_id)
    return payload


def mark_stale(session, org_id: UUID, event_type: str) -> None:
    """Called by EventWriter after a mutation. Marks the org's cache stale so the next
    request recomputes. Guarded -- a cache-bookkeeping failure must never fail a mutation."""
    if not event_type or not event_type.startswith(_INVALIDATING_PREFIXES):
        return
    try:
        session.execute(
            sa.text("UPDATE system_findings_cache SET stale = true WHERE org_id = :org_id AND stale = false"),
            {"org_id": str(org_id)},
        )
    except Exception:
        logger.exception("Failed to mark system_findings_cache stale for org %s", org_id)
