"""Tenant-scoped JSON and audit-pack routes for Compliant."""

import csv
from datetime import date
from decimal import Decimal, InvalidOperation
from io import StringIO
from uuid import UUID

from flask import Blueprint, Response, g, jsonify, render_template, request
from sqlalchemy.exc import IntegrityError

from app.core.db import db_session
from app.core.db.models.user import UserRole
from app.core.security.permissions import requires_auth, requires_role
from app.core.utils.log_action import log_action
from app.features.compliant.models import ComplianceReport
from app.features.compliant.modules.nz_alcohol.catalogue import capture_requirements, framework_by_slug
from app.features.compliant.modules.nz_alcohol.workflow_rules import validate_workflow_settings
from app.features.compliant.platform.workflow_rules import workflow_context
from app.features.compliant.service import ComplianceService, serialise_record
from app.observability import get_logger

logger = get_logger(__name__)

api_bp = Blueprint("compliant_api", __name__)
_RECORD_TYPES = {"attestation", "reading", "lodgement", "competency", "incident"}
_RECORD_STATUSES = {"complete", "failed", "open", "superseded"}
_CSV_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")
_FOOD_CONTROL_PROGRAMMES = {"np1", "np2", "np3", "none"}
_LIQUOR_LICENCE_TYPES = {"on", "off", "club", "special"}


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


@api_bp.route("/api/compliant/np3-audit", methods=["GET"])
@requires_auth
def np3_audit():
    try:
        audit = _service().np3_audit(_org_id())
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 409
    if request.args.get("format") != "csv":
        return jsonify(audit), 200

    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(
        [
            "Category",
            "Verification topic",
            "Status",
            "Evidence records",
            "Evidence references",
            "Core source IDs",
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


@api_bp.route("/api/compliant/capture-context", methods=["GET"])
@requires_auth
def capture_context():
    """Return module-contributed workflow extensions in Core's generic contract."""
    return jsonify(workflow_context(db_session(), _org_id())), 200


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
        licence_types = settings.get("liquor_licence_types")
        if licence_types is not None and (
            not isinstance(licence_types, list)
            or not all(isinstance(item, str) and item in _LIQUOR_LICENCE_TYPES for item in licence_types)
        ):
            return jsonify({"error": "liquor_licence_types must contain only on, off, club, or special"}), 400
        workflow_settings_error = validate_workflow_settings(settings)
        if workflow_settings_error:
            return jsonify({"error": workflow_settings_error}), 400
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
                    "abv_percent": str(product.abv_percent),
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
        return jsonify({"error": "Configure Compliant before adding records"}), 409
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
        return jsonify({"error": "This control requires a linked Core source reference"}), 400
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
        return jsonify({"error": "Each Core source reference must be a record in this organisation"}), 400
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
