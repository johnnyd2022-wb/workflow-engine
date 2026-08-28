"""Read-through cache for /api/core/system-findings.

The check suite (CoreChecksRunner + build_system_status_payload) runs a DAG traversal per
expired-with-stock raw material -- on a real org that is ~1.3s and hundreds of queries,
and /core hits the endpoint on every load. This module serves the last computed payload
from `system_findings_cache` and only recomputes when the row is missing, past its TTL,
or was marked ``stale`` by a mutation.

Recompute is single-flight: a pg transaction-scoped advisory lock keyed on the org means
a burst of /core loads for one org runs the suite once, not once per request. The lock
auto-releases on commit/rollback, so a failed request cannot leak it.
"""

import hashlib
import json
from datetime import UTC, datetime, timedelta
from uuid import UUID

import sqlalchemy as sa

from app.observability import get_logger

logger = get_logger(__name__)

# Findings are a slow-moving health summary and every inventory/execution/process mutation
# invalidates the row immediately anyway. This TTL is only the backstop for time-only
# changes (an item crossing its expiry date with nothing else happening) -- 30 min of lag
# there is fine, and the longer window keeps more sessions on the fast (cached) path
# instead of eating the ~1s recompute.
TTL = timedelta(minutes=30)

# Event-type prefixes whose mutations can change what the checks report.
_INVALIDATING_PREFIXES = ("inventory_item.", "execution.", "process.")


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
    return bool(row) and not row.stale and (now - row.computed_at) < TTL


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
