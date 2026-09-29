"""Tenant-scoped JSON and audit-pack routes for Compliant."""

import calendar
import csv
from datetime import date
from decimal import Decimal, InvalidOperation
from io import StringIO
from uuid import UUID

from flask import Blueprint, Response, g, jsonify, render_template, request
from sqlalchemy.exc import IntegrityError

from app.core.backend.evidence.evidence_service import get_evidence_for_download
from app.core.db import db_session
from app.core.db.models.execution_evidence import EVIDENCE_STATUS_ACTIVE, ExecutionEvidence
from app.core.db.models.user import User, UserRole
from app.core.security.permissions import requires_auth, requires_role
from app.core.utils.log_action import log_action
from app.features.compliant.models import ComplianceReport
from app.features.compliant.modules.nz_alcohol.catalogue import capture_requirements, framework_by_slug
from app.features.compliant.modules.nz_alcohol.national_programmes import GUIDANCE
from app.features.compliant.modules.nz_alcohol.np3_audit import evidence_playbook, np3_log_template
from app.features.compliant.modules.nz_alcohol.workflow_rules import (
    ABV_RULES_SETTING,
    matching_abv_rule,
    terminal_steps,
    validate_abv_rules,
    validate_workflow_settings,
)
from app.features.compliant.np3_evidence_pdf import build_np3_evidence_register_pdf
from app.features.compliant.platform.workflow_rules import workflow_context
from app.features.compliant.service import ComplianceService, serialise_record
from app.observability import get_logger

logger = get_logger(__name__)

api_bp = Blueprint("compliant_api", __name__)

# Excise and stocktake settings live on their own pages, which the main configuration form doesn't
# send, so a save of that form keeps them. (ABV rules are carried by configuration.js
# instead, because the Whistlebird replay relies on a PUT replacing them wholesale.)
_SUBFEATURE_SETTINGS = (
    "excise_frequency",
    "excise_tracking_from",
    "stocktake_frequency",
    "stocktake_bulk_tolerance_percent",
    "np_registered_on",
    "np_registered_as",
)
_RECORD_TYPES = {"attestation", "reading", "lodgement", "competency", "incident"}
_RECORD_STATUSES = {"complete", "failed", "open", "superseded"}
_CSV_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")
_FOOD_CONTROL_PROGRAMMES = {"np1", "np2", "np3", "none"}
_LIQUOR_LICENCE_TYPES = {"on", "off", "club", "special"}
_NP3_REVIEW_INTERVALS = {1, 3, 6, 12}


def _csv_safe(value):
    """Neutralise formula/DDE injection in a CSV cell.

    ``title``/``evidence_reference`` are free text a caller controls (validated only for
    length, not content) that ends up opened by an auditor in Excel/Sheets/LibreOffice. A
    cell whose text begins with a formula-trigger character is prefixed with a leading
    apostrophe so spreadsheet software renders it as text instead of evaluating it.
    """
    text = "" if value is None else str(value)
    if text.startswith(_CSV_FORMULA_PREFIXES):
        return "'" + text
    return text


_NP_PROGRAMMES = ("np1", "np2", "np3")


def _np_programme() -> str:
    """The org's national programme; the verification workspace serves NP1, NP2 and NP3 (plan 2.4b)."""
    profile = _service().get_profile(_org_id())
    programme = ((profile.settings or {}) if profile else {}).get("food_control_programme", "np3")
    return programme if programme in _NP_PROGRAMMES else "np3"


def _service() -> ComplianceService:
    return ComplianceService(db_session())


def _org_id() -> UUID:
    return UUID(g.org_id)


def _date(value, field: str):
    if value in (None, ""):
        return None
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError):
        raise ValueError(f"{field} must be YYYY-MM-DD") from None


def _add_months(value: date, months: int) -> date:
    """Keep recurring reviews on a calendar cadence, including month ends."""
    month_index = value.month - 1 + months
    year, month = value.year + month_index // 12, month_index % 12 + 1
    return date(year, month, min(value.day, calendar.monthrange(year, month)[1]))


def _decimal(value, field: str) -> str | None:
    if value in (None, ""):
        return None
    try:
        return str(Decimal(str(value)))
    except InvalidOperation:
        raise ValueError(f"{field} must be numeric") from None


@api_bp.route("/api/compliant/overview", methods=["GET"])
@requires_auth
def overview():
    return jsonify(_service().overview(_org_id())), 200


@api_bp.route("/api/compliant/core-sources", methods=["GET"])
@requires_auth
def core_sources():
    """Search selectable Core proof without exposing another tenant's records."""
    kind = request.args.get("kind", "")
    query = request.args.get("q", "").strip()
    try:
        offset = int(request.args.get("offset", "0"))
    except ValueError:
        return jsonify({"error": "Invalid offset"}), 400
    if kind not in {"file", "execution-step", "execution", "movement"} or len(query) > 100 or not 0 <= offset <= 10000:
        return jsonify({"error": "Invalid search parameters"}), 400
    return jsonify(_service().search_core_sources(_org_id(), kind, query, offset)), 200


