"""Always-on Core Tasks: durable work records, board data, and notification policy."""

from __future__ import annotations

from calendar import monthrange
from datetime import UTC, date, datetime, timedelta
from typing import Any
from uuid import UUID

from flask import g, jsonify, request
from sqlalchemy import and_, func, or_
from sqlalchemy.orm import Session

from app.core.backend.event_writer import EventWriter
from app.core.db import db_session
from app.core.db.models.core_task import CoreTask
from app.core.db.models.core_task_config import CoreTaskConfig
from app.core.db.models.task_board_lane import TaskBoardLane
from app.core.db.models.user import User
from app.core.security.permissions import requires_auth
from app.core.utils.time import utc_now
from app.observability import get_logger

logger = get_logger(__name__)

OPEN_STATUSES = frozenset({"pending", "in_progress"})
ALL_STATUSES = OPEN_STATUSES | {"completed", "cancelled"}
PRIORITIES = frozenset({"low", "medium", "high"})
LEAD_UNITS = frozenset({"days", "weeks", "months"})
DEFAULT_LANE_IDS = frozenset({"todo", "in-progress", "done", "cancelled"})
# A board should never turn one organisation's full history into an unbounded response.
# This remains well above a practical active operational queue while keeping task and
# assignee lookup work predictable.
TASK_BOARD_QUERY_LIMIT = 10_000


class TaskError(ValueError):
    pass


def _display_name(user: User | None) -> str | None:
    if user is None:
        return None
    name = " ".join(part for part in (user.first_name, user.last_name) if part).strip()
    return name or user.email


def _user_names(session: Session, org_id: UUID, ids: set[UUID]) -> dict[UUID, str]:
    if not ids:
        return {}
    rows = session.query(User).filter(User.org_id == org_id, User.id.in_(ids)).limit(TASK_BOARD_QUERY_LIMIT).all()
    return {row.id: _display_name(row) or row.email for row in rows}


def _serialise_core_task(task: CoreTask, names: dict[UUID, str], *, archived: bool = False) -> dict[str, Any]:
    return {
        "id": str(task.id),
        "source": "core",
        "source_label": "System",
        "title": task.title,
        "description": task.description,
        "due_date": task.due_date.isoformat() if task.due_date else None,
        "status": task.status,
        "priority": task.priority,
        "assigned_to_user_id": str(task.assigned_to_user_id) if task.assigned_to_user_id else None,
        "assigned_to_name": names.get(task.assigned_to_user_id) if task.assigned_to_user_id else None,
        "created_by_user_id": str(task.created_by_user_id) if task.created_by_user_id else None,
        "completed_at": task.completed_at.isoformat() if task.completed_at else None,
        "created_at": task.created_at.isoformat() if task.created_at else None,
        "updated_at": task.updated_at.isoformat() if task.updated_at else None,
        "editable": True,
        "board_lane_id": str(task.board_lane_id) if task.board_lane_id else None,
        "archived": archived,
    }


def _serialise_crm_task(task: Any, names: dict[UUID, str], *, archived: bool = False) -> dict[str, Any]:
    return {
        "id": str(task.id),
        "source": "crm",
        "source_label": "CRM",
        "title": task.title,
        "description": task.description,
        "due_date": task.due_date.isoformat() if task.due_date else None,
        "status": task.status,
        "priority": task.priority,
        "assigned_to_user_id": str(task.assigned_to_user_id) if task.assigned_to_user_id else None,
        "assigned_to_name": names.get(task.assigned_to_user_id) if task.assigned_to_user_id else None,
        "created_by_user_id": str(task.created_by_user_id) if task.created_by_user_id else None,
        "completed_at": task.completed_at.isoformat() if task.completed_at else None,
        "created_at": task.created_at.isoformat() if task.created_at else None,
        "updated_at": task.updated_at.isoformat() if task.updated_at else None,
        "editable": False,
        "href": "/crm/tasks?task_id=" + str(task.id),
        "board_lane_id": str(task.board_lane_id) if task.board_lane_id else None,
        "archived": archived,
    }


