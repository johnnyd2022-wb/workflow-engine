"""Tenant-scoped JSON and audit-pack routes for Compliant."""

import calendar
import csv
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from io import BytesIO, StringIO
from uuid import UUID

from flask import Blueprint, Response, g, jsonify, render_template, send_file
from sqlalchemy.exc import IntegrityError

from app.core.backend.idempotency import idempotent_write
from app.core.db import db_session
from app.core.db.models.execution_evidence import EVIDENCE_STATUS_ACTIVE, ExecutionEvidence
from app.core.db.models.user import User, UserRole
from app.core.security.permissions import requires_auth, requires_role
from app.core.utils.log_action import log_action
from app.features.compliant import record_files as record_files_module
from app.features.compliant.models import ComplianceRecord, ComplianceReport
from app.features.compliant.modules.nz_alcohol import excise_tariff
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
from app.features.compliant.routes.validation_payloads import (
    ABVRulesInput,
    AlcoholProductInput,
    AttestationInput,
    ComplianceProfileInput,
    ComplianceRecordInput,
    ExciseLodgementInput,
    ExciseProductInput,
    ExciseRateInput,
    ExciseSettingsInput,
    NPLogInput,
    ReportInput,
    ReviewIntervalInput,
)
from app.features.compliant.service import ComplianceService, serialise_record
from app.features.execution.evidence.evidence_service import get_evidence_for_download
from app.observability import get_logger
from app.utils.request_validation import InvalidInputError, query_int, query_text, read_json

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
_CSV_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


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
        number = Decimal(str(value))
        if number.is_finite():
            return str(number)
    except InvalidOperation:
        pass
    raise ValueError(f"{field} must be a finite number") from None


@api_bp.route("/api/compliant/overview", methods=["GET"])
@requires_auth
def overview():
    return jsonify(_service().overview(_org_id())), 200


@api_bp.route("/api/compliant/core-sources", methods=["GET"])
@requires_auth
def core_sources():
    """Search selectable Core proof without exposing another tenant's records."""
    try:
        kind = query_text("kind", max_length=14)
        query = query_text("q", max_length=100)
        offset = query_int("offset", default=0, minimum=0, maximum=10000)
    except InvalidInputError as exc:
        return exc.response()
    if kind not in {"file", "execution-step", "execution", "movement"}:
        return InvalidInputError({"kind": "Choose an allowed source type."}).response()
    return jsonify(_service().search_core_sources(_org_id(), kind, query, offset)), 200