@api_bp.route("/api/compliant/np3-audit", methods=["GET"])
@requires_auth
def np3_audit():
    try:
        audit = _service().np3_audit(_org_id())
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 409
    export_format = request.args.get("format")
    if export_format not in {"csv", "pdf"}:
        return jsonify(audit), 200

    if export_format == "pdf":
        uploaded_evidence = []
        evidence_rows = (
            db_session.query(ExecutionEvidence)
            .filter(
                ExecutionEvidence.org_id == _org_id(),
                ExecutionEvidence.evidence_status == EVIDENCE_STATUS_ACTIVE,
            )
            .order_by(ExecutionEvidence.created_at.asc(), ExecutionEvidence.id.asc())
            .all()
        )
        for evidence in evidence_rows:
            content, mime_type, file_name, error = get_evidence_for_download(evidence.id, _org_id())
            uploaded_evidence.append(
                {
                    "file_name": file_name or evidence.file_name,
                    "mime_type": mime_type or evidence.mime_type,
                    "checksum_sha256": evidence.checksum_sha256,
                    "content": content,
                    "error": error,
                }
            )
        return Response(
            build_np3_evidence_register_pdf(audit, uploaded_evidence),
            mimetype="application/pdf",
            headers={"Content-Disposition": "attachment; filename=np3-verification-evidence.pdf"},
        )

    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(
        [
            "Category",
            "Verification topic",
            "Status",
            "Evidence records",
            "Evidence references",
            "Production record IDs",
            "Last recorded",
        ]
    )
    for row in audit["rows"]:
        writer.writerow(
            [
                _csv_safe(row["category"]),
                _csv_safe(row["topic"]),
                _csv_safe(row["state"]),
                _csv_safe("; ".join(row["evidence_titles"])),
                _csv_safe("; ".join(row["evidence_references"])),
                _csv_safe("; ".join(ref for item in row["derived_evidence"] for ref in item["source_refs"])),
                _csv_safe(row["latest_recorded_at"] or ""),
            ]
        )
    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=np3-verification-evidence.csv"},
    )


@api_bp.route("/api/compliant/np3-audit/checks/<control_id>", methods=["GET"])
@requires_auth
def np3_audit_check(control_id: str):
    """Return the one check a user chose to inspect in full."""
    try:
        audit = _service().np3_audit(_org_id())
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 409
    row = next((item for item in audit["rows"] if item["control_id"] == control_id), None)
    if row is None:
        return jsonify({"error": "Unknown NP3 check"}), 404
    return jsonify({"check": row, "verification": audit["verification"], "available_staff": audit["staff"]}), 200


@api_bp.route("/api/compliant/np3-audit/checks/<control_id>/settings", methods=["PUT"])
@requires_auth
@requires_role(UserRole.ADMIN)
def update_np3_check_settings(control_id: str):
    if control_id not in dict((framework_by_slug(f"{_np_programme()}-food-control") or {}).get("controls", ())):
        return jsonify({"error": "Unknown NP3 check"}), 404
    data = request.get_json(silent=True)
    if not isinstance(data, dict) or data.get("review_interval_months") not in _NP3_REVIEW_INTERVALS:
        return jsonify({"error": "review_interval_months must be 1, 3, 6, or 12"}), 400
    profile = _service().get_profile(_org_id())
    if profile is None or not profile.enabled:
        return jsonify({"error": "Configure Compliance before changing NP3 check settings"}), 409
    settings = dict(profile.settings or {})
    intervals = dict(settings.get("np3_check_review_intervals") or {})
    intervals[control_id] = data["review_interval_months"]
    settings["np3_check_review_intervals"] = intervals
    profile = _service().upsert_profile(_org_id(), {"settings": settings})
    log_action("update", "compliance_profile", profile.id, {"np3_check_review_interval": control_id})
    return jsonify({"review_interval_months": intervals[control_id]}), 200


