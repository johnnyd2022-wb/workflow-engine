"""CRM JSON API routes — customers, invoices, notes, tasks, analytics, product mappings."""

import logging
from datetime import date, timedelta
from uuid import UUID

from flask import Blueprint, g, jsonify, request

from app.core.db import db_session
from app.core.security.permissions import requires_auth
from app.core.utils.log_action import log_action
from app.features.crm.services.crm_service import CRMService
from app.features.crm.services.xero_api_client import XeroInsufficientScopeError

logger = logging.getLogger(__name__)

api_bp = Blueprint("crm_api", __name__)


def _crm_service() -> CRMService:
    return CRMService(db_session())


# ------------------------------------------------------------------
# Customers
# ------------------------------------------------------------------


@api_bp.route("/api/crm/customers", methods=["GET"])
@requires_auth
def list_customers():
    org_id = UUID(g.org_id)
    search = request.args.get("q", "").strip() or None
    status = request.args.get("status") or None
    sort_by = request.args.get("sort_by", "name")
    sort_dir = request.args.get("sort_dir", "asc")
    page = max(1, int(request.args.get("page", 1)))
    page_size = min(100, max(1, int(request.args.get("page_size", 50))))

    result = _crm_service().list_customers(
        org_id=org_id,
        search=search,
        status=status,
        sort_by=sort_by,
        sort_dir=sort_dir,
        page=page,
        page_size=page_size,
    )
    return jsonify(result), 200


@api_bp.route("/api/crm/customers/<contact_id>", methods=["GET"])
@requires_auth
def get_customer(contact_id: str):
    org_id = UUID(g.org_id)
    result = _crm_service().get_customer(UUID(contact_id), org_id)
    if not result:
        return jsonify({"error": "Customer not found"}), 404
    return jsonify(result), 200


# ------------------------------------------------------------------
# Invoices
# ------------------------------------------------------------------


@api_bp.route("/api/crm/customers/<contact_id>/invoices", methods=["GET"])
@requires_auth
def get_customer_invoices(contact_id: str):
    org_id = UUID(g.org_id)
    page = max(1, int(request.args.get("page", 1)))
    page_size = min(100, max(1, int(request.args.get("page_size", 25))))
    result = _crm_service().get_customer_invoices(UUID(contact_id), org_id, page=page, page_size=page_size)
    return jsonify(result), 200


@api_bp.route("/api/crm/invoices", methods=["GET"])
@requires_auth
def get_org_invoices():
    org_id = UUID(g.org_id)
    kind = (request.args.get("kind") or "all").strip().lower()
    if kind not in {"all", "this_month", "outstanding"}:
        return jsonify({"error": "kind must be all, this_month or outstanding"}), 400
    page = max(1, int(request.args.get("page", 1)))
    page_size = min(100, max(1, int(request.args.get("page_size", 50))))
    result = _crm_service().get_org_invoices(org_id, kind=kind, page=page, page_size=page_size)
    return jsonify(result), 200


@api_bp.route("/api/crm/customers/<contact_id>/line-item-descriptions", methods=["GET"])
@requires_auth
def get_customer_line_item_descriptions(contact_id: str):
    org_id = UUID(g.org_id)
    options = _crm_service().get_customer_line_item_options(UUID(contact_id), org_id)
    return jsonify({"line_item_options": options}), 200


@api_bp.route("/api/crm/customers/<contact_id>/line-item-pricing", methods=["GET"])
@requires_auth
def get_customer_line_item_pricing(contact_id: str):
    org_id = UUID(g.org_id)
    description = (request.args.get("description") or "").strip() or None
    item_code = (request.args.get("item_code") or "").strip() or None
    pricing = _crm_service().get_customer_line_item_pricing(
        UUID(contact_id),
        org_id,
        description=description,
        item_code=item_code,
    )
    return jsonify({"line_item_pricing": pricing}), 200


@api_bp.route("/api/crm/customers/<contact_id>/invoice-defaults", methods=["GET"])
@requires_auth
def get_customer_invoice_defaults(contact_id: str):
    org_id = UUID(g.org_id)
    invoice_date_raw = (request.args.get("invoice_date") or "").strip()
    if not invoice_date_raw:
        return jsonify({"error": "invoice_date is required"}), 400
    try:
        invoice_date = date.fromisoformat(invoice_date_raw)
    except ValueError:
        return jsonify({"error": "invoice_date must be YYYY-MM-DD"}), 400
    try:
        due_date = _crm_service().suggest_invoice_due_date(UUID(contact_id), org_id, invoice_date)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    return jsonify({"due_date": due_date.isoformat() if due_date else None}), 200