def _archive_cutoff(config: dict[str, Any]) -> datetime:
    value = config["done_archive_value"]
    unit = config["done_archive_unit"]
    now = utc_now()
    if unit == "months":
        return datetime.combine(_add_months(now.date(), -value), datetime.min.time(), tzinfo=UTC)
    return now - timedelta(days=value * (7 if unit == "weeks" else 1))


def _archive_filter(model: Any, archive: str, cutoff: datetime):
    closed_at = func.coalesce(model.completed_at, model.updated_at, model.created_at)
    if archive == "archived":
        return and_(model.status.in_(("completed", "cancelled")), closed_at < cutoff)
    return or_(model.status.in_(OPEN_STATUSES), and_(model.status.in_(("completed", "cancelled")), closed_at >= cutoff))


def _all_task_rows(session: Session, org_id: UUID, source: str = "all", archive: str = "active") -> list[dict[str, Any]]:
    cutoff = _archive_cutoff(serialise_config(_config_row(session, org_id)))
    core_rows = (
        session.query(CoreTask)
        .filter(CoreTask.org_id == org_id, _archive_filter(CoreTask, archive, cutoff))
        .limit(TASK_BOARD_QUERY_LIMIT)
        .all()
        if source in {"all", "core"}
        else []
    )
    crm_rows = []
    if source in {"all", "crm"}:
        # CRM's storage is intentionally safe to read even when its product routes are
        # disabled: existing customer work remains visible in the Core work queue.
        # Core is mounted when CRM routes are off, but SQLAlchemy still needs the
        # contact table registered before it maps CRMTask.
        from app.features.crm.models.crm_task import CRMTask
        from app.features.crm.models.xero_contact import XeroContact

        _ = XeroContact

        crm_rows = (
            session.query(CRMTask)
            .filter(CRMTask.org_id == org_id, _archive_filter(CRMTask, archive, cutoff))
            .limit(TASK_BOARD_QUERY_LIMIT)
            .all()
        )
    ids = {row.assigned_to_user_id for row in core_rows + crm_rows if row.assigned_to_user_id}
    names = _user_names(session, org_id, ids)
    archived = archive == "archived"
    result = [_serialise_core_task(row, names, archived=archived) for row in core_rows]
    result.extend(_serialise_crm_task(row, names, archived=archived) for row in crm_rows)
    result.sort(key=lambda row: (row["due_date"] is None, row["due_date"] or "9999-12-31", row["created_at"] or ""))
    return result


def list_tasks(
    session: Session, org_id: UUID, source: str = "all", status: str | None = None, archive: str = "active"
) -> list[dict[str, Any]]:
    if source not in {"all", "core", "crm"}:
        raise TaskError("source must be all, core, or crm")
    if status and status not in ALL_STATUSES:
        raise TaskError("invalid status")
    if archive not in {"active", "archived"}:
        raise TaskError("archive must be active or archived")
    rows = _all_task_rows(session, org_id, source, archive)
    return [row for row in rows if not status or row["status"] == status]


def _parse_optional_date(raw: Any) -> date | None:
    if raw in {None, ""}:
        return None
    if isinstance(raw, date):
        return raw
    try:
        return date.fromisoformat(str(raw))
    except ValueError as exc:
        raise TaskError("due_date must be YYYY-MM-DD") from exc


def _parse_optional_user(session: Session, org_id: UUID, raw: Any) -> UUID | None:
    if raw in {None, ""}:
        return None
    try:
        user_id = UUID(str(raw))
    except (ValueError, TypeError, AttributeError) as exc:
        raise TaskError("assigned_to_user_id must be a UUID") from exc
    user = session.query(User).filter(User.org_id == org_id, User.id == user_id, User.is_active.is_(True)).first()
    if user is None:
        logger.warning("access_denied", reason="task_assignee_not_active_in_org", org_id=str(org_id), user_id=str(user_id))
        raise TaskError("assignee must be an active user in this organisation")
    return user_id