@api_bp.route("/api/compliant/np3-audit/attestations", methods=["POST"])
@requires_auth
def attest_np3_check():
    """Append a focused NP3 self-review without exposing the generic record register."""
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "JSON object required"}), 400
    control_id = str(data.get("control_id") or "")
    framework = framework_by_slug(f"{_np_programme()}-food-control") or {}
    controls = dict(framework.get("controls", ()))
    if control_id not in controls:
        return jsonify({"error": "Unknown NP3 check"}), 400
    how_we_meet = str(data.get("how_we_meet") or "").strip()
    if not how_we_meet or len(how_we_meet) > 4000:
        return jsonify({"error": "How we meet this requirement is required and must be at most 4000 characters"}), 400
    if data.get("confirmed") is not True:
        return jsonify({"error": "Confirm that you reviewed this check before signing it off"}), 400
    try:
        review_interval_months = int(data.get("review_interval_months", 6))
    except (TypeError, ValueError):
        return jsonify({"error": "review_interval_months must be 1, 3, 6, or 12"}), 400
    if review_interval_months not in _NP3_REVIEW_INTERVALS:
        return jsonify({"error": "review_interval_months must be 1, 3, 6, or 12"}), 400
    evidence_reference = str(data.get("evidence_reference") or "").strip() or None
    if evidence_reference and len(evidence_reference) > 1024:
        return jsonify({"error": "evidence_reference must be at most 1024 characters"}), 400
    source_refs = data.get("source_refs") or []
    if (
        not isinstance(source_refs, list)
        or len(source_refs) > 30
        or not all(isinstance(item, str) for item in source_refs)
    ):
        return jsonify({"error": "source_refs must be a list of at most 30 strings"}), 400
    profile = _service().get_profile(_org_id())
    if profile is None or not profile.enabled:
        return jsonify({"error": "Configure Compliance before signing off checks"}), 409
    if (profile.settings or {}).get("food_control_programme", "np3") not in _NP_PROGRAMMES:
        return jsonify({"error": "Select a national programme in Configuration before signing off checks"}), 409
    invalid_source_refs = _service().invalid_core_source_references(_org_id(), source_refs)
    if invalid_source_refs:
        logger.warning("access_denied", reason="source_ref_not_in_org", feature="compliant", org_id=str(_org_id()))
        return jsonify({"error": "Each Production record reference must be a record in this organisation"}), 400
    evidence_fields = data.get("evidence_fields") or {}
    allowed_evidence_fields = {field["key"] for field in evidence_playbook(control_id)["fields"]}
    if (
        not isinstance(evidence_fields, dict)
        or not set(evidence_fields).issubset(allowed_evidence_fields)
        or not all(isinstance(value, str) and len(value) <= 1024 for value in evidence_fields.values())
    ):
        return jsonify({"error": "Evidence fields do not match this NP3 check"}), 400
    today = date.today()
    record = _service().add_record(
        _org_id(),
        g.current_user.id,
        {
            "framework_slug": framework["slug"],
            "control_id": control_id,
            "record_type": "attestation",
            "status": "complete",
            "title": f"{GUIDANCE[_np_programme()]['short']} review: {controls[control_id]}",
            "due_date": _add_months(today, review_interval_months),
            "evidence_reference": evidence_reference,
            "source_refs": source_refs,
            "details": {
                "how_we_meet": how_we_meet,
                "review_interval_months": review_interval_months,
                "np3_guidance_version": framework.get("version"),
                "attestation_confirmed": True,
                "evidence_fields": evidence_fields,
            },
        },
    )
    log_action("create", "compliance_record", record.id, {"framework": framework["slug"], "control": control_id})
    return jsonify({"record": serialise_record(record)}), 201


@api_bp.route("/api/compliant/np3-audit/checks/<control_id>/logs", methods=["POST"])
@requires_auth
def add_np3_check_log(control_id: str):
    """Append a control-specific operational log entry from the check workspace."""
    template = np3_log_template(control_id)
    framework = framework_by_slug(f"{_np_programme()}-food-control") or {}
    controls = dict(framework.get("controls", ()))
    if control_id not in controls or template is None:
        return jsonify({"error": "This NP3 check does not have a built-in log"}), 404
    data = request.get_json(silent=True)
    fields = data.get("fields") if isinstance(data, dict) else None
    if not isinstance(fields, dict):
        return jsonify({"error": "fields must be an object"}), 400
    template_fields = {field["key"]: field for field in template["fields"]}
    if not set(fields).issubset(template_fields):
        return jsonify({"error": "Log fields do not match this NP3 check"}), 400
    normalised: dict[str, str] = {}
    for key, definition in template_fields.items():
        raw_value = fields.get(key, "")
        if raw_value is None:
            raw_value = ""
        if not isinstance(raw_value, str) or len(raw_value.strip()) > 4000:
            return jsonify({"error": f"{definition['label']} must be text of at most 4000 characters"}), 400
        value = raw_value.strip()
        if definition.get("required") and not value:
            return jsonify({"error": f"{definition['label']} is required"}), 400
        if definition.get("type") == "date" and value:
            try:
                date.fromisoformat(value)
            except ValueError:
                return jsonify({"error": f"{definition['label']} must be YYYY-MM-DD"}), 400
        if definition.get("type") == "select" and value:
            allowed = {option[0] for option in definition.get("options", ())}
            if value not in allowed:
                return jsonify({"error": f"{definition['label']} has an invalid option"}), 400
        if value:
            normalised[key] = value
    employee_id = normalised.get("employee_user_id")
    owner_user_id = None
    if employee_id:
        try:
            owner_user_id = UUID(employee_id)
        except ValueError:
            return jsonify({"error": "Employee must be a user in this organisation"}), 400
        employee = (
            db_session()
            .query(User)
            .filter(User.id == owner_user_id, User.org_id == _org_id(), User.is_active.is_(True))
            .one_or_none()
        )
        if employee is None:
            return jsonify({"error": "Employee must be an active user in this organisation"}), 400
    profile = _service().get_profile(_org_id())
    if (
        profile is None
        or not profile.enabled
        or (profile.settings or {}).get("food_control_programme", "np3") not in _NP_PROGRAMMES
    ):
        return jsonify({"error": "Configure a national programme before adding a log entry"}), 409
    status = "open" if normalised.get("result") == "action-required" else "complete"
    if status == "open" and not (normalised.get("corrective_action") or normalised.get("cause_and_action")):
        return jsonify({"error": "Describe the corrective action when follow-up is required"}), 400
    event_date = _date(normalised.get("event_date"), "event_date") or date.today()
    record = _service().add_record(
        _org_id(),
        g.current_user.id,
        {
            "framework_slug": framework["slug"],
            "control_id": control_id,
            "record_type": template["record_type"],
            "status": status,
            "title": f"{GUIDANCE[_np_programme()]['short']} log: {template['title']}",
            "period_start": event_date,
            "due_date": _add_months(event_date, 1) if status == "open" else None,
            "owner_user_id": owner_user_id,
            "details": {
                "np3_log_type": template["key"],
                "log_fields": normalised,
                "np3_guidance_version": framework.get("version"),
            },
        },
    )
    log_action(
        "create",
        "compliance_record",
        record.id,
        {"framework": framework["slug"], "control": control_id, "log": template["key"]},
    )
    return jsonify({"record": serialise_record(record)}), 201