@api_bp.route("/api/crm/line-item-descriptions", methods=["GET"])
@requires_auth
def get_org_line_item_descriptions():
    org_id = UUID(g.org_id)
    options = _crm_service().get_org_line_item_options(org_id)
    return jsonify({"line_item_options": options}), 200


@api_bp.route("/api/crm/customers/<contact_id>/invoices", methods=["POST"])
@requires_auth
def create_customer_invoice(contact_id: str):
    org_id = UUID(g.org_id)
    data = request.get_json() or {}
    try:
        invoice = _crm_service().create_customer_invoice(UUID(contact_id), org_id, data)
    except XeroInsufficientScopeError as e:
        return (
            jsonify(
                {
                    "error": "xero_insufficient_scope",
                    "message": str(e),
                    "action": "reconnect_xero",
                }
            ),
            401,
        )
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    return jsonify({"invoice": invoice}), 201


@api_bp.route("/api/crm/invoices/<invoice_id>/authorise", methods=["POST"])
@requires_auth
def authorise_invoice(invoice_id: str):
    org_id = UUID(g.org_id)
    try:
        invoice = _crm_service().authorise_invoice(UUID(invoice_id), org_id)
    except XeroInsufficientScopeError as e:
        return (
            jsonify(
                {
                    "error": "xero_insufficient_scope",
                    "message": str(e),
                    "action": "reconnect_xero",
                }
            ),
            401,
        )
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    return jsonify({"invoice": invoice}), 200


@api_bp.route("/api/crm/customers/<contact_id>/analytics", methods=["GET"])
@requires_auth
def get_customer_analytics(contact_id: str):
    org_id = UUID(g.org_id)
    start_date = None
    end_date = None
    start_raw = (request.args.get("start_date") or "").strip()
    end_raw = (request.args.get("end_date") or "").strip()
    if start_raw:
        try:
            start_date = date.fromisoformat(start_raw)
        except ValueError:
            return jsonify({"error": "start_date must be YYYY-MM-DD"}), 400
    if end_raw:
        try:
            end_date = date.fromisoformat(end_raw) + timedelta(days=1)
        except ValueError:
            return jsonify({"error": "end_date must be YYYY-MM-DD"}), 400
    data = _crm_service().get_customer_analytics(
        UUID(contact_id),
        org_id,
        start_date=start_date,
        end_date=end_date,
    )
    return jsonify(data), 200


# ------------------------------------------------------------------
# Notes
# ------------------------------------------------------------------


@api_bp.route("/api/crm/customers/<contact_id>/notes", methods=["POST"])
@requires_auth
def create_note(contact_id: str):
    org_id = UUID(g.org_id)
    data = request.get_json() or {}
    content = (data.get("content") or "").strip()
    if not content:
        return jsonify({"error": "content is required"}), 400

    svc = _crm_service()
    note = svc.create_note(org_id, UUID(contact_id), content, UUID(g.user_id) if g.user_id else None)
    log_action("create", "crm_note", None, {"contact_id": contact_id})
    return jsonify({"note": note}), 201


@api_bp.route("/api/crm/notes/<note_id>", methods=["PUT"])
@requires_auth
def update_note(note_id: str):
    org_id = UUID(g.org_id)
    data = request.get_json() or {}
    content = (data.get("content") or "").strip()
    if not content:
        return jsonify({"error": "content is required"}), 400

    note = _crm_service().update_note(UUID(note_id), org_id, content)
    if not note:
        return jsonify({"error": "Note not found"}), 404
    return jsonify({"note": note}), 200


@api_bp.route("/api/crm/notes/<note_id>", methods=["DELETE"])
@requires_auth
def delete_note(note_id: str):
    org_id = UUID(g.org_id)
    ok = _crm_service().delete_note(UUID(note_id), org_id)
    if not ok:
        return jsonify({"error": "Note not found"}), 404
    return jsonify({"ok": True}), 200


# ------------------------------------------------------------------
# Tasks
# ------------------------------------------------------------------


@api_bp.route("/api/crm/tasks", methods=["GET"])
@requires_auth
def list_tasks():
    org_id = UUID(g.org_id)
    contact_id = request.args.get("contact_id")
    status = request.args.get("status")
    assigned_to = request.args.get("assigned_to")

    tasks = _crm_service().list_tasks(
        org_id=org_id,
        contact_id=UUID(contact_id) if contact_id else None,
        status=status or None,
        assigned_to=UUID(assigned_to) if assigned_to else None,
    )
    return jsonify({"tasks": tasks}), 200


