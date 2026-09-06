"""JSON API routes for operational_cases (A1). Thin: parsing + auth/role checks only,
business logic lives in operational_case_service.
"""

from __future__ import annotations

from uuid import UUID

from flask import Blueprint, g, jsonify, request

from app.core.db import db_session
from app.core.db.models.user import UserRole
from app.core.security.permissions import requires_auth, requires_role
from app.features.operational_cases.services import operational_case_service as svc
from app.features.operational_cases.services.operational_case_service import CaseError
from app.observability import get_logger

logger = get_logger(__name__)

api_bp = Blueprint("operational_cases_api", __name__)


@api_bp.errorhandler(CaseError)
def handle_case_error(exc):
    return _error_response(exc)


@api_bp.before_request
def validate_command_shape():
    if request.method not in {"POST", "PATCH"}:
        return
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise CaseError(400, "invalid_json", "JSON object required")
    if request.path.endswith("/from-finding"):
        allowed = {"source_entity_id", "owner_id", "due_at", "next_action", "previous_case_id", "recurrence_reason"}
    elif request.path.endswith("/source-status"):
        allowed = {"source_entity_ids"}
    elif request.path.endswith("/refresh-source"):
        allowed = {"expected_version"}
    elif request.path.endswith("/transitions"):
        allowed = {
            "target_status",
            "status",
            "expected_version",
            "cause",
            "cause_detail",
            "action_taken",
            "outcome",
            "evidence_refs",
            "verification_note",
            "reason",
            "reopen_reason",
        }
        if "target_status" in data and not isinstance(data["target_status"], str):
            raise CaseError(400, "target_status_invalid", "target_status must be text")
        if "status" in data and not isinstance(data["status"], str):
            raise CaseError(400, "target_status_invalid", "status must be text")
    else:
        allowed = {"owner_id", "due_at", "next_action", "expected_version"}
    if set(data) - allowed:
        raise CaseError(400, "unsupported_fields", "unsupported fields")
    if "expected_version" in data and (type(data["expected_version"]) is not int or data["expected_version"] < 1):
        raise CaseError(400, "expected_version_invalid", "expected_version must be a positive integer")


_STATUS_FILTER_PRESETS = {
    "active": None,  # None -> repository default (CaseStatus.ACTIVE)
    "needs_owner": None,
    "overdue": None,
    "awaiting_verification": ("resolved",),
    "all": ("open", "acknowledged", "in_progress", "resolved", "verified", "dismissed"),
}


def _org_id() -> UUID:
    return g.current_org_id


def _error_response(exc: CaseError):
    db_session().rollback()
    if exc.status in {403, 404}:
        logger.warning(
            "operational_case_access_denied", org_id=str(getattr(g, "current_org_id", "")), error_code=exc.code
        )
    body = {"error": exc.message, "error_code": exc.code, **exc.extra}
    return jsonify(body), exc.status


def _parse_uuid(raw: str, field: str) -> UUID:
    try:
        return UUID(raw)
    except (ValueError, TypeError, AttributeError):
        raise CaseError(400, f"{field}_invalid", f"{field} must be a UUID") from None


def _idempotency_key_header() -> str:
    key = request.headers.get("Idempotency-Key") or (request.get_json(silent=True) or {}).get("idempotency_key")
    if not key:
        raise CaseError(400, "idempotency_key_required", "Idempotency-Key header is required")
    return str(key)