@api_bp.route("/api/compliant/capture-context", methods=["GET"])
@requires_auth
def capture_context():
    """Return module-contributed workflow extensions in Core's generic contract.

    ``?step_id=`` (the step definition being executed) adds any rules that apply only to
    that step; without it, only rules that apply to every step are returned.
    """
    raw_step_id = (request.args.get("step_id") or "").strip()
    step_id = None
    if raw_step_id:
        try:
            step_id = UUID(raw_step_id)
        except ValueError:
            return jsonify({"error": "step_id must be a UUID"}), 400
    return jsonify(workflow_context(db_session(), _org_id(), step_id)), 200


def _abv_rules_payload(org_id: UUID) -> dict:
    """Every workflow's final-step outputs, and which ABV rule (if any) covers each one."""
    profile = _service().get_profile(org_id)
    rules = list(((profile.settings or {}) if profile else {}).get(ABV_RULES_SETTING) or [])
    candidates = []
    for process, step in terminal_steps(db_session(), org_id):
        for output in step.outputs or []:
            name = str((output or {}).get("name") or "").strip() if isinstance(output, dict) else ""
            if not name:
                continue
            rule = matching_abv_rule(name, rules)
            candidates.append(
                {
                    "process_id": str(process.id),
                    "process_name": process.name,
                    "is_draft": bool(process.is_draft),
                    "step_id": str(step.id),
                    "step_name": step.name,
                    "output_name": name,
                    "matched_rule": rule,
                }
            )
    return {"rules": rules, "candidates": candidates, "enabled": bool(profile and profile.enabled)}


@api_bp.route("/api/compliant/nz-alcohol/abv-rules", methods=["GET"])
@requires_auth
def get_abv_rules():
    return jsonify(_abv_rules_payload(_org_id())), 200


@api_bp.route("/api/compliant/nz-alcohol/abv-rules", methods=["PUT"])
@requires_auth
@requires_role(UserRole.ADMIN)
def update_abv_rules():
    """Replace only the ABV product rules; every other profile setting is left untouched."""
    data = request.get_json(silent=True)
    rules = data.get("rules") if isinstance(data, dict) else None
    error = validate_abv_rules(rules)
    if error:
        return jsonify({"error": error}), 400
    profile = _service().get_profile(_org_id())
    if profile is None:
        return jsonify({"error": "Configure Compliance before adding ABV rules"}), 409
    cleaned = [{"pattern": rule["pattern"].strip(), "match_type": rule["match_type"]} for rule in rules]
    _service().upsert_profile(_org_id(), {"settings": {**(profile.settings or {}), ABV_RULES_SETTING: cleaned}})
    log_action("update", "compliance_profile", profile.id, {ABV_RULES_SETTING: len(cleaned)})
    return jsonify(_abv_rules_payload(_org_id())), 200


@api_bp.route("/api/compliant/profile", methods=["PUT"])
@requires_auth
@requires_role(UserRole.ADMIN)
def update_profile():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "JSON object required"}), 400
    if "enabled" in data and not isinstance(data["enabled"], bool):
        return jsonify({"error": "enabled must be boolean"}), 400
    if "settings" in data and not isinstance(data["settings"], dict):
        return jsonify({"error": "settings must be an object"}), 400
    settings = data.get("settings")
    if settings is not None:
        programme = settings.get("food_control_programme")
        if programme is not None and programme not in _FOOD_CONTROL_PROGRAMMES:
            return jsonify({"error": "food_control_programme must be np1, np2, np3, or none"}), 400
        review_interval = settings.get("np3_review_interval_months")
        if review_interval is not None and review_interval not in _NP3_REVIEW_INTERVALS:
            return jsonify({"error": "np3_review_interval_months must be 1, 3, 6, or 12"}), 400
        check_intervals = settings.get("np3_check_review_intervals")
        if check_intervals is not None and (
            not isinstance(check_intervals, dict)
            or not all(
                key in dict((framework_by_slug(f"{_np_programme()}-food-control") or {}).get("controls", ()))
                and value in _NP3_REVIEW_INTERVALS
                for key, value in check_intervals.items()
            )
        ):
            return jsonify({"error": "np3_check_review_intervals must contain valid NP3 checks and intervals"}), 400
        licence_types = settings.get("liquor_licence_types")
        if licence_types is not None and (
            not isinstance(licence_types, list)
            or not all(isinstance(item, str) and item in _LIQUOR_LICENCE_TYPES for item in licence_types)
        ):
            return jsonify({"error": "liquor_licence_types must contain only on, off, club, or special"}), 400
        workflow_settings_error = validate_workflow_settings(settings)
        if workflow_settings_error:
            return jsonify({"error": workflow_settings_error}), 400
    if settings is not None:
        # Settings owned by their own screens (ABV rules, excise) survive a save of the
        # main configuration form, which doesn't send them; they're only changed when a
        # request includes them.
        existing = getattr(_service().get_profile(_org_id()), "settings", None) or {}
        for key in _SUBFEATURE_SETTINGS:
            if key not in settings and key in existing:
                settings[key] = existing[key]
        data = {**data, "settings": settings}
    profile = _service().upsert_profile(_org_id(), data)
    log_action("update", "compliance_profile", profile.id, {"enabled": profile.enabled})
    return jsonify({"profile": _service().overview(_org_id())["profile"]}), 200


