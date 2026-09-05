"""Business logic for operational_cases (A1): eligibility, lifecycle transitions,
idempotency and per-source locking. Routes stay thin; every rule from
.agents/specs/operational_cases.md lives here.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.backend.event_writer import EventWriter
from app.core.db.models.api_idempotency_key import ApiIdempotencyKey
from app.core.db.models.user import User, UserRole
from app.core.db.repositories.execution_repo import ExecutionRepository
from app.core.db.repositories.inventory_repo import InventoryRepository
from app.core.db.repositories.user_repo import UserRepository
from app.core.security.entitlements import org_has_feature
from app.features.operational_cases.adapters import untracked_items_adapter
from app.features.operational_cases.models.operational_case import (
    CaseCauseCategory,
    CaseSeverity,
    CaseStatus,
    OperationalCase,
)
from app.features.operational_cases.models.operational_case_event import OperationalCaseEvent
from app.features.operational_cases.models.operational_case_link import CaseLinkRelation
from app.features.operational_cases.repositories.operational_case_event_repo import OperationalCaseEventRepository
from app.features.operational_cases.repositories.operational_case_link_repo import OperationalCaseLinkRepository
from app.features.operational_cases.repositories.operational_case_repo import (
    OperationalCaseRepository,
    decode_cursor,
    encode_cursor,
    filters_signature,
)
from app.observability import get_logger
from app.utils.config_loader import config

logger = get_logger(__name__)

OPERATIONAL_CASES_FEATURE_KEY = "operational_cases"
SOURCE_TYPE_CORE_FINDING = "core_finding"

_ALLOWED_EVIDENCE_TYPES = {"execution", "execution_evidence", "inventory_item"}
_MAX_EVIDENCE_REFS = 10

_TRANSITION_EVENTS = {
    (CaseStatus.OPEN, CaseStatus.ACKNOWLEDGED): "operational_case.acknowledged",
    (CaseStatus.ACKNOWLEDGED, CaseStatus.IN_PROGRESS): "operational_case.started",
    (CaseStatus.IN_PROGRESS, CaseStatus.RESOLVED): "operational_case.resolved",
    (CaseStatus.RESOLVED, CaseStatus.VERIFIED): "operational_case.verified",
    (CaseStatus.RESOLVED, CaseStatus.IN_PROGRESS): "operational_case.reopened",
}


class CaseError(Exception):
    """Carries an HTTP status + machine error code for the route layer to translate."""

    def __init__(self, status: int, code: str, message: str, extra: dict | None = None):
        self.status = status
        self.code = code
        self.message = message
        self.extra = extra or {}
        super().__init__(message)


# ---------------------------------------------------------------------------
# Small validation helpers
# ---------------------------------------------------------------------------


def _validate_text(value: Any, field: str, min_len: int = 1, max_len: int = 2000) -> str:
    if not isinstance(value, str):
        raise CaseError(400, f"{field}_invalid", f"{field} must be a string")
    trimmed = value.strip()
    if not (min_len <= len(trimmed) <= max_len):
        raise CaseError(400, f"{field}_invalid", f"{field} must be {min_len}-{max_len} characters")
    return trimmed


def _parse_iso_datetime(value: Any, field: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise CaseError(400, f"{field}_invalid", f"{field} must be an ISO-8601 timestamp")
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        raise CaseError(400, f"{field}_invalid", f"{field} must be a valid ISO-8601 timestamp") from None
    if parsed.tzinfo is None:
        raise CaseError(400, f"{field}_invalid", f"{field} must be timezone-aware (UTC)")
    return parsed.astimezone(UTC)


def _validate_due_at_future(due_at: datetime) -> None:
    if due_at <= datetime.now(UTC):
        raise CaseError(400, "due_at_invalid", "due_at must be in the future")


def _validate_owner(session: Session, org_id: UUID, owner_id: UUID) -> User:
    # Commands may already have loaded the case owner into this request's identity
    # map.  Re-read it so an account deactivated by another request cannot continue
    # to own a case through a stale ORM instance.
    user = session.query(User).filter(User.id == owner_id, User.org_id == org_id).populate_existing().one_or_none()
    if not user:
        raise CaseError(404, "invalid_owner", "member not found")
    if not user.is_active:
        raise CaseError(400, "invalid_owner", "owner must be active")
    return user


def _validate_evidence_refs(session: Session, org_id: UUID, refs: Any) -> list[dict]:
    if refs is None:
        return []
    if not isinstance(refs, list) or len(refs) > _MAX_EVIDENCE_REFS:
        raise CaseError(400, "evidence_invalid", f"evidence_refs must be a list of at most {_MAX_EVIDENCE_REFS} items")
    validated = []
    for ref in refs:
        if not isinstance(ref, dict):
            raise CaseError(400, "evidence_invalid", "each evidence_ref must be an object")
        if set(ref) != {"entity_type", "entity_id"}:
            raise CaseError(400, "evidence_invalid", "unsupported evidence fields")
        entity_type = ref.get("entity_type")
        if entity_type not in _ALLOWED_EVIDENCE_TYPES:
            raise CaseError(400, "evidence_invalid", f"unsupported evidence entity_type: {entity_type!r}")
        try:
            entity_id = UUID(str(ref.get("entity_id")))
        except (ValueError, TypeError):
            raise CaseError(400, "evidence_invalid", "evidence entity_id must be a UUID") from None
        if not _evidence_entity_exists(session, org_id, entity_type, entity_id):
            raise CaseError(404, "evidence_invalid", "evidence reference not found")
        validated.append({"entity_type": entity_type, "entity_id": str(entity_id)})
    return validated


def _evidence_entity_exists(session: Session, org_id: UUID, entity_type: str, entity_id: UUID) -> bool:
    if entity_type == "execution":
        return ExecutionRepository(session).get_execution_by_id(entity_id, org_id) is not None
    if entity_type == "execution_evidence":
        from app.core.db.models.execution_evidence import ExecutionEvidence

        return (
            session.query(ExecutionEvidence.id)
            .filter(
                ExecutionEvidence.org_id == org_id,
                ExecutionEvidence.id == entity_id,
                ExecutionEvidence.evidence_status == "active",
            )
            .first()
            is not None
        )
    if entity_type == "inventory_item":
        return InventoryRepository(session).get_inventory_item_by_id(entity_id, org_id) is not None
    return False


def _build_title(item_name: str) -> str:
    title = f"Untracked stock: {item_name}" if item_name else "Untracked stock case"
    return title[:200]


# ---------------------------------------------------------------------------
# Advisory locking + idempotency harness
# ---------------------------------------------------------------------------


def _pg_advisory_lock(session: Session, *parts: str) -> None:
    """Transaction-scoped advisory lock, released automatically at commit/rollback.
    No-op on non-PostgreSQL dialects (see backend.py's identical wastage-idempotency
    helper for the same tradeoff: correctness still relies on the unique DB constraints,
    concurrent duplicates just aren't pre-empted before they hit one)."""
    bind = session.get_bind()
    if not bind or getattr(bind.dialect, "name", None) != "postgresql":
        return
    digest = hashlib.sha256(":".join(parts).encode()).digest()
    k1 = int.from_bytes(digest[0:4], "big") & 0x7FFFFFFF
    k2 = int.from_bytes(digest[4:8], "big") & 0x7FFFFFFF
    session.execute(text("SELECT pg_advisory_xact_lock(:k1, :k2)"), {"k1": k1, "k2": k2})


def _source_lock(
    session: Session, org_id: UUID, source_type: str, check_id: str, source_entity_type: str, source_entity_id: UUID
) -> None:
    _pg_advisory_lock(
        session, "oc_source", str(org_id), source_type, check_id, source_entity_type, str(source_entity_id)
    )


def _idempotency_key(actor_id: UUID, method: str, route: str, client_key: str) -> str:
    digest = hashlib.sha256(f"{actor_id}:{method}:{route}:{client_key}".encode()).hexdigest()
    return f"oc:{digest}"


def _payload_hash(payload: dict) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()


def _validate_idempotency_key(client_key: Any) -> str:
    if not isinstance(client_key, str) or not (1 <= len(client_key) <= 128):
        raise CaseError(400, "idempotency_key_invalid", "Idempotency-Key must be 1-128 characters")
    return client_key


def _check_command_access(session, org_id, actor_id):
    actor = UserRepository(session).get_user_by_id(actor_id, org_id=org_id)
    if not actor or not actor.is_active:
        raise CaseError(403, "forbidden", "active organisation member required")
    if not config.operational_cases_enabled or not org_has_feature(session, org_id, OPERATIONAL_CASES_FEATURE_KEY):
        raise CaseError(404, "not_enabled", "not found")


def _lock_case(session, org_id, case_id):
    repo = OperationalCaseRepository(session)
    case = repo.get_by_id(case_id, org_id)
    if case is None:
        raise CaseError(404, "case_not_found", "case not found")
    _source_lock(session, org_id, case.source_type, case.check_id, case.source_entity_type, case.source_entity_id)
    return repo.get_by_id_for_update(case_id, org_id)


def run_idempotent_command(
    session: Session,
    org_id: UUID,
    actor_id: UUID,
    method: str,
    route: str,
    client_key: str,
    payload_for_hash: dict,
    command_fn,
) -> tuple[dict, int]:
    """Shared idempotency harness for every mutating case command.

    Replays an identical retry verbatim; 409s a changed payload under the same key;
    rolls back (storing nothing) when command_fn raises, so a failed/ineligible attempt
    creates no case/domain event and the same key can be retried with corrected data.
    """
    _check_command_access(session, org_id, actor_id)
    client_key = _validate_idempotency_key(client_key)
    idem_key = _idempotency_key(actor_id, method, route, client_key)
    payload_hash = _payload_hash(payload_for_hash)

    _pg_advisory_lock(session, "oc_idem", str(org_id), idem_key)
    existing = (
        session.query(ApiIdempotencyKey)
        .filter(ApiIdempotencyKey.org_id == org_id, ApiIdempotencyKey.key == idem_key)
        .one_or_none()
    )
    if existing:
        if existing.payload_hash != payload_hash:
            raise CaseError(
                409, "idempotency_payload_mismatch", "Idempotency key already used with a different payload"
            )
        stored = json.loads(existing.response_json)
        if isinstance(stored, dict):
            stored = {**stored, "idempotent_replay": True}
        return stored, existing.http_status

    try:
        body, status = command_fn()
    except CaseError:
        session.rollback()
        raise
    except Exception:
        session.rollback()
        raise

    session.add(
        ApiIdempotencyKey(
            org_id=org_id,
            key=idem_key,
            payload_hash=payload_hash,
            response_json=json.dumps(body, default=str),
            http_status=status,
        )
    )
    try:
        _check_command_access(session, org_id, actor_id)
        session.commit()
    except IntegrityError:
        session.rollback()
        existing = (
            session.query(ApiIdempotencyKey)
            .filter(ApiIdempotencyKey.org_id == org_id, ApiIdempotencyKey.key == idem_key)
            .one_or_none()
        )
        if existing and existing.payload_hash == payload_hash:
            stored = json.loads(existing.response_json)
            if isinstance(stored, dict):
                stored = {**stored, "idempotent_replay": True}
            return stored, existing.http_status
        raise CaseError(409, "conflict", "Conflict recording case command") from None
    logger.info(
        "operational_case_command_committed", org_id=str(org_id), actor_id=str(actor_id), route=route, status=status
    )
    return body, status


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------


def serialize_case_compact(case: OperationalCase) -> dict:
    owner = getattr(case, "owner", None)
    return {
        "id": str(case.id),
        "title": case.title,
        "severity": case.severity,
        "status": case.status,
        "owner_id": str(case.owner_id) if case.owner_id else None,
        "owner_active": bool(owner and owner.is_active),
        "owner_email": owner.email if owner is not None else None,
        "due_at": case.due_at.isoformat(),
        "next_action": case.next_action[:120],
        "version": case.version,
        "source_type": case.source_type,
        "check_id": case.check_id,
        "source_entity_type": case.source_entity_type,
        "source_entity_id": str(case.source_entity_id),
        "previous_case_id": str(case.previous_case_id) if case.previous_case_id else None,
        "created_by": str(case.created_by),
        "created_at": case.created_at.isoformat(),
        "updated_at": case.updated_at.isoformat(),
    }


def _serialize_event(event: OperationalCaseEvent) -> dict:
    return {
        "id": str(event.id),
        "case_version": event.case_version,
        "event_type": event.event_type,
        "actor_id": str(event.actor_id) if event.actor_id else None,
        "actor_label": event.actor_label,
        "occurred_at": event.occurred_at.isoformat(),
        "payload": event.payload,
    }


def _latest_event(session: Session, org_id: UUID, case_id: UUID, event_type: str) -> OperationalCaseEvent | None:
    return (
        session.query(OperationalCaseEvent)
        .filter(
            OperationalCaseEvent.org_id == org_id,
            OperationalCaseEvent.case_id == case_id,
            OperationalCaseEvent.event_type == event_type,
        )
        .order_by(OperationalCaseEvent.case_version.desc())
        .first()
    )


def _latest_source_observation(session: Session, org_id: UUID, case: OperationalCase) -> dict:
    row = (
        session.query(OperationalCaseEvent)
        .filter(
            OperationalCaseEvent.org_id == org_id,
            OperationalCaseEvent.case_id == case.id,
            OperationalCaseEvent.event_type.in_(["operational_case.created", "operational_case.source_observed"]),
        )
        .order_by(OperationalCaseEvent.case_version.desc())
        .first()
    )
    if row is not None:
        return {
            "state": row.payload.get("source_state"),
            "observed_at": row.payload.get("observed_at") or case.source_snapshot.get("observed_at"),
        }
    return {"state": "active", "observed_at": case.source_snapshot.get("observed_at")}


def _permitted_actions(session: Session, org_id: UUID, case: OperationalCase, actor: User) -> list[str]:
    actions: list[str] = []
    is_owner = actor.id == case.owner_id
    is_admin = actor.role == UserRole.ADMIN

    if case.status in CaseStatus.ACTIVE:
        if is_owner or is_admin:
            actions.append("edit")
        if is_admin:
            actions.append("reassign")
        actions.append("refresh_source")
        if is_admin:
            actions.append("dismiss")

    if case.status == CaseStatus.OPEN and (is_owner or is_admin):
        actions.append("acknowledge")
    if case.status == CaseStatus.ACKNOWLEDGED and (is_owner or is_admin):
        actions.append("start")
    if case.status == CaseStatus.IN_PROGRESS and (is_owner or is_admin):
        actions.append("resolve")
    if case.status == CaseStatus.RESOLVED:
        resolved_by = _latest_event(session, org_id, case.id, "operational_case.resolved")
        resolver_id = resolved_by.actor_id if resolved_by else None
        if actor.id != case.owner_id and actor.id != resolver_id:
            actions.append("verify")
        if is_owner or is_admin:
            actions.append("reopen")
    return actions


# ---------------------------------------------------------------------------
# Create from finding
# ---------------------------------------------------------------------------


def _do_create_case_from_finding(session: Session, org_id: UUID, actor: User, params: dict) -> tuple[dict, int]:
    source_entity_id: UUID = params["source_entity_id"]
    next_action = _validate_text(params.get("next_action"), "next_action")
    due_at = _parse_iso_datetime(params.get("due_at"), "due_at")
    _validate_due_at_future(due_at)
    owner = _validate_owner(session, org_id, params.get("owner_id"))

    previous_case_id = params.get("previous_case_id")
    recurrence_reason_raw = params.get("recurrence_reason")

    check_id = untracked_items_adapter.CHECK_ID
    source_entity_type = untracked_items_adapter.SOURCE_ENTITY_TYPE

    _source_lock(session, org_id, SOURCE_TYPE_CORE_FINDING, check_id, source_entity_type, source_entity_id)

    case_repo = OperationalCaseRepository(session)
    existing_active = case_repo.get_active_by_source_for_update(
        org_id, SOURCE_TYPE_CORE_FINDING, check_id, source_entity_type, source_entity_id
    )
    if existing_active is not None:
        return {"case": serialize_case_compact(existing_active), "created": False}, 200

    try:
        observation = untracked_items_adapter.evaluate(session, org_id, source_entity_id)
    except untracked_items_adapter.InvalidSourceDataError as exc:
        raise CaseError(400, "invalid_source_data", str(exc)) from exc

    if observation.state == untracked_items_adapter.STATE_DELETED:
        raise CaseError(404, "source_not_found", "source item not found")
    if observation.state == untracked_items_adapter.STATE_UNKNOWN:
        raise CaseError(409, "source_evaluation_unknown", "could not confirm source eligibility")
    if not observation.eligible_for_creation:
        raise CaseError(409, "source_not_eligible", "source is not eligible for a new case")

    latest_terminal = case_repo.get_latest_terminal_by_source(
        org_id, SOURCE_TYPE_CORE_FINDING, check_id, source_entity_type, source_entity_id
    )
    validated_previous_case_id = None
    recurrence_reason = None
    if latest_terminal is not None:
        if previous_case_id is None:
            raise CaseError(
                409,
                "requires_new_occurrence",
                "an explicit new-occurrence action is required for this source",
                extra={"previous_case": serialize_case_compact(latest_terminal)},
            )
        predecessor = case_repo.get_by_id(previous_case_id, org_id)
        if predecessor is None:
            raise CaseError(404, "predecessor_not_found", "previous_case_id not found")
        if predecessor.id != latest_terminal.id:
            raise CaseError(
                409, "stale_predecessor", "previous_case_id is not the latest terminal case for this source"
            )
        recurrence_reason = _validate_text(recurrence_reason_raw, "recurrence_reason")
        validated_previous_case_id = predecessor.id
    elif previous_case_id is not None:
        # No terminal predecessor exists for this source at all. Still validate the
        # referenced id's own org scope first -- a foreign-org id must 404 like any other
        # cross-tenant lookup, not surface as a same-org "wrong predecessor" 409.
        if case_repo.get_by_id(previous_case_id, org_id) is None:
            raise CaseError(404, "predecessor_not_found", "previous_case_id not found")
        raise CaseError(409, "stale_predecessor", "no terminal predecessor exists for this source")

    snapshot = observation.snapshot
    title = _build_title(snapshot["item_name"])

    case = OperationalCase(
        org_id=org_id,
        title=title,
        severity=CaseSeverity.CRITICAL,
        source_type=SOURCE_TYPE_CORE_FINDING,
        check_id=check_id,
        source_entity_type=source_entity_type,
        source_entity_id=source_entity_id,
        source_snapshot=snapshot,
        status=CaseStatus.OPEN,
        owner_id=owner.id,
        due_at=due_at,
        next_action=next_action,
        version=1,
        previous_case_id=validated_previous_case_id,
        created_by=actor.id,
    )
    case_repo.create(case)

    OperationalCaseLinkRepository(session).add(
        org_id=org_id,
        case_id=case.id,
        relation=CaseLinkRelation.SOURCE,
        entity_type=source_entity_type,
        entity_id=source_entity_id,
        created_by=actor.id,
    )

    event_payload = {
        "case_id": str(case.id),
        "version": 1,
        "source_type": SOURCE_TYPE_CORE_FINDING,
        "check_id": check_id,
        "source_entity_type": source_entity_type,
        "source_entity_id": str(source_entity_id),
        "source_state": "active",
        "observed_at": observation.observed_at.isoformat(),
        "previous_case_id": str(validated_previous_case_id) if validated_previous_case_id else None,
        "recurrence_reason": recurrence_reason,
    }
    entity_event = EventWriter(session, org_id).emit(
        event_type="operational_case.created",
        entity_type="operational_case",
        entity_id=case.id,
        payload=event_payload,
        actor_id=actor.id,
    )
    OperationalCaseEventRepository(session).add(
        org_id=org_id,
        case_id=case.id,
        case_version=1,
        event_type="operational_case.created",
        actor_id=actor.id,
        actor_label=actor.email,
        payload=event_payload,
        entity_event_id=entity_event.id,
    )
    session.flush()
    return {"case": serialize_case_compact(case), "created": True}, 201


def create_case_from_finding(
    session: Session, org_id: UUID, actor: User, params: dict, idempotency_key: str
) -> tuple[dict, int]:
    payload_for_hash = {
        "source_entity_id": str(params.get("source_entity_id")),
        "owner_id": str(params.get("owner_id")),
        "due_at": params.get("due_at"),
        "next_action": params.get("next_action"),
        "previous_case_id": str(params["previous_case_id"]) if params.get("previous_case_id") else None,
        "recurrence_reason": params.get("recurrence_reason"),
    }
    route = "/api/core/cases/from-finding"
    return run_idempotent_command(
        session,
        org_id,
        actor.id,
        "POST",
        route,
        idempotency_key,
        payload_for_hash,
        command_fn=lambda: _do_create_case_from_finding(session, org_id, actor, params),
    )


# ---------------------------------------------------------------------------
# Patch (owner/due/next_action)
# ---------------------------------------------------------------------------


def _apply_patch(
    session: Session, org_id: UUID, case: OperationalCase, actor: User, fields: dict, expected_version: int
) -> tuple[dict, int]:
    if case.version != expected_version:
        raise CaseError(
            409,
            "stale_version",
            "expected_version does not match the current case version",
            extra={"current_version": case.version, "case": serialize_case_compact(case)},
        )
    if case.status not in CaseStatus.ACTIVE:
        raise CaseError(409, "case_terminal", "terminal cases have no edit endpoint")

    allowed_keys = {"owner_id", "due_at", "next_action"}
    unsupported = set(fields.keys()) - allowed_keys
    if unsupported:
        raise CaseError(400, "unsupported_fields", f"unsupported fields: {sorted(unsupported)}")

    is_admin = actor.role == UserRole.ADMIN
    is_owner = actor.id == case.owner_id
    changes: dict[str, Any] = {}

    if "owner_id" in fields:
        if not is_admin:
            raise CaseError(403, "forbidden", "only ADMIN may reassign a case owner")
        try:
            new_owner_id = UUID(str(fields["owner_id"]))
        except (ValueError, TypeError):
            raise CaseError(400, "invalid_owner", "owner_id must be a UUID") from None
        new_owner = _validate_owner(session, org_id, new_owner_id)
        changes["owner_id"] = {"from": str(case.owner_id), "to": str(new_owner.id)}
        case.owner_id = new_owner.id

    if "owner_id" not in fields:
        _validate_owner(session, org_id, case.owner_id)

    if "due_at" in fields:
        if not (is_owner or is_admin):
            raise CaseError(403, "forbidden", "only the owner or ADMIN may edit the due date")
        new_due = _parse_iso_datetime(fields["due_at"], "due_at")
        _validate_due_at_future(new_due)
        changes["due_at"] = {"from": case.due_at.isoformat(), "to": new_due.isoformat()}
        case.due_at = new_due

    if "next_action" in fields:
        if not (is_owner or is_admin):
            raise CaseError(403, "forbidden", "only the owner or ADMIN may edit the next action")
        new_next_action = _validate_text(fields["next_action"], "next_action")
        changes["next_action"] = {"from": case.next_action, "to": new_next_action}
        case.next_action = new_next_action

    if not changes:
        raise CaseError(400, "no_changes", "at least one of owner_id/due_at/next_action must be provided")

    case.version += 1
    new_version = case.version
    entity_event = EventWriter(session, org_id).emit(
        event_type="operational_case.updated",
        entity_type="operational_case",
        entity_id=case.id,
        payload={"case_id": str(case.id), "version": new_version, "changes": changes},
        actor_id=actor.id,
    )
    OperationalCaseEventRepository(session).add(
        org_id=org_id,
        case_id=case.id,
        case_version=new_version,
        event_type="operational_case.updated",
        actor_id=actor.id,
        actor_label=actor.email,
        payload={"changes": changes},
        entity_event_id=entity_event.id,
    )
    session.flush()
    return {"case": serialize_case_compact(case)}, 200


def apply_patch(
    session: Session,
    org_id: UUID,
    actor: User,
    case_id: UUID,
    fields: dict,
    expected_version: int,
    idempotency_key: str,
) -> tuple[dict, int]:
    case = OperationalCaseRepository(session).get_by_id(case_id, org_id)
    if case is None:
        raise CaseError(404, "case_not_found", "case not found")
    route = f"/api/core/cases/{case_id}"
    payload_for_hash = {"fields": fields, "expected_version": expected_version}
    return run_idempotent_command(
        session,
        org_id,
        actor.id,
        "PATCH",
        route,
        idempotency_key,
        payload_for_hash,
        command_fn=lambda: _apply_patch(
            session, org_id, _lock_case(session, org_id, case_id), actor, fields, expected_version
        ),
    )


# ---------------------------------------------------------------------------
# Transitions
# ---------------------------------------------------------------------------


def _authorize_and_validate_transition(
    session: Session, org_id: UUID, case: OperationalCase, target_status: str, actor: User, fields: dict
) -> dict:
    allowed = {
        "acknowledged": set(),
        "in_progress": {"reopen_reason"},
        "resolved": {"cause", "cause_detail", "action_taken", "outcome", "evidence_refs"},
        "verified": {"verification_note"},
        "dismissed": {"reason"},
    }.get(target_status, set())
    if case.status == CaseStatus.ACKNOWLEDGED and target_status == "in_progress":
        allowed = set()
    if set(fields) - allowed:
        raise CaseError(400, "unsupported_fields", "unsupported transition fields")
    from_status = case.status
    is_owner = actor.id == case.owner_id
    is_admin = actor.role == UserRole.ADMIN

    if target_status == CaseStatus.DISMISSED:
        if from_status not in CaseStatus.ACTIVE:
            raise CaseError(409, "invalid_transition", f"cannot dismiss a case in status {from_status}")
        if not is_admin:
            raise CaseError(403, "forbidden", "dismissal requires ADMIN")
        reason = _validate_text(fields.get("reason"), "reason")
        return {"reason": reason}

    key = (from_status, target_status)
    if key not in _TRANSITION_EVENTS:
        raise CaseError(409, "invalid_transition", f"cannot transition from {from_status} to {target_status}")

    if target_status == CaseStatus.ACKNOWLEDGED:
        if not (is_owner or is_admin):
            raise CaseError(403, "forbidden", "only the owner or ADMIN may acknowledge")
        return {}

    if target_status == CaseStatus.IN_PROGRESS and from_status == CaseStatus.ACKNOWLEDGED:
        if not (is_owner or is_admin):
            raise CaseError(403, "forbidden", "only the owner or ADMIN may start work")
        return {}

    if target_status == CaseStatus.RESOLVED:
        if not (is_owner or is_admin):
            raise CaseError(403, "forbidden", "only the owner or ADMIN may resolve")
        cause = fields.get("cause")
        if cause not in CaseCauseCategory.ALL:
            raise CaseError(400, "cause_invalid", "cause must be one of the defined categories")
        cause_detail = None
        if cause == CaseCauseCategory.OTHER:
            cause_detail = _validate_text(fields.get("cause_detail"), "cause_detail")
        action_taken = _validate_text(fields.get("action_taken"), "action_taken")
        outcome = _validate_text(fields.get("outcome"), "outcome")
        evidence_refs = _validate_evidence_refs(session, org_id, fields.get("evidence_refs"))
        return {
            "cause": cause,
            "cause_detail": cause_detail,
            "action_taken": action_taken,
            "outcome": outcome,
            "evidence_refs": evidence_refs,
        }

    if target_status == CaseStatus.VERIFIED:
        resolved_by = _latest_event(session, org_id, case.id, "operational_case.resolved")
        resolver_id = resolved_by.actor_id if resolved_by else None
        if actor.id == case.owner_id or (resolver_id and actor.id == resolver_id):
            raise CaseError(403, "forbidden", "verification requires an independent actor")
        note = _validate_text(fields.get("verification_note"), "verification_note")
        return {"verification_note": note}

    if target_status == CaseStatus.IN_PROGRESS and from_status == CaseStatus.RESOLVED:
        if not (is_owner or is_admin):
            raise CaseError(403, "forbidden", "only the owner or ADMIN may reopen")
        reason = _validate_text(fields.get("reopen_reason"), "reopen_reason")
        return {"reopen_reason": reason}

    raise CaseError(409, "invalid_transition", "unsupported transition")  # pragma: no cover -- defensive


def _apply_transition(
    session: Session,
    org_id: UUID,
    case: OperationalCase,
    target_status: str,
    actor: User,
    fields: dict,
    expected_version: int,
) -> tuple[dict, int]:
    if case.version != expected_version:
        raise CaseError(
            409,
            "stale_version",
            "expected_version does not match the current case version",
            extra={"current_version": case.version, "case": serialize_case_compact(case)},
        )

    _validate_owner(session, org_id, case.owner_id)
    validated = _authorize_and_validate_transition(session, org_id, case, target_status, actor, fields)

    if target_status == CaseStatus.VERIFIED:
        _source_lock(session, org_id, case.source_type, case.check_id, case.source_entity_type, case.source_entity_id)
        observation = untracked_items_adapter.evaluate(session, org_id, case.source_entity_id)
        if observation.state != untracked_items_adapter.STATE_CLEARED:
            raise CaseError(
                409,
                "source_not_cleared",
                "source is not confirmed cleared",
                extra={"source_state": observation.state},
            )

    from_status = case.status
    case.status = target_status
    case.version += 1
    new_version = case.version

    event_type = (
        "operational_case.dismissed"
        if target_status == CaseStatus.DISMISSED
        else _TRANSITION_EVENTS[(from_status, target_status)]
    )

    evidence_refs = validated.get("evidence_refs") or []
    for ref in evidence_refs:
        OperationalCaseLinkRepository(session).add(
            org_id=org_id,
            case_id=case.id,
            relation=CaseLinkRelation.EVIDENCE,
            entity_type=ref["entity_type"],
            entity_id=UUID(ref["entity_id"]),
            created_by=actor.id,
        )

    event_payload = {"from_status": from_status, "to_status": target_status, **validated}
    entity_event = EventWriter(session, org_id).emit(
        event_type=event_type,
        entity_type="operational_case",
        entity_id=case.id,
        payload={"case_id": str(case.id), "version": new_version, "status": target_status, **event_payload},
        actor_id=actor.id,
    )
    OperationalCaseEventRepository(session).add(
        org_id=org_id,
        case_id=case.id,
        case_version=new_version,
        event_type=event_type,
        actor_id=actor.id,
        actor_label=actor.email,
        payload=event_payload,
        entity_event_id=entity_event.id,
    )
    session.flush()
    return {"case": serialize_case_compact(case)}, 200


def apply_transition(
    session: Session,
    org_id: UUID,
    actor: User,
    case_id: UUID,
    target_status: str,
    fields: dict,
    expected_version: int,
    idempotency_key: str,
) -> tuple[dict, int]:
    case = OperationalCaseRepository(session).get_by_id(case_id, org_id)
    if case is None:
        raise CaseError(404, "case_not_found", "case not found")
    route = f"/api/core/cases/{case_id}/transitions"
    payload_for_hash = {"target_status": target_status, "fields": fields, "expected_version": expected_version}
    return run_idempotent_command(
        session,
        org_id,
        actor.id,
        "POST",
        route,
        idempotency_key,
        payload_for_hash,
        command_fn=lambda: _apply_transition(
            session, org_id, _lock_case(session, org_id, case_id), target_status, actor, fields, expected_version
        ),
    )


# ---------------------------------------------------------------------------
# Refresh source (explicit observation, no lifecycle transition)
# ---------------------------------------------------------------------------


def _apply_refresh_source(
    session: Session, org_id: UUID, case: OperationalCase, actor: User, expected_version: int
) -> tuple[dict, int]:
    if case.version != expected_version:
        raise CaseError(
            409,
            "stale_version",
            "expected_version does not match the current case version",
            extra={"current_version": case.version, "case": serialize_case_compact(case)},
        )

    if case.status not in CaseStatus.ACTIVE:
        raise CaseError(409, "case_terminal", "terminal case")
    _validate_owner(session, org_id, case.owner_id)
    _source_lock(session, org_id, case.source_type, case.check_id, case.source_entity_type, case.source_entity_id)
    observation = untracked_items_adapter.evaluate(session, org_id, case.source_entity_id)
    last = _latest_source_observation(session, org_id, case)

    if observation.state == last.get("state"):
        return (
            {
                "case": serialize_case_compact(case),
                "source_state": observation.state,
                "observed_at": observation.observed_at.isoformat(),
                "changed": False,
            },
            200,
        )

    case.version += 1
    new_version = case.version
    payload = {"source_state": observation.state, "observed_at": observation.observed_at.isoformat()}
    entity_event = EventWriter(session, org_id).emit(
        event_type="operational_case.source_observed",
        entity_type="operational_case",
        entity_id=case.id,
        payload={"case_id": str(case.id), "version": new_version, **payload},
        actor_id=actor.id,
    )
    OperationalCaseEventRepository(session).add(
        org_id=org_id,
        case_id=case.id,
        case_version=new_version,
        event_type="operational_case.source_observed",
        actor_id=actor.id,
        actor_label=actor.email,
        payload=payload,
        entity_event_id=entity_event.id,
    )
    session.flush()
    return (
        {
            "case": serialize_case_compact(case),
            "source_state": observation.state,
            "observed_at": observation.observed_at.isoformat(),
            "changed": True,
        },
        200,
    )


def apply_refresh_source(
    session: Session, org_id: UUID, actor: User, case_id: UUID, expected_version: int, idempotency_key: str
) -> tuple[dict, int]:
    case = OperationalCaseRepository(session).get_by_id(case_id, org_id)
    if case is None:
        raise CaseError(404, "case_not_found", "case not found")
    route = f"/api/core/cases/{case_id}/refresh-source"
    payload_for_hash = {"expected_version": expected_version}
    return run_idempotent_command(
        session,
        org_id,
        actor.id,
        "POST",
        route,
        idempotency_key,
        payload_for_hash,
        command_fn=lambda: _apply_refresh_source(
            session, org_id, _lock_case(session, org_id, case_id), actor, expected_version
        ),
    )


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------


def get_case_detail(session: Session, org_id: UUID, actor: User, case_id: UUID) -> dict:
    case = OperationalCaseRepository(session).get_by_id(case_id, org_id)
    if case is None:
        raise CaseError(404, "case_not_found", "case not found")
    body = serialize_case_compact(case)
    body["source_snapshot"] = case.source_snapshot
    body["source_observation"] = _latest_source_observation(session, org_id, case)
    body["permitted_actions"] = _permitted_actions(session, org_id, case, actor)
    body["next_action"] = case.next_action
    return body


def get_case_history(session: Session, org_id: UUID, case_id: UUID) -> dict:
    """Read-only detail shell for same-org ADMIN when the capability is disabled for the
    org -- no actions/source refresh, per the API contract table."""
    case = OperationalCaseRepository(session).get_by_id(case_id, org_id)
    if case is None:
        raise CaseError(404, "case_not_found", "case not found")
    body = serialize_case_compact(case)
    body["source_snapshot"] = case.source_snapshot
    return body


def list_case_events(session: Session, org_id: UUID, case_id: UUID, before_version: int | None, limit: int) -> dict:
    case = OperationalCaseRepository(session).get_by_id(case_id, org_id)
    if case is None:
        raise CaseError(404, "case_not_found", "case not found")
    limit = max(1, min(int(limit or 25), 100))
    rows, has_more = OperationalCaseEventRepository(session).list_for_case(org_id, case_id, before_version, limit)
    next_cursor = rows[-1].case_version if (has_more and rows) else None
    return {"events": [_serialize_event(r) for r in rows], "has_more": has_more, "next_cursor": next_cursor}


def list_cases(
    session: Session,
    org_id: UUID,
    actor: User,
    *,
    owner: str | None,
    severity: str | None,
    statuses: tuple[str, ...] | None,
    source_entity_id: UUID | None,
    overdue_only: bool,
    cursor_token: str | None,
    limit: int,
) -> dict:
    limit = max(1, min(int(limit or 25), 100))
    resolved_owner = str(actor.id) if owner == "me" else owner
    signature = filters_signature(
        owner=resolved_owner,
        severity=severity,
        statuses=list(statuses) if statuses else None,
        source_entity_id=str(source_entity_id) if source_entity_id else None,
        overdue_only=overdue_only,
    )
    cursor = decode_cursor(cursor_token, org_id, signature) if cursor_token else None
    if cursor_token and cursor is None:
        raise CaseError(400, "invalid_cursor", "invalid cursor")
    rows, has_more = OperationalCaseRepository(session).list_for_org(
        org_id,
        owner=resolved_owner,
        severity=severity,
        statuses=statuses,
        source_entity_id=source_entity_id,
        overdue_only=overdue_only,
        now=datetime.now(UTC),
        cursor=cursor,
        limit=limit,
    )
    next_cursor = None
    if has_more and rows:
        last = rows[-1]
        next_cursor = encode_cursor(org_id, signature, last.updated_at, last.id)
    return {"cases": [serialize_case_compact(r) for r in rows], "has_more": has_more, "next_cursor": next_cursor}


def source_status_batch(session: Session, org_id: UUID, source_entity_ids: list[UUID]) -> dict:
    if len(source_entity_ids) > 100:
        raise CaseError(400, "too_many_ids", "at most 100 source identities per request")
    if not source_entity_ids:
        return {"cases": {}}

    from app.core.db.models.inventory_item import InventoryItem

    found_ids = {
        row[0]
        for row in session.query(InventoryItem.id)
        .filter(InventoryItem.id.in_(source_entity_ids), InventoryItem.org_id == org_id)
        .all()
    }
    if any(sid not in found_ids for sid in source_entity_ids):
        raise CaseError(404, "source_not_found", "one or more source identities not found in this organisation")

    best = OperationalCaseRepository(session).source_status_batch(org_id, source_entity_ids)
    result: dict[str, Any] = {}
    for sid in source_entity_ids:
        case = best.get(sid)
        if case is None:
            result[str(sid)] = None
        else:
            result[str(sid)] = {
                "case_id": str(case.id),
                "status": case.status,
                "is_active": case.status in CaseStatus.ACTIVE,
                "is_terminal": case.status in CaseStatus.TERMINAL,
                "owner_id": str(case.owner_id),
                "due_at": case.due_at.isoformat(),
                "severity": case.severity,
                "href": f"/core/cases/{case.id}",
            }
    return {"cases": result}


def dashboard_summary(session: Session, org_id: UUID) -> dict:
    disabled_body = {
        "availability": "not_enabled",
        "as_of": None,
        "active_count": None,
        "critical_count": None,
        "overdue_count": None,
        "needs_owner_count": None,
        "awaiting_verification_count": None,
        "href": "/core/cases",
    }
    if not config.operational_cases_enabled:
        return disabled_body
    if not org_has_feature(session, org_id, OPERATIONAL_CASES_FEATURE_KEY):
        return disabled_body

    try:
        now = datetime.now(UTC)
        aggregates = OperationalCaseRepository(session).count_aggregates(org_id, now)
        return {
            "availability": "ok",
            "as_of": now.isoformat(),
            "active_count": aggregates["active_count"],
            "critical_count": aggregates["critical_count"],
            "overdue_count": aggregates["overdue_count"],
            "needs_owner_count": aggregates["needs_owner_count"],
            "awaiting_verification_count": aggregates["awaiting_verification_count"],
            "href": "/core/cases",
        }
    except Exception:
        logger.exception("operational_cases dashboard summary failed for org_id=%s", org_id)
        return {
            "availability": "unavailable",
            "as_of": None,
            "active_count": None,
            "critical_count": None,
            "overdue_count": None,
            "needs_owner_count": None,
            "awaiting_verification_count": None,
            "href": "/core/cases",
        }