def _validate_task_fields(session: Session, org_id: UUID, data: dict[str, Any], *, creating: bool) -> dict[str, Any]:
    allowed = {"title", "description", "due_date", "priority", "status", "assigned_to_user_id"}
    unknown = set(data) - allowed
    if unknown:
        raise TaskError("unsupported fields: " + ", ".join(sorted(unknown)))
    if creating and not str(data.get("title") or "").strip():
        raise TaskError("title is required")
    fields: dict[str, Any] = {}
    if "title" in data:
        title = str(data["title"] or "").strip()
        if not title or len(title) > 500:
            raise TaskError("title must be 1-500 characters")
        fields["title"] = title
    if "description" in data:
        description = str(data["description"] or "").strip()
        if len(description) > 20_000:
            raise TaskError("description must be 20,000 characters or fewer")
        fields["description"] = description or None
    if "due_date" in data:
        fields["due_date"] = _parse_optional_date(data["due_date"])
    if "priority" in data:
        priority = str(data["priority"] or "").strip().lower()
        if priority not in PRIORITIES:
            raise TaskError("priority must be low, medium, or high")
        fields["priority"] = priority
    if "status" in data:
        status = str(data["status"] or "").strip().lower()
        if status not in ALL_STATUSES:
            raise TaskError("status must be pending, in_progress, completed, or cancelled")
        fields["status"] = status
    if "assigned_to_user_id" in data:
        fields["assigned_to_user_id"] = _parse_optional_user(session, org_id, data["assigned_to_user_id"])
    return fields


def _task_snapshot(task: CoreTask) -> dict[str, Any]:
    return {
        "title": task.title,
        "description": task.description,
        "due_date": task.due_date.isoformat() if task.due_date else None,
        "status": task.status,
        "priority": task.priority,
        "assigned_to_user_id": str(task.assigned_to_user_id) if task.assigned_to_user_id else None,
    }