@api_bp.route("/api/compliant/alcohol-products", methods=["GET"])
@requires_auth
def list_alcohol_products():
    products = _service().product_profiles(_org_id())
    return jsonify(
        {
            "products": [
                {
                    "id": str(product.id),
                    "inventory_name": product.inventory_name,
                    "product_type": product.product_type,
                    "abv_percent": str(product.abv_percent) if product.abv_percent is not None else None,
                    "pack_volume_ml": str(product.pack_volume_ml) if product.pack_volume_ml is not None else None,
                    "customs_product_code": product.customs_product_code,
                    "is_active": product.is_active,
                }
                for product in products
            ]
        }
    ), 200


@api_bp.route("/api/compliant/alcohol-products", methods=["POST"])
@requires_auth
@requires_role(UserRole.ADMIN)
def create_alcohol_product():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "JSON object required"}), 400
    product_type = str(data.get("product_type") or "")
    if product_type not in {"beer", "spirits", "wine", "cider", "mead", "rtd", "other"}:
        return jsonify({"error": "Invalid alcohol product type"}), 400
    inventory_name = str(data.get("inventory_name") or "").strip()
    if not inventory_name or len(inventory_name) > 255:
        return jsonify({"error": "inventory_name is required and must be at most 255 characters"}), 400
    customs_product_code = str(data.get("customs_product_code") or "").strip() or None
    if customs_product_code and len(customs_product_code) > 100:
        return jsonify({"error": "customs_product_code must be at most 100 characters"}), 400
    try:
        abv_percent = Decimal(_decimal(data.get("abv_percent"), "abv_percent") or "0")
        if not abv_percent.is_finite() or not Decimal("0") < abv_percent <= Decimal("100"):
            return jsonify({"error": "abv_percent must be greater than 0 and at most 100"}), 400
    except (ValueError, InvalidOperation):
        return jsonify({"error": "abv_percent must be a number"}), 400
    try:
        product = _service().add_product_profile(
            _org_id(),
            {
                "inventory_name": inventory_name,
                "product_type": product_type,
                "abv_percent": str(abv_percent),
                "customs_product_code": customs_product_code,
            },
        )
    except IntegrityError as exc:
        db_session().rollback()
        if "uq_compliance_alcohol_product_org_name" in str(exc):
            return jsonify({"error": "A profile already exists for this inventory name"}), 409
        raise
    log_action("create", "compliance_alcohol_product_profile", product.id, {"product_type": product_type})
    return jsonify({"product": {"id": str(product.id), "inventory_name": product.inventory_name}}), 201


@api_bp.route("/api/compliant/records", methods=["GET"])
@requires_auth
def list_records():
    framework_slug = (request.args.get("framework") or "").strip() or None
    if framework_slug and framework_by_slug(framework_slug) is None:
        return jsonify({"error": "Unknown framework"}), 400
    records = _service().records(_org_id(), framework_slug)
    return jsonify({"records": [serialise_record(record) for record in records[:200]]}), 200