@api_bp.route("/api/core/cases", methods=["GET"])
@requires_auth
def list_cases():
    org_id = _org_id()
    args = request.args
    owner = args.get("owner")
    severity = args.get("severity")
    status_filter = args.get("status")
    allowed_args = {"owner", "severity", "status", "overdue", "source_entity_id", "cursor", "limit"}
    if set(args) - allowed_args:
        raise CaseError(400, "invalid_filter", "unknown filter")
    if status_filter and status_filter not in _STATUS_FILTER_PRESETS and status_filter not in svc.CaseStatus.ALL:
        raise CaseError(400, "invalid_filter", "unknown status")
    if severity and severity != "critical":
        raise CaseError(400, "invalid_filter", "unknown severity")
    if owner and owner not in {"me", "needs_owner"}:
        _parse_uuid(owner, "owner")
    if "overdue" in args and args["overdue"] not in {"true", "false"}:
        raise CaseError(400, "invalid_filter", "overdue must be true or false")
    overdue_only = status_filter == "overdue" or args.get("overdue") == "true"
    statuses = (
        (status_filter,)
        if status_filter in svc.CaseStatus.ALL
        else (_STATUS_FILTER_PRESETS.get(status_filter) if status_filter else None)
    )
    source_entity_id_raw = args.get("source_entity_id")
    source_entity_id = _parse_uuid(source_entity_id_raw, "source_entity_id") if source_entity_id_raw else None
    if owner == "needs_owner":
        owner_filter = "needs_owner"
    else:
        owner_filter = owner

    try:
        limit = int(args.get("limit", 25))
    except ValueError:
        return jsonify({"error": "limit must be an integer", "error_code": "limit_invalid"}), 400

    if not 1 <= limit <= 100:
        raise CaseError(400, "limit_invalid", "limit must be 1-100")
    try:
        result = svc.list_cases(
            db_session(),
            org_id,
            g.current_user,
            owner=owner_filter,
            severity=severity,
            statuses=statuses,
            source_entity_id=source_entity_id,
            overdue_only=overdue_only,
            cursor_token=args.get("cursor"),
            limit=limit,
        )
    except CaseError as exc:
        return _error_response(exc)
    return jsonify(result), 200


@api_bp.route("/api/core/cases/from-finding", methods=["POST"])
@requires_auth
def create_from_finding():
    org_id = _org_id()
    data = request.get_json(silent=True) or {}
    try:
        idem_key = _idempotency_key_header()
        source_entity_id_raw = data.get("source_entity_id")
        if not source_entity_id_raw:
            raise CaseError(400, "source_entity_id_required", "source_entity_id is required")
        source_entity_id = _parse_uuid(source_entity_id_raw, "source_entity_id")
        owner_id_raw = data.get("owner_id")
        if not owner_id_raw:
            raise CaseError(400, "owner_id_required", "owner_id is required")
        owner_id = _parse_uuid(owner_id_raw, "owner_id")
        previous_case_id = None
        if data.get("previous_case_id"):
            previous_case_id = _parse_uuid(data["previous_case_id"], "previous_case_id")

        params = {
            "source_entity_id": source_entity_id,
            "owner_id": owner_id,
            "due_at": data.get("due_at"),
            "next_action": data.get("next_action"),
            "previous_case_id": previous_case_id,
            "recurrence_reason": data.get("recurrence_reason"),
        }
        body, status = svc.create_case_from_finding(db_session(), org_id, g.current_user, params, idem_key)
    except CaseError as exc:
        return _error_response(exc)
    return jsonify(body), status


@api_bp.route("/api/core/cases/<case_id>", methods=["GET"])
@requires_auth
def get_case(case_id: str):
    org_id = _org_id()
    try:
        cid = _parse_uuid(case_id, "case_id")
        body = svc.get_case_detail(db_session(), org_id, g.current_user, cid)
    except CaseError as exc:
        return _error_response(exc)
    return jsonify(body), 200


@api_bp.route("/api/core/cases/<case_id>", methods=["PATCH"])
@requires_auth
def patch_case(case_id: str):
    org_id = _org_id()
    data = request.get_json(silent=True) or {}
    try:
        cid = _parse_uuid(case_id, "case_id")
        idem_key = _idempotency_key_header()
        expected_version = data.get("expected_version")
        if not isinstance(expected_version, int):
            raise CaseError(400, "expected_version_required", "expected_version (integer) is required")
        # Pass every field through except command metadata -- the service itself must
        # reject an unsupported field (spec: "unsupported fields ... write nothing"), so
        # pre-filtering here would silently swallow the field instead of rejecting it.
        fields = {k: v for k, v in data.items() if k not in {"expected_version", "idempotency_key"}}
        body, status = svc.apply_patch(db_session(), org_id, g.current_user, cid, fields, expected_version, idem_key)
    except CaseError as exc:
        return _error_response(exc)
    return jsonify(body), status