@api_bp.route("/api/compliant/np3-audit", methods=["GET"])
@requires_auth
def np3_audit():
    try:
        export_format = query_text("format", default="json", max_length=4)
        if export_format not in {"", "json", "csv", "pdf"}:
            raise InvalidInputError({"format": "Choose json, csv or pdf."})
        audit = _service().np3_audit(_org_id())
    except InvalidInputError as exc:
        return exc.response()
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 409
    if export_format in {"", "json"}:
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
        record_files = {}
        for row in audit["rows"]:
            for item in (*row["history"], *row["log_entries"]):
                for attachment in item.get("files") or []:
                    stored = record_files_module.get_file(
                        db_session, _org_id(), UUID(str(item["id"])), UUID(attachment["id"])
                    )
                    record_files[attachment["id"]] = {
                        **attachment,
                        "content": record_files_module.read_content(stored) if stored else None,
                    }
        return Response(
            build_np3_evidence_register_pdf(audit, uploaded_evidence, record_files),
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
    try:
        data = read_json(ReviewIntervalInput)
    except InvalidInputError as exc:
        return exc.response()
    profile = _service().get_profile(_org_id())
    if profile is None or not profile.enabled:
        return jsonify({"error": "Configure Compliance before changing NP3 check settings"}), 409
    settings = dict(profile.settings or {})
    intervals = dict(settings.get("np3_check_review_intervals") or {})
    intervals[control_id] = data.review_interval_months
    settings["np3_check_review_intervals"] = intervals
    profile = _service().upsert_profile(_org_id(), {"settings": settings})
    log_action("update", "compliance_profile", profile.id, {"np3_check_review_interval": control_id})
    return jsonify({"review_interval_months": intervals[control_id]}), 200


@api_bp.route("/api/compliant/np3-audit/attestations", methods=["POST"])
@requires_auth
@idempotent_write("np3_attestation")  # GL-U03: a retried save adds the evidence once
def attest_np3_check():
    """Append a focused NP3 self-review without exposing the generic record register."""
    try:
        data = read_json(AttestationInput)
    except InvalidInputError as exc:
        return exc.response()
    control_id = data.control_id
    framework = framework_by_slug(f"{_np_programme()}-food-control") or {}
    controls = dict(framework.get("controls", ()))
    if control_id not in controls:
        return jsonify({"error": "Unknown NP3 check"}), 400
    how_we_meet = data.how_we_meet.strip()
    if not how_we_meet:
        return InvalidInputError({"how_we_meet": "Describe how you meet this requirement."}).response()
    if not data.confirmed:
        return jsonify({"error": "Confirm that you reviewed this check before signing it off"}), 400
    review_interval_months = data.review_interval_months
    evidence_reference = data.evidence_reference or None
    source_refs = data.source_refs
    profile = _service().get_profile(_org_id())
    if profile is None or not profile.enabled:
        return jsonify({"error": "Configure Compliance before signing off checks"}), 409
    if (profile.settings or {}).get("food_control_programme", "np3") not in _NP_PROGRAMMES:
        return jsonify({"error": "Select a national programme in Configuration before signing off checks"}), 409
    invalid_source_refs = _service().invalid_core_source_references(_org_id(), source_refs)
    if invalid_source_refs:
        logger.warning("access_denied", reason="source_ref_not_in_org", feature="compliant", org_id=str(_org_id()))
        return jsonify({"error": "Each Production record reference must be a record in this organisation"}), 400
    evidence_fields = data.evidence_fields
    allowed_evidence_fields = {field["key"] for field in evidence_playbook(control_id)["fields"]}
    if not set(evidence_fields).issubset(allowed_evidence_fields):
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
@idempotent_write("np3_log")  # GL-U03: a retried save adds the evidence once
def add_np3_check_log(control_id: str):
    """Append a control-specific operational log entry from the check workspace."""
    template = np3_log_template(control_id)
    framework = framework_by_slug(f"{_np_programme()}-food-control") or {}
    controls = dict(framework.get("controls", ()))
    if control_id not in controls or template is None:
        return jsonify({"error": "This NP3 check does not have a built-in log"}), 404
    try:
        fields = read_json(NPLogInput).fields
    except InvalidInputError as exc:
        return exc.response()
    template_fields = {field["key"]: field for field in template["fields"]}
    if not set(fields).issubset(template_fields):
        return jsonify({"error": "Log fields do not match this NP3 check"}), 400
    normalised: dict[str, str] = {}
    for key, definition in template_fields.items():
        raw_value = fields.get(key, "")
        if raw_value is None:
            raw_value = ""
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
    if status == "open" and event_date.year == date.max.year and event_date.month == 12:
        return InvalidInputError({"fields.event_date": "Choose a date that allows a follow-up next month."}).response()
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


def _np3_record(record_id: str) -> ComplianceRecord | None:
    """The org's own NP attestation or log entry, or None (also for another org's id)."""
    try:
        rid = UUID(record_id)
    except ValueError:
        return None
    record = (
        db_session.query(ComplianceRecord)
        .filter(ComplianceRecord.id == rid, ComplianceRecord.org_id == _org_id())
        .one_or_none()
    )
    if record is None or record.framework_slug not in {f"{programme}-food-control" for programme in _NP_PROGRAMMES}:
        return None
    is_log = bool((record.details or {}).get("np3_log_type"))
    return record if record.record_type == "attestation" or is_log else None


@api_bp.route("/api/compliant/np3-audit/records/<record_id>/files", methods=["POST"])
@requires_auth
def attach_np3_record_file(record_id: str):
    """Attach a PDF or image to an NP attestation or log entry the org already recorded."""
    record = _np3_record(record_id)
    if record is None:
        return jsonify({"error": "Record not found"}), 404
    if record_files_module.file_count(db_session, _org_id(), record.id) >= record_files_module.MAX_FILES_PER_RECORD:
        return (
            jsonify({"error": f"At most {record_files_module.MAX_FILES_PER_RECORD} files can be attached to a record"}),
            409,
        )
    temp_path, mime, name, _size, error = record_files_module.receive_upload()
    if temp_path is None:
        return jsonify({"error": error}), 400
    row = record_files_module.attach_file(db_session, _org_id(), record, g.current_user.id, temp_path, mime, name)
    log_action("create", "compliance_record_file", row.id, {"record_id": str(record.id), "mime_type": mime})
    attached = record_files_module.files_by_record(db_session, _org_id(), [record.id])[record.id]
    return jsonify({"file": next(item for item in attached if item["id"] == str(row.id))}), 201


@api_bp.route("/api/compliant/np3-audit/records/<record_id>/files/<file_id>", methods=["GET"])
@requires_auth
def download_np3_record_file(record_id: str, file_id: str):
    record = _np3_record(record_id)
    try:
        fid = UUID(file_id)
    except ValueError:
        fid = None
    row = record_files_module.get_file(db_session, _org_id(), record.id, fid) if record and fid else None
    content = record_files_module.read_content(row) if row else None
    if row is None or content is None:
        return jsonify({"error": "File not found"}), 404
    response = send_file(
        BytesIO(content), mimetype=row.mime_type, as_attachment=True, download_name=row.file_name, max_age=0
    )
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Cache-Control"] = "private, no-store"
    return response


@api_bp.route("/api/compliant/capture-context", methods=["GET"])
@requires_auth
def capture_context():
    """Return module-contributed workflow extensions in Core's generic contract.

    ``?step_id=`` (the step definition being executed) adds any rules that apply only to
    that step; without it, only rules that apply to every step are returned.
    """
    try:
        raw_step_id = query_text("step_id", max_length=36)
    except InvalidInputError as exc:
        return exc.response()
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
    try:
        rules = read_json(ABVRulesInput).rules
    except InvalidInputError as exc:
        return exc.response()
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
    try:
        data = read_json(ComplianceProfileInput).model_dump(mode="json", exclude_unset=True)
    except InvalidInputError as exc:
        return exc.response()
    settings = data.get("settings")
    if settings is not None:
        check_intervals = settings.get("np3_check_review_intervals")
        if check_intervals is not None:
            controls = dict((framework_by_slug(f"{_np_programme()}-food-control") or {}).get("controls", ()))
            if not set(check_intervals).issubset(controls):
                return jsonify({"error": "np3_check_review_intervals must contain valid NP3 checks and intervals"}), 400
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
    try:
        data = read_json(AlcoholProductInput).model_dump()
        data["customs_product_code"] = data["customs_product_code"] or None
        product = _service().add_product_profile(_org_id(), data)
    except InvalidInputError as exc:
        return exc.response()
    except IntegrityError as exc:
        db_session().rollback()
        if "uq_compliance_alcohol_product_org_name" in str(exc):
            return jsonify({"error": "A profile already exists for this inventory name"}), 409
        raise
    log_action("create", "compliance_alcohol_product_profile", product.id, {"product_type": data["product_type"]})
    return jsonify({"product": {"id": str(product.id), "inventory_name": product.inventory_name}}), 201


@api_bp.route("/api/compliant/records", methods=["GET"])
@requires_auth
def list_records():
    try:
        framework_slug = query_text("framework", max_length=80) or None
    except InvalidInputError as exc:
        return exc.response()
    if framework_slug and framework_by_slug(framework_slug) is None:
        return jsonify({"error": "Unknown framework"}), 400
    records = _service().records(_org_id(), framework_slug)
    return jsonify(
        {"records": [serialise_record(record) for record in records[:200]], "total_count": len(records)}
    ), 200


@api_bp.route("/api/compliant/records", methods=["POST"])
@requires_auth
@idempotent_write("compliance_record")  # GL-U03: a retried save adds the evidence once
def create_record():
    try:
        data = read_json(ComplianceRecordInput)
    except InvalidInputError as exc:
        return exc.response()
    framework_slug = data.framework_slug
    framework = framework_by_slug(framework_slug)
    if framework is None:
        return jsonify({"error": "Unknown framework"}), 400
    control_ids = {control_id for control_id, _ in framework["controls"]}
    control_id = data.control_id
    if control_id not in control_ids:
        return jsonify({"error": "Unknown control for framework"}), 400
    record_data = data.model_dump(exclude={"declared_litres_of_alcohol"})
    details = record_data["details"]
    if data.declared_litres_of_alcohol is not None:
        details["declared_litres_of_alcohol"] = str(data.declared_litres_of_alcohol)
    if "declared_litres_of_alcohol" in details:
        try:
            _decimal(details["declared_litres_of_alcohol"], "declared_litres_of_alcohol")
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
    record_data["evidence_reference"] = data.evidence_reference or None
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
    try:
        data = read_json(ReportInput)
        if data.period_start and data.period_end and data.period_start > data.period_end:
            raise InvalidInputError({"period_end": "Choose a date on or after the period start."})
        report = _service().build_audit_pack(
            _org_id(),
            framework_slug,
            g.current_user.id,
            data.period_start,
            data.period_end,
        )
    except InvalidInputError as exc:
        return exc.response()
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
    try:
        output = query_text("format", default="json", max_length=4).lower() or "json"
        if output not in {"json", "html", "csv"}:
            raise InvalidInputError({"format": "Choose json, html or csv."})
    except InvalidInputError as exc:
        return exc.response()
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
    """One period's entry; with several sites, one CCA licence's (``cca``, else the first)."""
    excise, cfg = _excise_cfg()
    try:
        raw_day = query_text("period", max_length=10)
        day = _parse_iso(raw_day, "period") if raw_day else None
        licence_id = _cca_param(query_text("cca", max_length=36))
        if day is None:
            day = excise.previous_period(excise.period_for(date.today(), cfg["frequency"])[0], cfg["frequency"])[0]
        current = excise.draft(db_session, _org_id(), day, cfg["frequency"], licence_id=licence_id)
    except InvalidInputError as exc:
        return exc.response()
    except OverflowError:
        return InvalidInputError({"period": "Choose a date within a valid excise period."}).response()
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    return jsonify({"settings": cfg, "draft": current}), 200


def _cca_param(value):
    if not value:
        return None
    try:
        return UUID(str(value))
    except ValueError:
        raise ValueError("cca must be a CCA licence id") from None


@api_bp.route("/api/compliant/nz-alcohol/excise/periods", methods=["GET"])
@requires_auth
def list_excise_periods():
    """The current period and the last eleven, newest first, with lodged status."""
    from app.features.compliant.models.excise import ExciseLodgement

    excise, cfg = _excise_cfg()
    try:
        licence_id = _cca_param(query_text("cca", max_length=36))
    except InvalidInputError as exc:
        return exc.response()
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    if licence_id is None and excise.per_cca(db_session, _org_id()):
        current = excise.period_for(date.today(), cfg["frequency"])
        first = excise.cca_licences(db_session, _org_id(), current[0], current[1])
        licence_id = first[0].id if first else None
    lodged = {
        r.period_start: r
        for r in db_session.query(ExciseLodgement).filter(
            ExciseLodgement.org_id == _org_id(), ExciseLodgement.licence_id.is_not_distinct_from(licence_id)
        )
    }
    start = excise.period_for(date.today(), cfg["frequency"])[0]
    rows = []
    for _ in range(12):
        s0, e0 = excise.period_for(start, cfg["frequency"])
        rec = lodged.get(s0)
        rows.append(
            {
                "period_start": s0.isoformat(),
                "period_end": (e0 - timedelta(days=1)).isoformat(),
                "label": excise.period_label(s0, e0),
                "due": excise.entry_due(e0).isoformat(),
                "open": date.today() < e0,
                "status": "lodged" if rec else "not lodged",
                "lodged_on": rec.lodged_on.isoformat() if rec else None,
                "nil_return": bool(rec.nil_return) if rec else None,
                "total_lal": (rec.snapshot or {}).get("total_lal") if rec else None,
                "total": ((rec.snapshot or {}).get("entry") or {}).get("total") if rec else None,
            }
        )
        start = excise.previous_period(s0, cfg["frequency"])[0]
    return jsonify({"settings": cfg, "periods": rows, "total_count": len(rows)}), 200


@api_bp.route("/api/compliant/nz-alcohol/excise/position", methods=["GET"])
@requires_auth
def get_excise_position():
    """Where the org stands with Customs: the year's duty, this period, stocktake, remissions, setup."""
    from app.features.compliant.modules.nz_alcohol import excise

    profile = _service().get_profile(_org_id())
    return jsonify(excise.position(db_session, _org_id(), profile)), 200


@api_bp.route("/api/compliant/nz-alcohol/excise/settings", methods=["PUT"])
@requires_auth
def update_excise_settings():
    excise, _cfg = _excise_cfg()
    try:
        data = read_json(ExciseSettingsInput)
    except InvalidInputError as exc:
        return exc.response()
    frequency = data.frequency
    tracking = data.tracking_from.isoformat() if data.tracking_from else None
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
    try:
        data = read_json(ExciseLodgementInput)
        start = data.period_start
        lodged_on = data.lodged_on or date.today()
        licence_id = data.cca
        record = excise.lodge(
            db_session,
            _org_id(),
            start,
            cfg["frequency"],
            lodged_on,
            data.entry_reference,
            g.current_user.id,
            licence_id=licence_id,
        )
        db_session.commit()
    except InvalidInputError as exc:
        return exc.response()
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
            "cca": str(record.licence_id) if record.licence_id else None,
            "nil_return": record.nil_return,
            "total_lal": (record.snapshot or {}).get("total_lal"),
        },
    )
    return jsonify({"draft": excise.draft(db_session, _org_id(), start, cfg["frequency"], licence_id=licence_id)}), 201


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

    try:
        data = read_json(ExciseRateInput)
    except InvalidInputError as exc:
        return exc.response()
    db_session.add(
        ExciseRate(
            org_id=_org_id(),
            tariff_item=data.tariff_item,
            rate_per_lal=data.rate_per_lal,
            effective_from=data.effective_from,
            description=data.description or None,
        )
    )
    try:
        db_session.commit()
    except IntegrityError:
        db_session.rollback()
        return jsonify({"error": "A rate for that tariff item already starts on that date"}), 409
    return list_excise_rates()


