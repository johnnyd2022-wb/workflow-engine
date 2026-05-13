"""EventWriter — single entry point for all entity_events writes.

All event emission goes through EventWriter.emit(). Never write to entity_events
inline in business logic or route handlers.

Key rules:
- emit() is called inside the same DB transaction as the mutation. Events roll
  back with the mutation on failure — no dual-write problem.
- entity_event_summaries is upserted in the same transaction immediately after
  the event is written. Never update summaries in a separate transaction.
- actor_id/actor_label are pulled from Flask g (set by tenant_context middleware).
- correlation_id is pulled from g.correlation_id (set per-request in middleware).
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from decimal import Decimal
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.db.models.entity_event import EntityEvent

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

_QUANTITY_HISTORY_CAP = 50


def _get_g_attr(name: str, default=None):
    """Safely pull an attribute from Flask g (returns default outside request context)."""
    try:
        from flask import g

        return getattr(g, name, default)
    except RuntimeError:
        return default


def _request_metadata() -> dict:
    try:
        from flask import request

        return {
            "ip": request.remote_addr,
            "user_agent": (request.user_agent.string[:200] if request.user_agent else None),
        }
    except RuntimeError:
        return {}


def _safe_uuid(value) -> UUID | None:
    if value is None:
        return None
    if isinstance(value, UUID):
        return value
    try:
        return UUID(str(value))
    except (ValueError, AttributeError):
        return None


class EventWriter:
    """Writes events to entity_events and upserts entity_event_summaries atomically."""

    def __init__(self, session: Session, org_id: UUID):
        self.session = session
        self.org_id = org_id

    def emit(
        self,
        event_type: str,
        entity_type: str,
        entity_id: UUID,
        payload: dict,
        diff: dict | None = None,
        causation_id: UUID | None = None,
        actor_id: UUID | None = None,
        actor_label: str | None = None,
        actor_type: str = "user",
    ) -> EntityEvent:
        """Write one event and upsert the entity summary. Caller owns the transaction."""
        resolved_actor_id = actor_id or _safe_uuid(_get_g_attr("user_id"))
        resolved_actor_label = actor_label or _get_g_attr("user_email")
        correlation_id = _get_g_attr("correlation_id") or uuid4()

        event = EntityEvent(
            org_id=self.org_id,
            event_type=event_type,
            entity_type=entity_type,
            entity_id=entity_id,
            actor_id=resolved_actor_id,
            actor_type=actor_type,
            actor_label=resolved_actor_label,
            payload=payload,
            diff=diff,
            causation_id=causation_id,
            correlation_id=correlation_id,
            request_metadata=_request_metadata(),
            created_at=datetime.now(timezone.utc),
        )
        self.session.add(event)
        self.session.flush()  # get event.id before upsert

        try:
            _upsert_summary(self.session, event)
        except Exception:
            logger.exception("Failed to upsert entity_event_summary for event %s", event_type)
            # Summary failure must not block the main event write
        return event


# ---------------------------------------------------------------------------
# Summary upsert dispatcher
# ---------------------------------------------------------------------------


def _upsert_summary(session: Session, event: EntityEvent) -> None:
    entity_type = event.entity_type
    if entity_type == "inventory_item":
        _update_inventory_summary(session, event)
    elif entity_type == "execution":
        _update_execution_summary(session, event)
    elif entity_type == "process":
        _update_process_summary(session, event)
    elif entity_type == "user":
        _update_user_summary(session, event)
    elif entity_type == "org":
        _update_org_summary(session, event)


def _do_upsert(
    session: Session, entity_id: UUID, org_id: UUID, entity_type: str, summary: dict, event: EntityEvent
) -> None:
    """Generic upsert into entity_event_summaries."""
    now = datetime.now(timezone.utc)
    session.execute(
        text(
            """
            INSERT INTO entity_event_summaries
                (entity_id, org_id, entity_type, summary, last_event_at, last_event_type, last_actor, updated_at)
            VALUES
                (:entity_id, :org_id, :entity_type, CAST(:summary AS jsonb), :last_event_at, :last_event_type, :last_actor, :updated_at)
            ON CONFLICT (entity_id) DO UPDATE SET
                summary        = CAST(:summary AS jsonb),
                last_event_at  = :last_event_at,
                last_event_type= :last_event_type,
                last_actor     = :last_actor,
                updated_at     = :updated_at
            """
        ),
        {
            "entity_id": str(entity_id),
            "org_id": str(org_id),
            "entity_type": entity_type,
            "summary": _json_dumps(summary),
            "last_event_at": event.created_at,
            "last_event_type": event.event_type,
            "last_actor": event.actor_label,
            "updated_at": now,
        },
    )


def _json_dumps(obj) -> str:
    import json

    def default(o):
        if isinstance(o, Decimal):
            return str(o)
        if isinstance(o, (datetime,)):
            return o.isoformat()
        if isinstance(o, UUID):
            return str(o)
        raise TypeError(f"Object of type {type(o)} is not JSON serializable")

    return json.dumps(obj, default=default)


# ---------------------------------------------------------------------------
# Current summary loader (reads existing row before merging)
# ---------------------------------------------------------------------------


def _load_existing_summary(session: Session, entity_id: UUID) -> dict:
    row = session.execute(
        text("SELECT summary FROM entity_event_summaries WHERE entity_id = :eid"),
        {"eid": str(entity_id)},
    ).fetchone()
    if row and row[0]:
        return dict(row[0])
    return {}


# ---------------------------------------------------------------------------
# Per-entity summary updaters
# ---------------------------------------------------------------------------


def _update_inventory_summary(session: Session, event: EntityEvent) -> None:
    existing = _load_existing_summary(session, event.entity_id)
    p = event.payload or {}

    if event.event_type == "inventory_item.created":
        summary = {
            "created_by": event.actor_label,
            "created_at": event.created_at.isoformat() if event.created_at else None,
            "add_method": p.get("add_method", "manual"),
            "last_consumed_at": None,
            "last_consumed_by": None,
            "last_consumed_execution": None,
            "times_consumed": 0,
            "processes_used_in": 0,
            "wastage_event_count": 0,
            "total_quantity_wasted": "0",
            "quantity_history": [
                {"at": event.created_at.isoformat() if event.created_at else None, "qty": str(p.get("quantity", "0"))}
            ],
            "status_hint": "available",
        }

    elif event.event_type == "inventory_item.quantity_adjusted":
        summary = dict(existing)
        qty_after = str(p.get("quantity_after", p.get("quantity", "0")))
        history = list(existing.get("quantity_history") or [])
        history.append({"at": event.created_at.isoformat() if event.created_at else None, "qty": qty_after})
        summary["quantity_history"] = history[-_QUANTITY_HISTORY_CAP:]

    elif event.event_type == "inventory_item.consumed":
        summary = dict(existing)
        summary["last_consumed_at"] = event.created_at.isoformat() if event.created_at else None
        summary["last_consumed_by"] = event.actor_label
        summary["last_consumed_execution"] = p.get("execution_name") or p.get("step_name")
        summary["times_consumed"] = int(existing.get("times_consumed") or 0) + 1
        # Track unique process count via a set stored as sorted list
        procs = set(existing.get("process_ids_used_in") or [])
        if p.get("process_id"):
            procs.add(str(p["process_id"]))
        summary["process_ids_used_in"] = sorted(procs)
        summary["processes_used_in"] = len(procs)
        summary["status_hint"] = _inventory_status_hint(summary)

    elif event.event_type == "inventory_item.wasted":
        summary = dict(existing)
        summary["wastage_event_count"] = int(existing.get("wastage_event_count") or 0) + 1
        prev_wasted = _parse_decimal(existing.get("total_quantity_wasted") or "0")
        new_wasted = _parse_decimal(str(p.get("quantity_wasted") or "0"))
        summary["total_quantity_wasted"] = str(prev_wasted + new_wasted)

    elif event.event_type in ("inventory_item.updated", "inventory_item.deleted"):
        summary = dict(existing)

    else:
        summary = dict(existing)

    _do_upsert(session, event.entity_id, event.org_id, "inventory_item", summary, event)


def _inventory_status_hint(summary: dict) -> str:
    times = int(summary.get("times_consumed") or 0)
    if times == 0:
        return "available"
    # Rough heuristic — full accuracy requires querying current quantity
    return "partially_consumed"


def _update_execution_summary(session: Session, event: EntityEvent) -> None:
    existing = _load_existing_summary(session, event.entity_id)
    p = event.payload or {}

    if event.event_type == "execution.created":
        summary = {
            "created_by": event.actor_label,
            "created_at": event.created_at.isoformat() if event.created_at else None,
            "process_version": p.get("process_version_number"),
            "process_version_date": p.get("process_version_date"),
            "steps_completed": 0,
            "last_step_completed_at": None,
            "last_step_actor": None,
            "evidence_count": 0,
            "items_consumed": [],
            "items_produced": [],
        }

    elif event.event_type == "execution.step_completed":
        summary = dict(existing)
        summary["steps_completed"] = int(existing.get("steps_completed") or 0) + 1
        summary["last_step_completed_at"] = event.created_at.isoformat() if event.created_at else None
        summary["last_step_actor"] = event.actor_label
        # Accumulate consumed/produced
        consumed = list(existing.get("items_consumed") or [])
        consumed.extend(p.get("items_consumed") or [])
        summary["items_consumed"] = consumed
        produced = list(existing.get("items_produced") or [])
        produced.extend(p.get("items_produced") or [])
        summary["items_produced"] = produced
        # Count evidence IDs
        ev_ids = p.get("evidence_ids") or []
        summary["evidence_count"] = int(existing.get("evidence_count") or 0) + len(ev_ids)

    elif event.event_type == "execution.completed":
        summary = dict(existing)
        summary["completed_at"] = event.created_at.isoformat() if event.created_at else None

    else:
        summary = dict(existing)

    _do_upsert(session, event.entity_id, event.org_id, "execution", summary, event)


def _update_process_summary(session: Session, event: EntityEvent) -> None:
    existing = _load_existing_summary(session, event.entity_id)
    p = event.payload or {}

    if event.event_type == "process.created":
        summary = {
            "created_by": event.actor_label,
            "created_at": event.created_at.isoformat() if event.created_at else None,
            "current_version": p.get("version_number", 1),
            "last_modified_at": event.created_at.isoformat() if event.created_at else None,
            "last_modified_by": event.actor_label,
            "last_change_summary": "Process created",
            "total_runs": 0,
            "completed_runs": 0,
            "failed_runs": 0,
            "cancelled_runs": 0,
            "active_runs": 0,
            "last_run_at": None,
            "last_run_by": None,
        }

    elif event.event_type in (
        "process.updated",
        "process.step_added",
        "process.step_updated",
        "process.step_deleted",
        "process.step_doc_uploaded",
        "process.step_doc_created",
        "process.step_doc_updated",
        "process.step_doc_deleted",
    ):
        summary = dict(existing)
        summary["current_version"] = p.get("version_number", existing.get("current_version", 1))
        summary["last_modified_at"] = event.created_at.isoformat() if event.created_at else None
        summary["last_modified_by"] = event.actor_label
        summary["last_change_summary"] = (
            p.get("change_summary") or event.event_type.replace("process.", "").replace("_", " ").capitalize()
        )

    elif event.event_type == "execution.created":
        # Increment process run count when an execution is created for this process
        # Note: the entity_id here is the process_id from the event payload
        summary = dict(existing)
        summary["total_runs"] = int(existing.get("total_runs") or 0) + 1
        summary["active_runs"] = int(existing.get("active_runs") or 0) + 1
        summary["last_run_at"] = event.created_at.isoformat() if event.created_at else None
        summary["last_run_by"] = event.actor_label

    elif event.event_type == "execution.completed":
        summary = dict(existing)
        summary["completed_runs"] = int(existing.get("completed_runs") or 0) + 1
        summary["active_runs"] = max(0, int(existing.get("active_runs") or 0) - 1)

    elif event.event_type == "execution.cancelled":
        summary = dict(existing)
        summary["cancelled_runs"] = int(existing.get("cancelled_runs") or 0) + 1
        summary["active_runs"] = max(0, int(existing.get("active_runs") or 0) - 1)

    else:
        summary = dict(existing)

    _do_upsert(session, event.entity_id, event.org_id, "process", summary, event)


def _update_user_summary(session: Session, event: EntityEvent) -> None:
    existing = _load_existing_summary(session, event.entity_id)
    p = event.payload or {}

    if event.event_type == "user.created":
        summary = {
            "created_at": event.created_at.isoformat() if event.created_at else None,
            "email": p.get("email"),
            "role": p.get("role"),
            "login_count": 0,
            "failed_login_count": 0,
            "last_login_at": None,
        }
    elif event.event_type == "user.login":
        summary = dict(existing)
        summary["login_count"] = int(existing.get("login_count") or 0) + 1
        summary["last_login_at"] = event.created_at.isoformat() if event.created_at else None
    elif event.event_type == "user.login_failed":
        summary = dict(existing)
        summary["failed_login_count"] = int(existing.get("failed_login_count") or 0) + 1
    elif event.event_type == "user.role_changed":
        summary = dict(existing)
        summary["role"] = p.get("new_role")
    else:
        summary = dict(existing)

    _do_upsert(session, event.entity_id, event.org_id, "user", summary, event)


def _update_org_summary(session: Session, event: EntityEvent) -> None:
    existing = _load_existing_summary(session, event.entity_id)
    p = event.payload or {}
    summary = dict(existing)
    summary["name"] = p.get("name", existing.get("name"))
    summary["status"] = p.get("status", existing.get("status"))
    summary["last_changed_at"] = event.created_at.isoformat() if event.created_at else None
    summary["last_changed_by"] = event.actor_label
    _do_upsert(session, event.entity_id, event.org_id, "org", summary, event)


def _parse_decimal(value: str) -> Decimal:
    try:
        return Decimal(str(value))
    except Exception:
        return Decimal("0")