@api_bp.route("/api/crm/tasks", methods=["POST"])
@requires_auth
def create_task():
    org_id = UUID(g.org_id)
    data = request.get_json() or {}
    if not data.get("title"):
        return jsonify({"error": "title is required"}), 400

    try:
        task = _crm_service().create_task(org_id, data, UUID(g.user_id) if g.user_id else None)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    log_action("create", "crm_task", None, {"title": data.get("title")})
    return jsonify({"task": task}), 201


@api_bp.route("/api/crm/tasks/<task_id>", methods=["PUT"])
@requires_auth
def update_task(task_id: str):
    org_id = UUID(g.org_id)
    data = request.get_json() or {}
    try:
        task = _crm_service().update_task(UUID(task_id), org_id, data)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    if not task:
        return jsonify({"error": "Task not found"}), 404
    log_action("update", "crm_task", UUID(task_id), {"status": data.get("status")})
    return jsonify({"task": task}), 200


@api_bp.route("/api/crm/tasks/<task_id>", methods=["DELETE"])
@requires_auth
def delete_task(task_id: str):
    org_id = UUID(g.org_id)
    ok = _crm_service().delete_task(UUID(task_id), org_id)
    if not ok:
        return jsonify({"error": "Task not found"}), 404
    return jsonify({"ok": True}), 200


# ------------------------------------------------------------------
# Analytics
# ------------------------------------------------------------------


@api_bp.route("/api/crm/analytics/monthly-sales", methods=["GET"])
@requires_auth
def monthly_sales():
    org_id = UUID(g.org_id)
    months = min(24, max(1, int(request.args.get("months", 12))))
    data = _crm_service().monthly_sales(org_id, months=months)
    return jsonify({"monthly_sales": data}), 200


@api_bp.route("/api/crm/analytics/customer-breakdown", methods=["GET"])
@requires_auth
def customer_breakdown():
    org_id = UUID(g.org_id)
    top_n = min(50, max(1, int(request.args.get("top_n", 20))))
    data = _crm_service().customer_breakdown(org_id, top_n=top_n)
    return jsonify({"customer_breakdown": data}), 200


@api_bp.route("/api/crm/analytics/rankings", methods=["GET"])
@requires_auth
def rankings():
    org_id = UUID(g.org_id)
    entity = (request.args.get("entity") or "customers").strip().lower()
    if entity not in {"customers", "products", "customers_by_product"}:
        return jsonify({"error": "entity must be customers, products or customers_by_product"}), 400

    direction = (request.args.get("direction") or "top").strip().lower()
    if direction not in {"top", "bottom"}:
        return jsonify({"error": "direction must be top or bottom"}), 400

    limit = min(50, max(1, int(request.args.get("limit", 10))))
    months = request.args.get("months")
    period_n = request.args.get("period_n")
    period_unit = (request.args.get("period_unit") or "months").strip().lower()
    start_month = (request.args.get("start_month") or "").strip()
    end_month = (request.args.get("end_month") or "").strip()
    start_date_raw = (request.args.get("start_date") or "").strip()
    end_date_raw = (request.args.get("end_date") or "").strip()

    start_date = None
    end_date = None

    if period_n:
        try:
            n = min(3650, max(1, int(period_n)))
        except ValueError:
            return jsonify({"error": "period_n must be an integer"}), 400
        today = date.today()
        # Inclusive "last n <unit>" window ending today.
        end_date = today + timedelta(days=1)
        if period_unit == "days":
            start_date = today - timedelta(days=n - 1)
        elif period_unit == "weeks":
            start_date = today - timedelta(days=(n * 7) - 1)
        elif period_unit == "years":
            start_date = today - timedelta(days=(n * 365) - 1)
        else:
            # default: months
            current_month_start = today.replace(day=1)
            y = current_month_start.year
            mm = current_month_start.month - (n - 1)
            while mm <= 0:
                y -= 1
                mm += 12
            start_date = date(y, mm, 1)
            if current_month_start.month == 12:
                end_date = date(current_month_start.year + 1, 1, 1)
            else:
                end_date = date(current_month_start.year, current_month_start.month + 1, 1)
    elif start_date_raw:
        try:
            start_date = date.fromisoformat(start_date_raw)
        except ValueError:
            return jsonify({"error": "start_date must be YYYY-MM-DD"}), 400
        if end_date_raw:
            try:
                end_date = date.fromisoformat(end_date_raw) + timedelta(days=1)
            except ValueError:
                return jsonify({"error": "end_date must be YYYY-MM-DD"}), 400
    elif months:
        try:
            m = min(36, max(1, int(months)))
        except ValueError:
            return jsonify({"error": "months must be an integer"}), 400
        today = date.today()
        current_month_start = today.replace(day=1)
        y = current_month_start.year
        mm = current_month_start.month - (m - 1)
        while mm <= 0:
            y -= 1
            mm += 12
        start_date = date(y, mm, 1)
        if current_month_start.month == 12:
            end_date = date(current_month_start.year + 1, 1, 1)
        else:
            end_date = date(current_month_start.year, current_month_start.month + 1, 1)
    elif start_month:
        try:
            y, m = start_month.split("-")
            start_date = date(int(y), int(m), 1)
        except Exception:
            return jsonify({"error": "start_month must be YYYY-MM"}), 400
        if end_month:
            try:
                y2, m2 = end_month.split("-")
                end_base = date(int(y2), int(m2), 1)
                if end_base.month == 12:
                    end_date = date(end_base.year + 1, 1, 1)
                else:
                    end_date = date(end_base.year, end_base.month + 1, 1)
            except Exception:
                return jsonify({"error": "end_month must be YYYY-MM"}), 400

    data = _crm_service().rankings(
        org_id,
        entity=entity,
        direction=direction,
        limit=limit,
        start_date=start_date,
        end_date=end_date,
    )
    return jsonify({"rankings": data}), 200