@api_bp.route("/api/compliant/nz-alcohol/excise/categories", methods=["GET"])
@requires_auth
def list_excise_categories():
    """The built-in Customs guide: product types, their excise items and today's rates."""
    return jsonify(
        {
            "categories": excise_tariff.catalogue(date.today()),
            "source": excise_tariff.SOURCE,
            "guide": excise_tariff.guide_status(date.today()),
        }
    ), 200


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
                "excise_category": p.excise_category if p is not None else None,
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

    try:
        data = read_json(ExciseProductInput)
    except InvalidInputError as exc:
        return exc.response()
    category = data.excise_category or None
    if category is not None and excise_tariff.category(category) is None:
        return jsonify({"error": "Unknown product type"}), 400
    profile = (
        db_session.query(AlcoholProductProfile)
        .filter(AlcoholProductProfile.org_id == _org_id(), AlcoholProductProfile.inventory_name == data.name)
        .one_or_none()
    )
    if profile is None:
        profile = AlcoholProductProfile(
            org_id=_org_id(), inventory_name=data.name, product_type=data.product_type or "spirits"
        )
        db_session.add(profile)
    profile.pack_volume_ml = data.pack_volume_ml
    profile.abv_percent = data.abv_fallback
    profile.customs_product_code = data.tariff_item or None
    profile.excise_category = category
    profile.is_active = True
    db_session.commit()
    return list_excise_products()