@api_bp.route("/api/compliant/records", methods=["POST"])
@requires_auth
def create_record():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "JSON object required"}), 400
    framework_slug = str(data.get("framework_slug") or "")
    framework = framework_by_slug(framework_slug)
    if framework is None:
        return jsonify({"error": "Unknown framework"}), 400
    control_ids = {control_id for control_id, _ in framework["controls"]}
    control_id = str(data.get("control_id") or "")
    if control_id not in control_ids:
        return jsonify({"error": "Unknown control for framework"}), 400
    if data.get("record_type") not in _RECORD_TYPES or data.get("status", "complete") not in _RECORD_STATUSES:
        return jsonify({"error": "Invalid record_type or status"}), 400
    title = str(data.get("title") or "").strip()
    if not title or len(title) > 255:
        return jsonify({"error": "title is required and must be at most 255 characters"}), 400
    source_refs = data.get("source_refs") or []
    if (
        not isinstance(source_refs, list)
        or len(source_refs) > 30
        or not all(isinstance(item, str) for item in source_refs)
    ):
        return jsonify({"error": "source_refs must be a list of at most 30 strings"}), 400
    details = data.get("details") or {}
    if not isinstance(details, dict):
        return jsonify({"error": "details must be an object"}), 400
    if data.get("declared_litres_of_alcohol") not in (None, ""):
        details["declared_litres_of_alcohol"] = data["declared_litres_of_alcohol"]
    if "declared_litres_of_alcohol" in details:
        try:
            _decimal(details["declared_litres_of_alcohol"], "declared_litres_of_alcohol")
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
    evidence_reference = str(data.get("evidence_reference") or "").strip() or None
    if evidence_reference and len(evidence_reference) > 1024:
        return jsonify({"error": "evidence_reference must be at most 1024 characters"}), 400
    try:
        record_data = {
            "framework_slug": framework_slug,
            "control_id": control_id,
            "record_type": data["record_type"],
            "status": data.get("status", "complete"),
            "title": title,
            "period_start": _date(data.get("period_start"), "period_start"),
            "period_end": _date(data.get("period_end"), "period_end"),
            "due_date": _date(data.get("due_date"), "due_date"),
            "measured_value": _decimal(data.get("measured_value"), "measured_value"),
            "limit_value": _decimal(data.get("limit_value"), "limit_value"),
            "evidence_reference": evidence_reference,
            "source_refs": source_refs,
            "details": details,
        }
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    if (
        record_data["period_start"]
        and record_data["period_end"]
        and record_data["period_end"] < record_data["period_start"]
    ):
        return jsonify({"error": "period_end cannot be before period_start"}), 400
    profile = _service().get_profile(_org_id())
    if profile is None or not profile.enabled:
        return jsonify({"error": "Configure Compliance before adding records"}), 409
    requirements = capture_requirements(framework_slug, control_id, profile.settings or {})
    if requirements.get("record_types") and record_data["record_type"] not in requirements["record_types"]:
        allowed = ", ".join(requirements["record_types"])
        return jsonify({"error": f"This control requires a {allowed} record"}), 400
    if requirements.get("period") and (not record_data["period_start"] or not record_data["period_end"]):
        return jsonify({"error": "This control requires both period start and period end"}), 400
    if requirements.get("due_date") and not record_data["due_date"]:
        return jsonify({"error": "This control requires a review or expiry date"}), 400
    if requirements.get("evidence") and not record_data["evidence_reference"]:
        return jsonify({"error": "This control requires an evidence reference"}), 400
    if requirements.get("source_refs") and not record_data["source_refs"]:
        return jsonify({"error": "This control requires a linked Production record reference"}), 400
    invalid_source_refs = _service().invalid_core_source_references(_org_id(), record_data["source_refs"])
    if invalid_source_refs:
        # A source_ref that parses as a UUID but doesn't resolve inside this org is a
        # tenant-boundary probe (or a stale reference) the route turns into an ordinary
        # 400 -- without this it leaves no trace. Same `access_denied` event name
        # app/core/security/permissions.py and inventory_repo.py use, so one query
        # covers all three.
        logger.warning(
            "access_denied",
            reason="source_ref_not_in_org",
            feature="compliant",
            org_id=str(_org_id()),
            invalid_source_refs=invalid_source_refs,
        )
        return jsonify({"error": "Each Production record reference must be a record in this organisation"}), 400
    missing_fields = [
        field for field in requirements.get("fields", ()) if not record_data.get(field) and not details.get(field)
    ]
    if missing_fields:
        return jsonify({"error": f"This control requires: {', '.join(missing_fields)}"}), 400
    record = _service().add_record(_org_id(), g.current_user.id, record_data)
    log_action("create", "compliance_record", record.id, {"framework": framework_slug, "control": control_id})
    return jsonify({"record": serialise_record(record)}), 201


@api_bp.route("/api/compliant/reports/<framework_slug>", methods=["POST"])
@requires_auth
def create_report(framework_slug: str):
    data = request.get_json(silent=True) or {}
    try:
        report = _service().build_audit_pack(
            _org_id(),
            framework_slug,
            g.current_user.id,
            _date(data.get("period_start"), "period_start"),
            _date(data.get("period_end"), "period_end"),
        )
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    log_action("create", "compliance_report", UUID(report["report_id"]), {"framework": framework_slug})
    return jsonify({"report": report, "view_url": f"/api/compliant/reports/{report['report_id']}?format=html"}), 201


@api_bp.route("/api/compliant/reports/<report_id>", methods=["GET"])
@requires_auth
def get_report(report_id: str):
    try:
        report_uuid = UUID(report_id)
    except ValueError:
        return jsonify({"error": "Invalid report id"}), 400
    report = (
        db_session()
        .query(ComplianceReport)
        .filter(ComplianceReport.id == report_uuid, ComplianceReport.org_id == _org_id())
        .one_or_none()
    )
    if report is None:
        # A rejected org-scoped report lookup is a tenant-boundary probe (or a stale/
        # mistyped id) the route turns into a generic 404 -- must not distinguish
        # "doesn't exist" from "exists in another org" in status code or body (spec), so
        # the log doesn't try to either. Same `access_denied` event name as
        # permissions.py/inventory_repo.py, so one query covers all three.
        logger.warning(
            "access_denied",
            reason="report_not_found_or_cross_org",
            feature="compliant",
            org_id=str(_org_id()),
            report_id=str(report_uuid),
        )
        return jsonify({"error": "Report not found"}), 404
    output = (request.args.get("format") or "json").lower()
    if output == "html":
        return render_template("compliant/audit_pack.html", report=report)
    if output == "csv":
        stream = StringIO()
        writer = csv.writer(stream)
        writer.writerow(
            [
                "framework",
                "control",
                "record type",
                "status",
                "title",
                "period start",
                "period end",
                "due date",
                "evidence reference",
            ]
        )
        for record in report.payload.get("records", []):
            writer.writerow(
                [
                    report.framework_slug,
                    record.get("control_id"),
                    record.get("record_type"),
                    record.get("status"),
                    _csv_safe(record.get("title")),
                    record.get("period_start"),
                    record.get("period_end"),
                    record.get("due_date"),
                    _csv_safe(record.get("evidence_reference")),
                ]
            )
        return Response(
            stream.getvalue(),
            mimetype="text/csv",
            headers={"Content-Disposition": f'attachment; filename="{report.framework_slug}-audit-pack.csv"'},
        )
    return jsonify({"id": str(report.id), "checksum_sha256": report.checksum_sha256, "payload": report.payload}), 200