@api_bp.route("/api/core/cases/<case_id>/transitions", methods=["POST"])
@requires_auth
def transition_case(case_id: str):
    org_id = _org_id()
    data = request.get_json(silent=True) or {}
    try:
        cid = _parse_uuid(case_id, "case_id")
        idem_key = _idempotency_key_header()
        target_status = data.get("target_status") or data.get("status")
        if not target_status:
            raise CaseError(400, "target_status_required", "target_status is required")
        expected_version = data.get("expected_version")
        if not isinstance(expected_version, int):
            raise CaseError(400, "expected_version_required", "expected_version (integer) is required")
        fields = {
            k: v for k, v in data.items() if k not in {"target_status", "status", "expected_version", "idempotency_key"}
        }
        body, status = svc.apply_transition(
            db_session(), org_id, g.current_user, cid, target_status, fields, expected_version, idem_key
        )
    except CaseError as exc:
        return _error_response(exc)
    return jsonify(body), status


@api_bp.route("/api/core/cases/<case_id>/refresh-source", methods=["POST"])
@requires_auth
def refresh_source(case_id: str):
    org_id = _org_id()
    data = request.get_json(silent=True) or {}
    try:
        cid = _parse_uuid(case_id, "case_id")
        idem_key = _idempotency_key_header()
        expected_version = data.get("expected_version")
        if not isinstance(expected_version, int):
            raise CaseError(400, "expected_version_required", "expected_version (integer) is required")
        body, status = svc.apply_refresh_source(db_session(), org_id, g.current_user, cid, expected_version, idem_key)
    except CaseError as exc:
        return _error_response(exc)
    return jsonify(body), status


@api_bp.route("/api/core/cases/<case_id>/events", methods=["GET"])
@requires_auth
def list_case_events(case_id: str):
    org_id = _org_id()
    try:
        cid = _parse_uuid(case_id, "case_id")
        before_version_raw = request.args.get("before_version")
        before_version = int(before_version_raw) if before_version_raw else None
        limit = int(request.args.get("limit", 25))
        body = svc.list_case_events(db_session(), org_id, cid, before_version, limit)
    except CaseError as exc:
        return _error_response(exc)
    except ValueError:
        return jsonify({"error": "before_version/limit must be integers", "error_code": "invalid_pagination"}), 400
    return jsonify(body), 200


@api_bp.route("/api/core/cases/history/<case_id>", methods=["GET"])
@requires_auth
@requires_role(UserRole.ADMIN)
def get_case_history(case_id: str):
    """Read-only detail shell, reachable even when the org's subscription is off (see
    operational_cases_bp's before_request gate, which explicitly bypasses this path)."""
    org_id = _org_id()
    try:
        cid = _parse_uuid(case_id, "case_id")
        body = svc.get_case_history(db_session(), org_id, cid)
    except CaseError as exc:
        return _error_response(exc)
    return jsonify(body), 200


@api_bp.route("/api/core/cases/history/<case_id>/events", methods=["GET"])
@requires_auth
@requires_role(UserRole.ADMIN)
def get_case_history_events(case_id: str):
    org_id = _org_id()
    try:
        cid = _parse_uuid(case_id, "case_id")
        before_version_raw = request.args.get("before_version")
        before_version = int(before_version_raw) if before_version_raw else None
        limit = int(request.args.get("limit", 25))
        body = svc.list_case_events(db_session(), org_id, cid, before_version, limit)
    except CaseError as exc:
        return _error_response(exc)
    except ValueError:
        return jsonify({"error": "before_version/limit must be integers", "error_code": "invalid_pagination"}), 400
    return jsonify(body), 200


@api_bp.route("/api/core/cases/source-status", methods=["POST"])
@requires_auth
def source_status_batch():
    org_id = _org_id()
    data = request.get_json(silent=True) or {}
    raw_ids = data.get("source_entity_ids")
    if not isinstance(raw_ids, list) or not raw_ids:
        return jsonify(
            {"error": "source_entity_ids (non-empty array) is required", "error_code": "source_entity_ids_required"}
        ), 400
    try:
        ids = [_parse_uuid(str(x), "source_entity_ids") for x in raw_ids]
        body = svc.source_status_batch(db_session(), org_id, ids)
    except CaseError as exc:
        return _error_response(exc)
    return jsonify(body), 200