def _diff(before: dict[str, Any], after: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {key: {"before": before[key], "after": after[key]} for key in before if before[key] != after[key]}


def create_task(session: Session, org_id: UUID, actor_id: UUID | None, data: dict[str, Any]) -> dict[str, Any]:
    fields = _validate_task_fields(session, org_id, data, creating=True)
    values = {"status": "pending", "priority": "medium"}
    values.update(fields)
    task = CoreTask(org_id=org_id, created_by_user_id=actor_id, **values)
    session.add(task)
    session.flush()
    snapshot = _task_snapshot(task)
    EventWriter(session, org_id).emit(
        event_type="core_task.created", entity_type="core_task", entity_id=task.id, payload=snapshot, actor_id=actor_id
    )
    session.commit()
    return _serialise_core_task(task, _user_names(session, org_id, {task.assigned_to_user_id} if task.assigned_to_user_id else set()))


def update_task(session: Session, org_id: UUID, actor_id: UUID | None, task_id: UUID, data: dict[str, Any]) -> dict[str, Any] | None:
    task = session.query(CoreTask).filter(CoreTask.org_id == org_id, CoreTask.id == task_id).first()
    if task is None:
        logger.warning("access_denied", reason="core_task_not_found_or_cross_org", org_id=str(org_id), task_id=str(task_id))
        return None
    before = _task_snapshot(task)
    fields = _validate_task_fields(session, org_id, data, creating=False)
    for key, value in fields.items():
        setattr(task, key, value)
    if fields.get("status") == "completed" and task.completed_at is None:
        task.completed_at = utc_now()
    elif fields.get("status") in OPEN_STATUSES:
        task.completed_at = None
    task.updated_at = utc_now()
    after = _task_snapshot(task)
    EventWriter(session, org_id).emit(
        event_type="core_task.updated",
        entity_type="core_task",
        entity_id=task.id,
        payload=after,
        diff=_diff(before, after),
        actor_id=actor_id,
    )
    session.commit()
    return _serialise_core_task(task, _user_names(session, org_id, {task.assigned_to_user_id} if task.assigned_to_user_id else set()))


def delete_task(session: Session, org_id: UUID, actor_id: UUID | None, task_id: UUID) -> bool:
    task = session.query(CoreTask).filter(CoreTask.org_id == org_id, CoreTask.id == task_id).first()
    if task is None:
        logger.warning("access_denied", reason="core_task_not_found_or_cross_org", org_id=str(org_id), task_id=str(task_id))
        return False
    EventWriter(session, org_id).emit(
        event_type="core_task.deleted", entity_type="core_task", entity_id=task.id, payload=_task_snapshot(task), actor_id=actor_id
    )
    session.delete(task)
    session.commit()
    return True


def _config_row(session: Session, org_id: UUID) -> CoreTaskConfig | None:
    return session.query(CoreTaskConfig).filter(CoreTaskConfig.org_id == org_id).first()


def serialise_config(row: CoreTaskConfig | None) -> dict[str, Any]:
    return {
        "due_notifications_enabled": True if row is None else row.due_notifications_enabled,
        "notification_lead_value": 7 if row is None else row.notification_lead_value,
        "notification_lead_unit": "days" if row is None else row.notification_lead_unit,
        "done_archive_value": 1 if row is None else row.done_archive_value,
        "done_archive_unit": "weeks" if row is None else row.done_archive_unit,
        "lane_order": [] if row is None else list(row.lane_order or []),
        "hidden_default_lanes": [] if row is None else list(row.hidden_default_lanes or []),
    }


def get_config(session: Session, org_id: UUID) -> dict[str, Any]:
    return serialise_config(_config_row(session, org_id))


def _validate_period(value: Any, unit: Any, *, prefix: str) -> tuple[int, str]:
    if type(value) is not int or not 1 <= value <= 3650:
        raise TaskError(f"{prefix}_value must be an integer from 1 to 3650")
    parsed_unit = str(unit or "").lower()
    if parsed_unit not in LEAD_UNITS:
        raise TaskError(f"{prefix}_unit must be days, weeks, or months")
    return value, parsed_unit


def update_config(session: Session, org_id: UUID, data: dict[str, Any]) -> dict[str, Any]:
    allowed = {
        "due_notifications_enabled", "notification_lead_value", "notification_lead_unit",
        "done_archive_value", "done_archive_unit", "lane_order", "hidden_default_lanes",
    }
    if set(data) - allowed:
        raise TaskError("unsupported configuration fields")
    row = _config_row(session, org_id)
    if row is None:
        row = CoreTaskConfig(org_id=org_id)
        session.add(row)
    if "due_notifications_enabled" in data:
        if not isinstance(data["due_notifications_enabled"], bool):
            raise TaskError("due_notifications_enabled must be true or false")
        row.due_notifications_enabled = data["due_notifications_enabled"]
    if "notification_lead_value" in data or "notification_lead_unit" in data:
        row.notification_lead_value, row.notification_lead_unit = _validate_period(
            data.get("notification_lead_value", row.notification_lead_value),
            data.get("notification_lead_unit", row.notification_lead_unit),
            prefix="notification_lead",
        )
    if "done_archive_value" in data or "done_archive_unit" in data:
        row.done_archive_value, row.done_archive_unit = _validate_period(
            data.get("done_archive_value", row.done_archive_value),
            data.get("done_archive_unit", row.done_archive_unit),
            prefix="done_archive",
        )
    if "lane_order" in data:
        order = data["lane_order"]
        if not isinstance(order, list) or len(order) > 100:
            raise TaskError("lane_order must be a list of up to 100 lane ids")
        clean_order = [str(lane_id).strip() for lane_id in order]
        if not all(clean_order) or len(clean_order) != len(set(clean_order)):
            raise TaskError("lane_order must contain unique lane ids")
        row.lane_order = clean_order
    if "hidden_default_lanes" in data:
        hidden = data["hidden_default_lanes"]
        if not isinstance(hidden, list):
            raise TaskError("hidden_default_lanes must be a list")
        clean_hidden = [str(lane_id).strip() for lane_id in hidden]
        if len(clean_hidden) != len(set(clean_hidden)) or not set(clean_hidden).issubset(DEFAULT_LANE_IDS):
            raise TaskError("hidden_default_lanes contains an invalid lane")
        row.hidden_default_lanes = clean_hidden
    session.commit()
    return serialise_config(row)


def _add_months(day: date, months: int) -> date:
    month_index = day.month - 1 + months
    year = day.year + month_index // 12
    month = month_index % 12 + 1
    return date(year, month, min(day.day, monthrange(year, month)[1]))


def task_due_summary(session: Session, org_id: UUID, today: date | None = None) -> dict[str, Any]:
    """Return open tasks split into due-soon and overdue for the system checks."""
    today = today or date.today()
    config = serialise_config(_config_row(session, org_id))
    rows = [row for row in _all_task_rows(session, org_id) if row["status"] in OPEN_STATUSES and row["due_date"]]
    overdue = [row for row in rows if date.fromisoformat(row["due_date"]) < today]
    due_soon: list[dict[str, Any]] = []
    if config["due_notifications_enabled"]:
        lead_value = config["notification_lead_value"]
        lead_unit = config["notification_lead_unit"]
        end = _add_months(today, lead_value) if lead_unit == "months" else date.fromordinal(
            today.toordinal() + lead_value * (7 if lead_unit == "weeks" else 1)
        )
        due_soon = [row for row in rows if today <= date.fromisoformat(row["due_date"]) <= end]
    return {"due_soon_tasks": due_soon, "overdue_tasks": overdue, "notification_policy": config}


def _serialise_lane(lane: TaskBoardLane) -> dict[str, Any]:
    return {"id": str(lane.id), "title": lane.title, "position": lane.position}


def list_lanes(session: Session, org_id: UUID, board: str) -> list[dict[str, Any]]:
    if board not in {"core", "crm"}:
        raise TaskError("invalid task board")
    rows = (
        session.query(TaskBoardLane)
        .filter(TaskBoardLane.org_id == org_id, TaskBoardLane.board == board)
        .order_by(TaskBoardLane.position, TaskBoardLane.created_by_user_id, TaskBoardLane.id)
        .all()
    )
    return [_serialise_lane(row) for row in rows]


def create_lane(session: Session, org_id: UUID, board: str, actor_id: UUID | None, data: dict[str, Any]) -> dict[str, Any]:
    if board not in {"core", "crm"}:
        raise TaskError("invalid task board")
    if set(data) - {"title"}:
        raise TaskError("unsupported lane fields")
    title = str(data.get("title") or "").strip()
    if not title or len(title) > 80:
        raise TaskError("lane title must be 1-80 characters")
    max_position = (
        session.query(TaskBoardLane.position)
        .filter(TaskBoardLane.org_id == org_id, TaskBoardLane.board == board)
        .order_by(TaskBoardLane.position.desc())
        .first()
    )
    lane = TaskBoardLane(
        org_id=org_id, board=board, title=title, position=(max_position[0] + 1 if max_position else 0), created_by_user_id=actor_id
    )
    session.add(lane)
    try:
        session.commit()
    except Exception as exc:
        session.rollback()
        raise TaskError("a lane with this name already exists") from exc
    return _serialise_lane(lane)


def update_lane(session: Session, org_id: UUID, board: str, lane_id: UUID, data: dict[str, Any]) -> dict[str, Any] | None:
    if board not in {"core", "crm"} or set(data) - {"title", "position"}:
        raise TaskError("unsupported lane fields")
    lane = session.query(TaskBoardLane).filter(TaskBoardLane.org_id == org_id, TaskBoardLane.board == board, TaskBoardLane.id == lane_id).first()
    if lane is None:
        return None
    if "title" in data:
        title = str(data["title"] or "").strip()
        if not title or len(title) > 80:
            raise TaskError("lane title must be 1-80 characters")
        lane.title = title
    if "position" in data:
        if type(data["position"]) is not int or data["position"] < 0:
            raise TaskError("position must be a non-negative integer")
        lane.position = data["position"]
    try:
        session.commit()
    except Exception as exc:
        session.rollback()
        raise TaskError("a lane with this name already exists") from exc
    return _serialise_lane(lane)


def reorder_lanes(session: Session, org_id: UUID, board: str, lane_ids: list[UUID]) -> list[dict[str, Any]]:
    """Persist an exact lane order as one transaction."""
    if board not in {"core", "crm"}:
        raise TaskError("invalid task board")
    if len(lane_ids) != len(set(lane_ids)):
        raise TaskError("lane_ids must not contain duplicates")
    rows = (
        session.query(TaskBoardLane)
        .filter(TaskBoardLane.org_id == org_id, TaskBoardLane.board == board)
        .order_by(TaskBoardLane.position, TaskBoardLane.id)
        .all()
    )
    by_id = {lane.id: lane for lane in rows}
    if set(lane_ids) != set(by_id):
        raise TaskError("lane_ids must contain every lane on this board")
    for position, lane_id in enumerate(lane_ids):
        by_id[lane_id].position = position
    session.commit()
    return [_serialise_lane(by_id[lane_id]) for lane_id in lane_ids]


def delete_lane(session: Session, org_id: UUID, board: str, lane_id: UUID) -> bool:
    lane = session.query(TaskBoardLane).filter(TaskBoardLane.org_id == org_id, TaskBoardLane.board == board, TaskBoardLane.id == lane_id).first()
    if lane is None:
        return False
    session.delete(lane)
    session.commit()
    return True


def assign_task_to_lane(session: Session, org_id: UUID, board: str, task_id: UUID, lane_id: UUID | None) -> dict[str, Any] | None:
    if board not in {"core", "crm"}:
        raise TaskError("invalid task board")
    if board == "core":
        task = session.query(CoreTask).filter(CoreTask.org_id == org_id, CoreTask.id == task_id).first()
    else:
        from app.features.crm.models.crm_task import CRMTask
        from app.features.crm.models.xero_contact import XeroContact

        _ = XeroContact
        task = session.query(CRMTask).filter(CRMTask.org_id == org_id, CRMTask.id == task_id).first()
    if task is None:
        return None
    if lane_id is not None:
        lane = session.query(TaskBoardLane).filter(TaskBoardLane.org_id == org_id, TaskBoardLane.board == board, TaskBoardLane.id == lane_id).first()
        if lane is None:
            raise TaskError("lane not found")
    task.board_lane_id = lane_id
    session.commit()
    return {"id": str(task.id), "board_lane_id": str(lane_id) if lane_id else None}


def register_routes(bp) -> None:
    """Attach Core Task JSON routes to the always-mounted Core blueprint."""

    def org_id() -> UUID:
        return UUID(g.org_id)

    @bp.route("/api/core/tasks", methods=["GET"])
    @requires_auth
    def list_core_tasks():
        try:
            return jsonify({
                "tasks": list_tasks(
                    db_session(),
                    org_id(),
                    request.args.get("source", "all"),
                    request.args.get("status"),
                    request.args.get("archive", "active"),
                )
            })
        except TaskError as exc:
            return jsonify({"error": str(exc)}), 400

    @bp.route("/api/core/tasks", methods=["POST"])
    @requires_auth
    def create_core_task():
        try:
            task = create_task(db_session(), org_id(), UUID(g.user_id) if g.user_id else None, request.get_json(silent=True) or {})
            return jsonify({"task": task}), 201
        except TaskError as exc:
            db_session().rollback()
            return jsonify({"error": str(exc)}), 400

    @bp.route("/api/core/tasks/<task_id>", methods=["PUT"])
    @requires_auth
    def update_core_task(task_id: str):
        try:
            task = update_task(
                db_session(), org_id(), UUID(g.user_id) if g.user_id else None, UUID(task_id), request.get_json(silent=True) or {}
            )
            if task is None:
                return jsonify({"error": "Task not found"}), 404
            return jsonify({"task": task})
        except (TaskError, ValueError) as exc:
            db_session().rollback()
            return jsonify({"error": str(exc)}), 400

    @bp.route("/api/core/tasks/<task_id>", methods=["DELETE"])
    @requires_auth
    def delete_core_task(task_id: str):
        try:
            deleted = delete_task(db_session(), org_id(), UUID(g.user_id) if g.user_id else None, UUID(task_id))
            if not deleted:
                return jsonify({"error": "Task not found"}), 404
            return jsonify({"ok": True})
        except ValueError:
            return jsonify({"error": "task_id must be a UUID"}), 400

    @bp.route("/api/core/tasks/configuration", methods=["GET"])
    @requires_auth
    def get_task_configuration():
        return jsonify(get_config(db_session(), org_id()))

    @bp.route("/api/core/tasks/configuration", methods=["PUT"])
    @requires_auth
    def save_task_configuration():
        try:
            return jsonify(update_config(db_session(), org_id(), request.get_json(silent=True) or {}))
        except TaskError as exc:
            db_session().rollback()
            return jsonify({"error": str(exc)}), 400

    @bp.route("/api/core/tasks/lanes", methods=["GET"])
    @requires_auth
    def list_core_task_lanes():
        return jsonify({"lanes": list_lanes(db_session(), org_id(), "core")})

    @bp.route("/api/core/tasks/lanes", methods=["POST"])
    @requires_auth
    def create_core_task_lane():
        try:
            lane = create_lane(db_session(), org_id(), "core", UUID(g.user_id) if g.user_id else None, request.get_json(silent=True) or {})
            return jsonify({"lane": lane}), 201
        except TaskError as exc:
            return jsonify({"error": str(exc)}), 400

    @bp.route("/api/core/tasks/lanes/<lane_id>", methods=["PUT"])
    @requires_auth
    def update_core_task_lane(lane_id: str):
        try:
            lane = update_lane(db_session(), org_id(), "core", UUID(lane_id), request.get_json(silent=True) or {})
            if lane is None:
                return jsonify({"error": "Lane not found"}), 404
            return jsonify({"lane": lane})
        except (TaskError, ValueError) as exc:
            return jsonify({"error": str(exc)}), 400

    @bp.route("/api/core/tasks/lanes/order", methods=["PUT"])
    @requires_auth
    def reorder_core_task_lanes():
        data = request.get_json(silent=True) or {}
        try:
            raw_ids = data.get("lane_ids")
            if set(data) != {"lane_ids"} or not isinstance(raw_ids, list):
                raise TaskError("lane_ids is required")
            lanes = reorder_lanes(db_session(), org_id(), "core", [UUID(raw_id) for raw_id in raw_ids])
            return jsonify({"lanes": lanes})
        except (TaskError, ValueError, TypeError) as exc:
            return jsonify({"error": str(exc)}), 400

    @bp.route("/api/core/tasks/lanes/<lane_id>", methods=["DELETE"])
    @requires_auth
    def delete_core_task_lane(lane_id: str):
        try:
            if not delete_lane(db_session(), org_id(), "core", UUID(lane_id)):
                return jsonify({"error": "Lane not found"}), 404
            return jsonify({"ok": True})
        except ValueError:
            return jsonify({"error": "lane_id must be a UUID"}), 400

    @bp.route("/api/core/tasks/<task_id>/lane", methods=["PUT"])
    @requires_auth
    def assign_core_task_lane(task_id: str):
        data = request.get_json(silent=True) or {}
        try:
            if set(data) != {"lane_id"}:
                raise TaskError("lane_id is required")
            lane_id = UUID(data["lane_id"]) if data["lane_id"] else None
            task = assign_task_to_lane(db_session(), org_id(), "core", UUID(task_id), lane_id)
            if task is None:
                return jsonify({"error": "Task not found"}), 404
            return jsonify({"task": task})
        except (TaskError, ValueError, TypeError) as exc:
            return jsonify({"error": str(exc)}), 400