# ------------------------------------------------------------------
# Excise (plan 2.1): per-period lines from removals, lodgement, rates, products
# ------------------------------------------------------------------


def _excise_cfg():
    from app.features.compliant.modules.nz_alcohol import excise

    return excise, excise.settings_for(_service().get_profile(_org_id()))


def _parse_iso(value, field):
    try:
        return date.fromisoformat(str(value).strip())
    except (TypeError, ValueError):
        raise ValueError(f"{field} must be a date like 2026-10-01") from None


@api_bp.route("/api/compliant/nz-alcohol/excise", methods=["GET"])
@requires_auth
def get_excise_period():
    excise, cfg = _excise_cfg()
    try:
        day = _parse_iso(request.args["period"], "period") if request.args.get("period") else None
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    if day is None:
        day = excise.previous_period(excise.period_for(date.today(), cfg["frequency"])[0], cfg["frequency"])[0]
    return jsonify({"settings": cfg, "draft": excise.draft(db_session, _org_id(), day, cfg["frequency"])}), 200


@api_bp.route("/api/compliant/nz-alcohol/excise/periods", methods=["GET"])
@requires_auth
def list_excise_periods():
    """The current period and the last eleven, newest first, with lodged status."""
    from app.features.compliant.models.excise import ExciseLodgement

    excise, cfg = _excise_cfg()
    lodged = {
        r.period_start: r for r in db_session.query(ExciseLodgement).filter(ExciseLodgement.org_id == _org_id()).all()
    }
    start = excise.period_for(date.today(), cfg["frequency"])[0]
    rows = []
    for _ in range(12):
        s0, e0 = excise.period_for(start, cfg["frequency"])
        rec = lodged.get(s0)
        rows.append(
            {
                "period_start": s0.isoformat(),
                "label": excise.period_label(s0, e0),
                "due": excise.entry_due(e0).isoformat(),
                "open": date.today() < e0,
                "status": "lodged" if rec else "not lodged",
                "lodged_on": rec.lodged_on.isoformat() if rec else None,
                "nil_return": bool(rec.nil_return) if rec else None,
                "total_lal": (rec.snapshot or {}).get("total_lal") if rec else None,
            }
        )
        start = excise.previous_period(s0, cfg["frequency"])[0]
    return jsonify({"settings": cfg, "periods": rows}), 200


@api_bp.route("/api/compliant/nz-alcohol/excise/settings", methods=["PUT"])
@requires_auth
def update_excise_settings():
    excise, _cfg = _excise_cfg()
    data = request.get_json(silent=True) or {}
    frequency = data.get("frequency", "monthly")
    if frequency not in excise.FREQUENCIES:
        return jsonify({"error": "frequency must be monthly, six_monthly or twelve_monthly"}), 400
    tracking = data.get("tracking_from")
    try:
        tracking = _parse_iso(tracking, "tracking_from").isoformat() if tracking else None
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    profile = _service().get_profile(_org_id())
    if profile is None:
        return jsonify({"error": "Configure Compliant before setting up excise"}), 409
    settings = {**(profile.settings or {}), "excise_frequency": frequency, "excise_tracking_from": tracking}
    _service().upsert_profile(_org_id(), {"settings": settings})
    log_action(
        "update", "compliance_profile", profile.id, {"excise_frequency": frequency, "excise_tracking_from": tracking}
    )
    return jsonify({"settings": excise.settings_for(_service().get_profile(_org_id()))}), 200


@api_bp.route("/api/compliant/nz-alcohol/excise/lodge", methods=["POST"])
@requires_auth
def lodge_excise_period():
    excise, cfg = _excise_cfg()
    data = request.get_json(silent=True) or {}
    try:
        start = _parse_iso(data.get("period_start"), "period_start")
        lodged_on = _parse_iso(data.get("lodged_on") or date.today().isoformat(), "lodged_on")
        record = excise.lodge(
            db_session, _org_id(), start, cfg["frequency"], lodged_on, data.get("entry_reference"), g.current_user.id
        )
        db_session.commit()
    except ValueError as e:
        db_session.rollback()
        return jsonify({"error": str(e)}), 400
    except IntegrityError:
        db_session.rollback()
        return jsonify({"error": "That period is already recorded as lodged."}), 409
    log_action(
        "lodge_excise",
        "organisation",
        _org_id(),
        {
            "period_start": record.period_start.isoformat(),
            "nil_return": record.nil_return,
            "total_lal": (record.snapshot or {}).get("total_lal"),
        },
    )
    return jsonify({"draft": excise.draft(db_session, _org_id(), start, cfg["frequency"])}), 201


