"""Audited amendments to completed production-step records (source-to-sale 1.5)."""

from __future__ import annotations

from uuid import UUID

from flask import g, jsonify, render_template, request
from sqlalchemy.orm import joinedload

from app.core.backend.complete_step_payload import validate_json_blob
from app.core.backend.event_writer import EventWriter
from app.core.db import db_session
from app.core.db.models.entity_event import EntityEvent
from app.core.db.models.execution import Execution
from app.core.db.models.execution_step import ExecutionStep, ExecutionStepStatus
from app.core.security.permissions import requires_auth
from app.observability import get_logger

logger = get_logger(__name__)
_AUDIT_KEYS = frozenset(
    {
        "completed_at",
        "completed_by",
        "completed_by_email",
        "completed_by_user_id",
        "entered_at",
        "evidence_ids",
        "execution_errors",
        "execution_warnings",
    }
)


def _step(org_id: UUID, execution_id: UUID, step_id: UUID, *, lock: bool = False):
    query = (
        db_session.query(ExecutionStep)
        .join(Execution, ExecutionStep.execution_id == Execution.id)
        .filter(
            ExecutionStep.id == step_id,
            ExecutionStep.execution_id == execution_id,
            ExecutionStep.org_id == org_id,
            Execution.org_id == org_id,
        )
        .options(joinedload(ExecutionStep.step))
    )
    if lock:
        query = query.with_for_update(of=ExecutionStep)
    return query.one_or_none()


def _parse_ids(execution_id: str, execution_step_id: str):
    try:
        return UUID(g.org_id), UUID(execution_id), UUID(execution_step_id)
    except (ValueError, TypeError):
        return None


def _prompt_data(step: ExecutionStep) -> dict:
    return {k: v for k, v in (step.execution_data or {}).items() if k not in _AUDIT_KEYS}


def _history(org_id: UUID, execution_id: UUID, step_id: UUID) -> list[dict]:
    events = (
        db_session.query(EntityEvent)
        .filter(
            EntityEvent.org_id == org_id,
            EntityEvent.entity_type == "execution",
            EntityEvent.entity_id == execution_id,
            EntityEvent.event_type.in_(("execution.step_completed", "execution.step_amended")),
            EntityEvent.payload["execution_step_id"].astext == str(step_id),
        )
        .order_by(EntityEvent.seq.asc())
        .all()
    )
    history = []
    for event in events:
        payload = event.payload or {}
        before = (payload.get("before") or {}).get("prompts") or {}
        after = (payload.get("after") or {}).get("prompts") or {}
        history.append(
            {
                "event": event.event_type,
                "at": event.created_at.isoformat(),
                "actor": event.actor_label or "System",
                "reason": payload.get("reason"),
                "changes": [
                    {"field": key, "before": before.get(key), "after": after.get(key)}
                    for key in sorted(set(before) | set(after))
                    if before.get(key) != after.get(key)
                ],
            }
        )
    return history


def register_routes(bp):
    """Register the completed-step record and amendment endpoints on Core."""

    @bp.route("/core/executions/<execution_id>/steps/<execution_step_id>/record", methods=["GET"])
    @requires_auth
    def execution_step_record_page(execution_id: str, execution_step_id: str):
        ids = _parse_ids(execution_id, execution_step_id)
        if ids is None:
            return jsonify({"error": "Invalid execution or step ID"}), 400
        org_id, execution_uuid, step_uuid = ids
        step = _step(org_id, execution_uuid, step_uuid)
        if step is None or step.status != ExecutionStepStatus.COMPLETED:
            return jsonify({"error": "Completed step not found"}), 404
        return render_template(
            "processes/execution-step-record.html",
            execution_id=str(execution_uuid),
            execution_step_id=str(step_uuid),
            step_name=step.step.name if step.step else f"Step {step.step_number}",
            occurred_at=step.completed_at.isoformat() if step.completed_at else None,
            entered_at=(step.execution_data or {}).get("entered_at"),
            prompts=_prompt_data(step),
            history=_history(org_id, execution_uuid, step_uuid),
        )

    @bp.route("/api/core/executions/<execution_id>/steps/<execution_step_id>/record", methods=["POST"])
    @requires_auth
    def amend_execution_step_record(execution_id: str, execution_step_id: str):
        ids = _parse_ids(execution_id, execution_step_id)
        if ids is None:
            return jsonify({"error": "Invalid execution or step ID"}), 400
        org_id, execution_uuid, step_uuid = ids
        if request.content_length is not None and request.content_length > 64 * 1024:
            return jsonify({"error": "Request body too large"}), 413
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            return jsonify({"error": "JSON object required"}), 400
        if set(data) - {"reason", "prompts"}:
            return jsonify({"error": "Only prompts and an edit reason can be amended"}), 400
        reason = str(data.get("reason") or "").strip()
        if len(reason) < 3 or len(reason) > 500:
            return jsonify({"error": "An edit reason of 3–500 characters is required"}), 400
        changes = data.get("prompts", {})
        if not isinstance(changes, dict) or any(not isinstance(k, str) or k in _AUDIT_KEYS for k in changes):
            return jsonify({"error": "Invalid prompt changes"}), 400
        try:
            validate_json_blob(changes, path="$.prompts")
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400

        try:
            step = _step(org_id, execution_uuid, step_uuid, lock=True)
            if step is None or step.status != ExecutionStepStatus.COMPLETED:
                db_session.rollback()
                return jsonify({"error": "Completed step not found"}), 404
            existing = dict(step.execution_data or {})
            allowed = (
                set(_prompt_data(step))
                | {"operator_note"}
                | {
                    p.get("label")
                    for p in (step.step.execution_prompts or [])
                    if isinstance(p, dict) and p.get("label")
                }
            )
            if set(changes) - allowed:
                db_session.rollback()
                return jsonify({"error": "Only recorded step prompts can be edited"}), 400
            before = {
                "occurred_at": step.completed_at.isoformat() if step.completed_at else None,
                "prompts": _prompt_data(step),
            }
            updated = dict(existing)
            updated.update(changes)
            occurred = step.completed_at
            after = {
                "occurred_at": occurred.isoformat() if occurred else None,
                "prompts": {k: v for k, v in updated.items() if k not in _AUDIT_KEYS},
            }
            if before == after:
                db_session.rollback()
                return jsonify({"error": "No record changes supplied"}), 400
            step.execution_data = updated
            EventWriter(db_session, org_id).emit(
                event_type="execution.step_amended",
                entity_type="execution",
                entity_id=execution_uuid,
                payload={
                    "execution_step_id": str(step_uuid),
                    "reason": reason,
                    "before": before,
                    "after": after,
                },
                diff={"step_record": {"before": before, "after": after}},
            )
            db_session.commit()
            return jsonify({"saved": True, "history_count": len(_history(org_id, execution_uuid, step_uuid))}), 200
        except Exception:
            db_session.rollback()
            logger.exception("execution_step_amend_failed", org_id=str(org_id), step_id=str(step_uuid))
            return jsonify({"error": "Could not save the amendment"}), 500