@api_bp.route("/api/crm/analytics/churn-risk", methods=["GET"])
@requires_auth
def churn_risk():
    org_id = UUID(g.org_id)
    data = _crm_service().churn_risk(org_id)
    return jsonify({"churn_risk": data}), 200


@api_bp.route("/api/crm/overview", methods=["GET"])
@requires_auth
def crm_overview():
    org_id = UUID(g.org_id)
    return jsonify(_crm_service().get_overview(org_id)), 200


@api_bp.route("/api/crm/traceability-config", methods=["GET"])
@requires_auth
def get_traceability_config():
    org_id = UUID(g.org_id)
    return jsonify(_crm_service().get_traceability_config(org_id)), 200


@api_bp.route("/api/crm/traceability-config", methods=["PUT"])
@requires_auth
def update_traceability_config():
    org_id = UUID(g.org_id)
    data = request.get_json() or {}
    try:
        updated = _crm_service().update_traceability_config(org_id, data)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    log_action("update", "crm_traceability_config", None, {"matching_strategy": updated.get("matching_strategy")})
    return jsonify(updated), 200


# ------------------------------------------------------------------
# Product Mappings
# ------------------------------------------------------------------


@api_bp.route("/api/crm/product-mappings", methods=["GET"])
@requires_auth
def list_mappings():
    org_id = UUID(g.org_id)
    mappings = _crm_service().list_mappings(org_id)
    return jsonify({"product_mappings": mappings}), 200


@api_bp.route("/api/crm/final-products", methods=["GET"])
@requires_auth
def list_final_products():
    org_id = UUID(g.org_id)
    rows = _crm_service().list_final_products(org_id)
    return jsonify({"final_products": rows}), 200


@api_bp.route("/api/crm/product-mappings", methods=["POST"])
@requires_auth
def create_mapping():
    org_id = UUID(g.org_id)
    data = request.get_json() or {}
    if not data.get("biz_e_product_name") or not data.get("xero_description_pattern"):
        return jsonify({"error": "biz_e_product_name and xero_description_pattern are required"}), 400
    if data.get("biz_e_source_output_id"):
        try:
            UUID(data["biz_e_source_output_id"])
        except Exception:
            return jsonify({"error": "biz_e_source_output_id must be a valid UUID"}), 400

    try:
        mapping = _crm_service().create_mapping(org_id, data, UUID(g.user_id) if g.user_id else None)
        log_action("create", "product_mapping", None, {"biz_e": data.get("biz_e_product_name")})
        return jsonify({"product_mapping": mapping}), 201
    except Exception as e:
        if "unique" in str(e).lower():
            return jsonify({"error": "This mapping already exists"}), 409
        raise


@api_bp.route("/api/crm/product-mappings/<mapping_id>", methods=["PUT"])
@requires_auth
def update_mapping(mapping_id: str):
    org_id = UUID(g.org_id)
    data = request.get_json() or {}
    mapping = _crm_service().update_mapping(UUID(mapping_id), org_id, data)
    if not mapping:
        return jsonify({"error": "Mapping not found"}), 404
    log_action("update", "product_mapping", UUID(mapping_id))
    return jsonify({"product_mapping": mapping}), 200


@api_bp.route("/api/crm/product-mappings/<mapping_id>", methods=["DELETE"])
@requires_auth
def delete_mapping(mapping_id: str):
    org_id = UUID(g.org_id)
    ok = _crm_service().delete_mapping(UUID(mapping_id), org_id)
    if not ok:
        return jsonify({"error": "Mapping not found"}), 404
    log_action("delete", "product_mapping", UUID(mapping_id))
    return jsonify({"ok": True}), 200