@api_bp.route("/api/compliant/nz-alcohol/excise/rates", methods=["GET"])
@requires_auth
def list_excise_rates():
    from app.features.compliant.models.excise import ExciseRate

    rows = (
        db_session.query(ExciseRate)
        .filter(ExciseRate.org_id == _org_id())
        .order_by(ExciseRate.tariff_item.asc(), ExciseRate.effective_from.desc())
        .all()
    )
    return jsonify(
        {
            "rates": [
                {
                    "id": str(r.id),
                    "tariff_item": r.tariff_item,
                    "description": r.description,
                    "rate_per_lal": f"{Decimal(str(r.rate_per_lal)).normalize():f}",
                    "effective_from": r.effective_from.isoformat(),
                }
                for r in rows
            ]
        }
    ), 200


@api_bp.route("/api/compliant/nz-alcohol/excise/rates", methods=["POST"])
@requires_auth
def add_excise_rate():
    from app.features.compliant.models.excise import ExciseRate

    data = request.get_json(silent=True) or {}
    tariff = str(data.get("tariff_item") or "").strip()
    if not tariff or len(tariff) > 100:
        return jsonify({"error": "tariff_item is required (up to 100 characters)"}), 400
    try:
        rate = Decimal(str(data.get("rate_per_lal")))
        effective = _parse_iso(data.get("effective_from"), "effective_from")
    except (InvalidOperation, ValueError) as e:
        return jsonify({"error": str(e) if isinstance(e, ValueError) else "rate_per_lal must be a number"}), 400
    if not rate.is_finite() or rate < 0:
        return jsonify({"error": "rate_per_lal must be 0 or more"}), 400
    db_session.add(
        ExciseRate(
            org_id=_org_id(),
            tariff_item=tariff,
            rate_per_lal=rate,
            effective_from=effective,
            description=(str(data.get("description") or "").strip()[:255] or None),
        )
    )
    try:
        db_session.commit()
    except IntegrityError:
        db_session.rollback()
        return jsonify({"error": "A rate for that tariff item already starts on that date"}), 409
    return list_excise_rates()


@api_bp.route("/api/compliant/nz-alcohol/excise/products", methods=["GET"])
@requires_auth
def list_excise_products():
    """Final outputs of every workflow, with their excise setup (pack volume, tariff item)."""
    from app.core.backend.go_live import workflow_outputs

    profiles = {p.inventory_name.casefold(): p for p in _service().product_profiles(_org_id())}
    rows = []
    for output in workflow_outputs(db_session, _org_id())["final_outputs"]:
        p = profiles.get(output["name"].casefold())
        rows.append(
            {
                "name": output["name"],
                "unit": output["unit"],
                "workflow": output["workflow"],
                "configured": p is not None,
                "pack_volume_ml": f"{Decimal(str(p.pack_volume_ml)).normalize():f}"
                if p is not None and p.pack_volume_ml
                else None,
                "tariff_item": p.customs_product_code if p is not None else None,
                "abv_fallback": f"{Decimal(str(p.abv_percent)).normalize():f}"
                if p is not None and p.abv_percent is not None
                else None,
            }
        )
    return jsonify({"products": rows}), 200


@api_bp.route("/api/compliant/nz-alcohol/excise/products", methods=["PUT"])
@requires_auth
def save_excise_product():
    from app.features.compliant.models.alcohol_product_profile import AlcoholProductProfile

    data = request.get_json(silent=True) or {}
    name = str(data.get("name") or "").strip()
    if not name:
        return jsonify({"error": "name is required"}), 400
    try:
        volume = Decimal(str(data["pack_volume_ml"])) if data.get("pack_volume_ml") not in (None, "") else None
        abv = Decimal(str(data["abv_fallback"])) if data.get("abv_fallback") not in (None, "") else None
    except InvalidOperation:
        return jsonify({"error": "Pack volume and ABV must be numbers"}), 400
    if volume is not None and not (0 < volume <= 100000):
        return jsonify({"error": "Pack volume must be more than 0 mL"}), 400
    if abv is not None and not (0 <= abv <= 100):
        return jsonify({"error": "ABV must be between 0 and 100"}), 400
    tariff = str(data.get("tariff_item") or "").strip()[:100] or None
    profile = (
        db_session.query(AlcoholProductProfile)
        .filter(AlcoholProductProfile.org_id == _org_id(), AlcoholProductProfile.inventory_name == name)
        .one_or_none()
    )
    if profile is None:
        profile = AlcoholProductProfile(
            org_id=_org_id(), inventory_name=name, product_type=str(data.get("product_type") or "spirits")[:40]
        )
        db_session.add(profile)
    profile.pack_volume_ml = volume
    profile.abv_percent = abv
    profile.customs_product_code = tariff
    profile.is_active = True
    db_session.commit()
    return list_excise_products()
