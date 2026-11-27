"""CRM JSON API routes — customers, invoices, notes, tasks, analytics, product mappings."""

from datetime import date, timedelta
from io import BytesIO
from uuid import UUID

import requests
from flask import Blueprint, Response, abort, g, jsonify, request, send_file
from urllib3.exceptions import HTTPError as Urllib3HTTPError
from xero_python.exceptions import OpenApiException

from app.core.backend.tasks import (
    TaskError,
    assign_task_to_lane,
    create_lane,
    delete_lane,
    list_lanes,
    reorder_lanes,
    update_lane,
)
from app.core.db import db_session
from app.core.security.access_policy import has_permission
from app.core.security.permissions import requires_auth, requires_permission
from app.features.crm.models.sales_fifo_allocation import SalesFifoAllocation
from app.features.crm.models.xero_invoice import XeroInvoice
from app.features.crm.routes.crm_payloads import (
    AssignLaneInput,
    AssignMatchingLineInput,
    BulkMappingsInput,
    ContactImportInput,
    ContactSyncInput,
    ContactSyncSettingsInput,
    CreateMappingInput,
    CreateTaskInput,
    LineRefInput,
    NoReturnNoteInput,
    NoteInput,
    ReorderLanesInput,
    ServicePayload,
    TraceabilitySettingsInput,
    UpdateMappingInput,
    UpdateTaskInput,
)
from app.features.crm.services.crm_service import CRMService
from app.features.crm.services.xero_api_client import XeroInsufficientScopeError, _extract_exception_error_message
from app.features.crm.services.xero_oauth_service import XeroTokenExpiredError
from app.observability import get_logger
from app.utils.request_validation import InvalidInputError, query_int, query_text, read_json

api_bp = Blueprint("crm_api", __name__)
logger = get_logger(__name__)


def _crm_service() -> CRMService:
    return CRMService(db_session())


def _uuid_or_none(raw: str | None) -> UUID | None:
    """The UUID in a request-supplied string, or None when it is not one (the caller answers 400)."""
    if not isinstance(raw, str):
        return None
    try:
        return UUID(raw)
    except ValueError:
        return None


def _page_args(default_page_size: int) -> tuple[int, int]:
    page = query_int("page", default=1, minimum=1, maximum=20_000_000)
    page_size = query_int("page_size", default=default_page_size, minimum=1, maximum=100)
    return page, page_size


@api_bp.errorhandler(InvalidInputError)
def invalid_crm_request(error):
    return error.response()


# ------------------------------------------------------------------
# Customers
# ------------------------------------------------------------------


@api_bp.route("/api/crm/customers/import-template", methods=["GET"])
@requires_auth
def customer_import_template():
    from app.features.crm.services.contact_import import template

    return Response(
        template(),
        mimetype="text/csv",
        headers={"Content-Disposition": 'attachment; filename="crm-customers-template.csv"'},
    )


@api_bp.route("/api/crm/customers/import", methods=["POST"])
@requires_auth
@requires_permission("sales.record")
def customer_import():
    from app.features.crm.services.contact_import import import_contacts

    if request.content_length and request.content_length > 1_200_000:
        return jsonify({"error": "Import text must be at most 1 MB"}), 413
    data = read_json(ContactImportInput)
    try:
        result = import_contacts(
            db_session(),
            UUID(g.org_id),
            data.text,
            data.format,
            commit=data.commit,
            actor_id=_actor(),
        )
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    return jsonify(result), 200


@api_bp.route("/api/crm/customers", methods=["GET"])
@requires_auth
def list_customers():
    org_id = UUID(g.org_id)
    search = query_text("q") or None
    status = request.args.get("status") or None
    sort_by = request.args.get("sort_by", "name")
    sort_dir = request.args.get("sort_dir", "asc")
    page, page_size = _page_args(50)

    result = _crm_service().list_customers(
        org_id=org_id,
        search=search,
        status=status,
        sort_by=sort_by,
        sort_dir=sort_dir,
        page=page,
        page_size=page_size,
        missing_contact=request.args.get("missing_contact") == "1",
    )
    return jsonify(result), 200


@api_bp.route("/api/crm/customers/<contact_id>", methods=["GET"])
@requires_auth
def get_customer(contact_id: str):
    org_id = UUID(g.org_id)
    contact_uuid = _uuid_or_none(contact_id)
    if contact_uuid is None:
        return jsonify({"error": "Invalid customer ID"}), 400
    result = _crm_service().get_customer(contact_uuid, org_id)
    if not result:
        return jsonify({"error": "Customer not found"}), 404
    return jsonify(result), 200


# What a call to Xero raises when Xero refuses it or cannot be reached (RuntimeError is
# XeroAPIClient's own "no usable reply"). Anything else is a Biz-E bug and stays a 500.
_XERO_CALL_ERRORS = (OpenApiException, requests.RequestException, Urllib3HTTPError, ConnectionError, RuntimeError)


def _xero_failure(exc: Exception, action: str):
    """The answer for a Xero call that failed, in words the page can show."""
    if isinstance(exc, XeroInsufficientScopeError):
        return jsonify({"error": "xero_insufficient_scope", "message": str(exc), "action": "reconnect_xero"}), 401
    if isinstance(exc, XeroTokenExpiredError):
        return jsonify(
            {
                "error": "The Xero connection has expired. Reconnect Xero, then try again.",
                "code": "reconnect_required",
                "action": "reconnect_xero",
            }
        ), 401
    if isinstance(exc, ValueError):
        return jsonify({"error": str(exc)}), 400
    if not isinstance(exc, _XERO_CALL_ERRORS):
        raise exc
    refused = _extract_exception_error_message(exc)
    if refused:
        logger.warning("crm_xero_call_refused", action=action, org_id=g.org_id, error=refused)
        return jsonify({"error": f"Xero refused this: {refused}"}), 400
    logger.exception("crm_xero_call_failed", action=action, org_id=g.org_id)
    return jsonify({"error": "Xero could not be reached. Try again in a moment."}), 502


def _contact_sync():
    from app.features.crm.services.contact_service import ContactSyncService

    return ContactSyncService(db_session())


def _actor() -> UUID | None:
    return UUID(g.user_id) if getattr(g, "user_id", None) else None


def _contact_response(contact, xero_state: dict, status: int = 200, **extra):
    from app.features.crm.services.crm_service import _serialise_contact

    return jsonify({"customer": _serialise_contact(contact), "xero_sync": xero_state, **extra}), status


@api_bp.route("/api/crm/customers", methods=["POST"])
@requires_auth
def create_customer():
    """Create a contact in Biz-E. It goes to Xero now if its sync (or the Sales default) is on."""
    data = read_json(ServicePayload).model_dump()
    try:
        contact, state = _contact_sync().create_contact(UUID(g.org_id), data, actor_id=_actor())
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    return _contact_response(contact, state, 201)


@api_bp.route("/api/crm/customers/<contact_id>", methods=["PATCH"])
@requires_auth
def update_customer(contact_id: str):
    """Save edited contact details; a contact that syncs sends the changed ones to Xero."""
    from app.features.crm.services.contact_service import ContactNotFoundError

    contact_uuid = _uuid_or_none(contact_id)
    if contact_uuid is None:
        return jsonify({"error": "Invalid customer ID"}), 400
    data = read_json(ServicePayload).model_dump()
    try:
        contact, state, changed = _contact_sync().update_contact(UUID(g.org_id), contact_uuid, data, actor_id=_actor())
    except ContactNotFoundError:
        return jsonify({"error": "Customer not found"}), 404
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    return _contact_response(contact, state, changed=sorted(changed))


@api_bp.route("/api/crm/customers/<contact_id>/xero-sync", methods=["PUT"])
@requires_auth
def set_customer_xero_sync(contact_id: str):
    """A Biz-E contact's own Xero sync: true, false, or null to follow the Sales default."""
    from app.features.crm.services.contact_service import ContactNotFoundError

    contact_uuid = _uuid_or_none(contact_id)
    if contact_uuid is None:
        raise InvalidInputError({"contact_id": "Enter a valid contact ID."})
    data = read_json(ContactSyncInput)
    try:
        contact, state = _contact_sync().set_contact_sync(
            UUID(g.org_id), contact_uuid, data.sync_to_xero, actor_id=_actor()
        )
    except ContactNotFoundError:
        return jsonify({"error": "Customer not found"}), 404
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    return _contact_response(contact, state)


@api_bp.route("/api/crm/customers/<contact_id>/xero-sync/retry", methods=["POST"])
@requires_auth
def retry_customer_xero_sync(contact_id: str):
    from app.features.crm.services.contact_service import ContactNotFoundError

    contact_uuid = _uuid_or_none(contact_id)
    if contact_uuid is None:
        return jsonify({"error": "Invalid customer ID"}), 400
    try:
        contact, state = _contact_sync().retry(UUID(g.org_id), contact_uuid, actor_id=_actor())
    except ContactNotFoundError:
        return jsonify({"error": "Customer not found"}), 404
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    return _contact_response(contact, state)


@api_bp.route("/api/crm/contact-sync-settings", methods=["GET"])
@requires_auth
def get_contact_sync_settings():
    return jsonify(_contact_sync().settings(UUID(g.org_id))), 200


@api_bp.route("/api/crm/contact-sync-settings", methods=["PUT"])
@requires_auth
def update_contact_sync_settings():
    """The Sales default for contacts created in Biz-E. Turning it on sends those not yet in Xero."""
    data = read_json(ContactSyncSettingsInput)
    result = _contact_sync().set_sync_default(UUID(g.org_id), data.sync_contacts_to_xero, actor_id=_actor())
    return jsonify(result), 200


# ------------------------------------------------------------------
# Invoices
# ------------------------------------------------------------------


@api_bp.route("/api/crm/customers/<contact_id>/invoices", methods=["GET"])
@requires_auth
def get_customer_invoices(contact_id: str):
    org_id = UUID(g.org_id)
    contact_uuid = _uuid_or_none(contact_id)
    if contact_uuid is None:
        return jsonify({"error": "Invalid customer ID"}), 400
    page, page_size = _page_args(25)
    result = _crm_service().get_customer_invoices(contact_uuid, org_id, page=page, page_size=page_size)
    return jsonify(result), 200


@api_bp.route("/api/crm/invoices", methods=["GET"])
@requires_auth
def get_org_invoices():
    org_id = UUID(g.org_id)
    kind = (request.args.get("kind") or "all").strip().lower()
    if kind not in {"all", "this_month", "outstanding"}:
        return jsonify({"error": "kind must be all, this_month or outstanding"}), 400
    page, page_size = _page_args(50)
    result = _crm_service().get_org_invoices(org_id, kind=kind, page=page, page_size=page_size)
    return jsonify(result), 200


@api_bp.route("/api/crm/returns/pending", methods=["GET"])
@requires_auth
def list_pending_returns():
    """Mapped credit-note lines that still need a physical-return decision."""
    from app.features.crm.services.credit_note_returns import pending

    page, page_size = _page_args(25)
    return jsonify(pending(db_session(), UUID(g.org_id), page=page, page_size=page_size)), 200


@api_bp.route("/api/crm/credit-notes/<credit_note_id>/lines/<line_id>/no-return", methods=["POST"])
@requires_auth
def record_credit_note_line_no_return(credit_note_id: str, line_id: str):
    """Record, without touching inventory, that a credited product did not come back."""
    from app.features.crm.services.credit_note_returns import ReturnDecisionConflictError, record_no_return

    note_uuid = _uuid_or_none(credit_note_id)
    line_uuid = _uuid_or_none(line_id)
    if note_uuid is None or line_uuid is None:
        return jsonify({"error": "Credit note line not found"}), 404
    note = read_json(NoReturnNoteInput).note
    try:
        record_no_return(db_session(), UUID(g.org_id), note_uuid, line_uuid, UUID(g.user_id), note)
        db_session().commit()
        return jsonify({"ok": True, "decision": "no_return"}), 200
    except LookupError as e:
        db_session().rollback()
        return jsonify({"error": str(e)}), 404
    except ReturnDecisionConflictError as e:
        db_session().rollback()
        return jsonify({"error": str(e)}), 409
    except ValueError as e:
        db_session().rollback()
        return jsonify({"error": str(e)}), 400


@api_bp.route("/api/crm/returns", methods=["GET"])
@requires_auth
def list_customer_returns():
    """GL-P01b: goods customers sent back, newest first."""
    from app.features.crm.services.sales_returns import recent, serialise

    contact_id = None
    if request.args.get("contact_id"):
        contact_id = _uuid_or_none(request.args.get("contact_id"))
        if contact_id is None:
            return jsonify({"returns": []}), 200
    rows = recent(db_session(), UUID(g.org_id), contact_id=contact_id)
    return jsonify({"returns": [serialise(r) for r in rows]}), 200


@api_bp.route("/api/crm/returns/places", methods=["GET"])
@requires_auth
def list_return_places():
    """GL-P01b: the stock areas a return can be received into, and whether each is in bond."""
    from app.core.db.models.site import Site
    from app.core.db.models.stock_location import StockLocation

    org_id = UUID(g.org_id)
    sites = {s.id: s.name for s in db_session().query(Site).filter(Site.org_id == org_id).all()}
    rows = (
        db_session()
        .query(StockLocation)
        .filter(StockLocation.org_id == org_id, StockLocation.is_active.is_(True))
        .order_by(StockLocation.name)
        .all()
    )
    places = [
        {
            "id": str(loc.id),
            "name": f"{sites[loc.site_id]} · {loc.name}" if len(sites) > 1 and loc.site_id in sites else loc.name,
            "in_bond": bool(loc.inside_licensed_area),
        }
        for loc in rows
    ]
    return jsonify({"places": places}), 200


@api_bp.route("/api/crm/invoices/<xero_invoice_id>/returnable", methods=["GET"])
@requires_auth
def list_returnable_sale_lines(xero_invoice_id: str):
    """GL-P01b: the sale lines on an invoice that goods could come back from."""
    from app.features.crm.services.sales_returns import returnable_sale_lines

    if not xero_invoice_id or len(xero_invoice_id) > 100:
        return jsonify({"lines": []}), 200
    return jsonify({"lines": returnable_sale_lines(db_session(), UUID(g.org_id), xero_invoice_id)}), 200


@api_bp.route("/api/crm/returns", methods=["POST"])
@requires_auth
def record_customer_return():
    """GL-P01b: record what physically came back. Only this moves stock; a credit note never does."""
    from datetime import date

    from app.features.crm.services.sales_returns import ReturnConflictError, ReturnError, record_return, serialise

    data = read_json(ServicePayload).model_dump()
    ids = {}
    for key, missing in (
        ("credit_note_line_id", "Credit note line not found"),
        ("allocation_id", "Sale line not found"),
        ("location_id", "Stock area not found"),
    ):
        ids[key] = None
        if data.get(key) not in (None, ""):
            ids[key] = _uuid_or_none(str(data.get(key)))
            if ids[key] is None:
                return jsonify({"error": missing}), 404
    try:
        received_on = date.fromisoformat(str(data.get("received_on") or date.today().isoformat()))
    except ValueError:
        return jsonify({"error": "Received date must be YYYY-MM-DD"}), 400
    session = db_session()
    try:
        ret = record_return(
            session,
            UUID(g.org_id),
            UUID(g.user_id),
            condition=str(data.get("condition") or ""),
            quantity=data.get("quantity"),
            received_on=received_on,
            note=data.get("note") if isinstance(data.get("note"), str) else None,
            credit_note_line_id=ids["credit_note_line_id"],
            allocation_id=ids["allocation_id"],
            location_id=ids["location_id"],
            product_name=data.get("product_name") if isinstance(data.get("product_name"), str) else None,
            unit=data.get("unit") if isinstance(data.get("unit"), str) else None,
        )
        session.commit()
    except LookupError as e:
        session.rollback()
        return jsonify({"error": str(e)}), 404
    except ReturnConflictError as e:
        session.rollback()
        return jsonify({"error": str(e)}), 409
    except ReturnError as e:
        session.rollback()
        return jsonify({"error": str(e)}), 400
    return jsonify({"return": serialise(ret)}), 201


@api_bp.route("/api/crm/invoices/<invoice_id>/trace-items", methods=["GET"])
@requires_auth
def get_invoice_trace_items(invoice_id: str):
    """Resolve every labelled stock lot allocated to one tenant's invoice."""
    if len(invoice_id) > 128:
        return jsonify({"error": "Invalid invoice ID"}), 400
    org_id = UUID(g.org_id)
    session = db_session()
    invoice = (
        session.query(XeroInvoice)
        .filter(XeroInvoice.org_id == org_id, XeroInvoice.xero_invoice_id == invoice_id)
        .first()
    )
    if invoice is None:
        return jsonify({"error": "Invoice not found"}), 404
    allocations = (
        session.query(SalesFifoAllocation.inventory_item_id)
        .filter(SalesFifoAllocation.org_id == org_id, SalesFifoAllocation.xero_invoice_id == invoice_id)
        .distinct()
        .all()
    )
    return jsonify(
        {
            "invoice_number": invoice.invoice_number or invoice.xero_invoice_id,
            "inventory_item_ids": sorted(str(row.inventory_item_id) for row in allocations),
        }
    ), 200


@api_bp.route("/api/crm/customers/<contact_id>/line-item-descriptions", methods=["GET"])
@requires_auth
def get_customer_line_item_descriptions(contact_id: str):
    org_id = UUID(g.org_id)
    contact_uuid = _uuid_or_none(contact_id)
    if contact_uuid is None:
        return jsonify({"error": "Invalid customer ID"}), 400
    options = _crm_service().get_customer_line_item_options(contact_uuid, org_id)
    return jsonify({"line_item_options": options}), 200


@api_bp.route("/api/crm/customers/<contact_id>/line-item-pricing", methods=["GET"])
@requires_auth
def get_customer_line_item_pricing(contact_id: str):
    org_id = UUID(g.org_id)
    contact_uuid = _uuid_or_none(contact_id)
    if contact_uuid is None:
        return jsonify({"error": "Invalid customer ID"}), 400
    description = (request.args.get("description") or "").strip() or None
    item_code = (request.args.get("item_code") or "").strip() or None
    pricing = _crm_service().get_customer_line_item_pricing(
        contact_uuid,
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
        due_date = _crm_service().suggest_invoice_due_date(
            UUID(contact_id), org_id, invoice_date, fetch_from_xero=getattr(g, "auth_via", None) != "mcp"
        )
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
    data = read_json(ServicePayload).model_dump()
    try:
        invoice = _crm_service().create_customer_invoice(UUID(contact_id), org_id, data)
    except Exception as e:  # noqa: BLE001 - every Xero failure gets an answer the page can show
        return _xero_failure(e, "create_invoice")
    return jsonify({"invoice": invoice}), 201


@api_bp.route("/api/crm/invoices/<invoice_id>/authorise", methods=["POST"])
@requires_auth
def authorise_invoice(invoice_id: str):
    org_id = UUID(g.org_id)
    try:
        invoice = _crm_service().authorise_invoice(UUID(invoice_id), org_id)
    except Exception as e:  # noqa: BLE001 - every Xero failure gets an answer the page can show
        return _xero_failure(e, "authorise_invoice")
    return jsonify({"invoice": invoice}), 200


@api_bp.route("/api/crm/invoices/<invoice_id>/pdf", methods=["GET"])
@requires_auth
def get_invoice_pdf(invoice_id: str):
    org_id = UUID(g.org_id)
    inline = str(request.args.get("inline") or "").strip().lower() in {"1", "true", "yes"}
    try:
        pdf_bytes, filename = _crm_service().get_invoice_pdf(UUID(invoice_id), org_id)
    except Exception as e:  # noqa: BLE001 - every Xero failure gets an answer the page can show
        return _xero_failure(e, "invoice_pdf")
    return send_file(
        BytesIO(pdf_bytes),
        mimetype="application/pdf",
        as_attachment=not inline,
        download_name=filename or "invoice.pdf",
    )


@api_bp.route("/api/crm/invoices/<invoice_id>/view-url", methods=["GET"])
@requires_auth
def get_invoice_view_url(invoice_id: str):
    org_id = UUID(g.org_id)
    try:
        view_url = _crm_service().get_invoice_view_url(UUID(invoice_id), org_id)
    except Exception as e:  # noqa: BLE001 - every Xero failure gets an answer the page can show
        return _xero_failure(e, "invoice_view_url")
    return jsonify({"view_url": view_url}), 200


@api_bp.route("/api/crm/customers/<contact_id>/analytics", methods=["GET"])
@requires_auth
def get_customer_analytics(contact_id: str):
    org_id = UUID(g.org_id)
    try:
        contact_uuid = UUID(contact_id)
    except ValueError:
        return jsonify({"error": "Invalid customer ID"}), 400
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
        contact_uuid,
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
    content = read_json(NoteInput).content

    svc = _crm_service()
    try:
        note = svc.create_note(org_id, UUID(contact_id), content, UUID(g.user_id) if g.user_id else None)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    return jsonify({"note": note}), 201


@api_bp.route("/api/crm/notes/<note_id>", methods=["PUT"])
@requires_auth
def update_note(note_id: str):
    org_id = UUID(g.org_id)
    content = read_json(NoteInput).content

    note_uuid = _uuid_or_none(note_id)
    if note_uuid is None:
        return jsonify({"error": "Invalid note ID"}), 400
    note = _crm_service().update_note(note_uuid, org_id, content)
    if not note:
        return jsonify({"error": "Note not found"}), 404
    return jsonify({"note": note}), 200


@api_bp.route("/api/crm/notes/<note_id>", methods=["DELETE"])
@requires_auth
def delete_note(note_id: str):
    org_id = UUID(g.org_id)
    note_uuid = _uuid_or_none(note_id)
    if note_uuid is None:
        return jsonify({"error": "Invalid note ID"}), 400
    ok = _crm_service().delete_note(note_uuid, org_id)
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
    contact_uuid = _uuid_or_none(contact_id) if contact_id else None
    if contact_id and contact_uuid is None:
        return jsonify({"error": "contact_id must be a UUID"}), 400
    assigned_uuid = _uuid_or_none(assigned_to) if assigned_to else None
    if assigned_to and assigned_uuid is None:
        return jsonify({"error": "assigned_to must be a UUID"}), 400

    tasks = _crm_service().list_tasks(
        org_id=org_id,
        contact_id=contact_uuid,
        status=status or None,
        assigned_to=assigned_uuid,
    )
    return jsonify({"tasks": tasks}), 200


@api_bp.route("/api/crm/tasks", methods=["POST"])
@requires_auth
def create_task():
    org_id = UUID(g.org_id)
    data = read_json(CreateTaskInput).model_dump(mode="json", exclude_unset=True)
    if data.get("task_type") == "tasting":
        from app.features.compliant.service import nz_alcohol_active
        from app.features.tastings.routes.tasting_routes import _write
        from app.features.tastings.services import tasting_service

        if not nz_alcohol_active(db_session(), org_id):
            abort(404)
        if set(data) != {"task_type", "tasting"}:
            return jsonify(error="Supply tasting details with the task type"), 400
        try:
            response = _write(tasting_service.save_event, data["tasting"])
        except tasting_service.TastingError as exc:
            db_session().rollback()
            return jsonify(error=str(exc)), exc.status
        event = response.get_json()["tasting"]
        from app.features.crm.services.crm_service import _serialise_task

        row = _crm_service().task_repo.get_by_id(UUID(event["task_id"]), org_id)
        return jsonify(task=_serialise_task(row, db=db_session()), tasting=event), 201
    if not data.get("title"):
        raise InvalidInputError({"title": "Enter a task title."})

    try:
        task = _crm_service().create_task(org_id, data, UUID(g.user_id) if g.user_id else None)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    return jsonify({"task": task}), 201


@api_bp.route("/api/crm/tasks/<task_id>", methods=["GET"])
@requires_auth
def get_task(task_id: str):
    from app.features.crm.models.crm_task import CRMTask
    from app.features.crm.repositories.crm_task_repo import visible_task_filter
    from app.features.crm.services.crm_service import _serialise_task

    task_uuid = _uuid_or_none(task_id)
    if task_uuid is None:
        return jsonify(error="Invalid task ID"), 400
    db = db_session()
    task = (
        db.query(CRMTask)
        .filter(CRMTask.org_id == g.current_org_id, CRMTask.id == task_uuid, visible_task_filter(db, g.current_org_id))
        .first()
    )
    if task is None:
        abort(404)
    return jsonify(task=_serialise_task(task, db=db))


@api_bp.route("/api/crm/tasks/<task_id>", methods=["PUT"])
@requires_auth
def update_task(task_id: str):
    org_id = UUID(g.org_id)
    data = read_json(UpdateTaskInput).model_dump(mode="json", exclude_unset=True)
    if "title" in data and data["title"] is None:
        raise InvalidInputError({"title": "This field cannot be null."})
    try:
        task = _crm_service().update_task(UUID(task_id), org_id, data)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    if not task:
        return jsonify({"error": "Task not found"}), 404
    return jsonify({"task": task}), 200


@api_bp.route("/api/crm/tasks/<task_id>", methods=["DELETE"])
@requires_auth
def delete_task(task_id: str):
    org_id = UUID(g.org_id)
    task_uuid = _uuid_or_none(task_id)
    if task_uuid is None:
        return jsonify({"error": "Invalid task ID"}), 400
    try:
        ok = _crm_service().delete_task(task_uuid, org_id)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 409
    if not ok:
        return jsonify({"error": "Task not found"}), 404
    return jsonify({"ok": True}), 200


# ------------------------------------------------------------------
# Durable CRM board lanes
# ------------------------------------------------------------------


@api_bp.route("/api/crm/tasks/lanes", methods=["GET"])
@requires_auth
def list_task_lanes():
    return jsonify({"lanes": list_lanes(db_session(), UUID(g.org_id), "crm")}), 200


@api_bp.route("/api/crm/tasks/lanes", methods=["POST"])
@requires_auth
def create_task_lane():
    data = read_json(ServicePayload).model_dump()
    try:
        lane = create_lane(
            db_session(),
            UUID(g.org_id),
            "crm",
            UUID(g.user_id) if g.user_id else None,
            data,
        )
        return jsonify({"lane": lane}), 201
    except TaskError as exc:
        return jsonify({"error": str(exc)}), 400


@api_bp.route("/api/crm/tasks/lanes/<lane_id>", methods=["PUT"])
@requires_auth
def update_task_lane(lane_id: str):
    data = read_json(ServicePayload).model_dump()
    try:
        lane = update_lane(db_session(), UUID(g.org_id), "crm", UUID(lane_id), data)
        if lane is None:
            return jsonify({"error": "Lane not found"}), 404
        return jsonify({"lane": lane}), 200
    except (TaskError, ValueError) as exc:
        return jsonify({"error": str(exc)}), 400


@api_bp.route("/api/crm/tasks/lanes/order", methods=["PUT"])
@requires_auth
def reorder_task_lanes():
    data = read_json(ReorderLanesInput)
    try:
        lanes = reorder_lanes(db_session(), UUID(g.org_id), "crm", data.lane_ids)
        return jsonify({"lanes": lanes}), 200
    except (TaskError, ValueError, TypeError) as exc:
        return jsonify({"error": str(exc)}), 400


@api_bp.route("/api/crm/tasks/lanes/<lane_id>", methods=["DELETE"])
@requires_auth
def delete_task_lane(lane_id: str):
    try:
        if not delete_lane(db_session(), UUID(g.org_id), "crm", UUID(lane_id)):
            return jsonify({"error": "Lane not found"}), 404
        return jsonify({"ok": True}), 200
    except ValueError:
        return jsonify({"error": "lane_id must be a UUID"}), 400


@api_bp.route("/api/crm/tasks/<task_id>/lane", methods=["PUT"])
@requires_auth
def assign_task_lane(task_id: str):
    data = read_json(AssignLaneInput)
    try:
        lane_id = data.lane_id if isinstance(data.lane_id, UUID) else None
        task = assign_task_to_lane(db_session(), UUID(g.org_id), "crm", UUID(task_id), lane_id)
        if task is None:
            return jsonify({"error": "Task not found"}), 404
        return jsonify({"task": task}), 200
    except (TaskError, ValueError, TypeError) as exc:
        return jsonify({"error": str(exc)}), 400


# ------------------------------------------------------------------
# Excise from sales (NZ Alcohol orgs only)
# ------------------------------------------------------------------


def _excise_guard():
    from app.features.compliant.service import nz_alcohol_active

    if not nz_alcohol_active(db_session(), g.org_id):
        return jsonify({"error": "Not found"}), 404
    return None


@api_bp.route("/api/crm/excise/months", methods=["GET"])
@requires_auth
def excise_months():
    from app.features.compliant.modules.nz_alcohol import sales_excise

    if (denied := _excise_guard()) is not None:
        return denied
    org_id = UUID(g.org_id)
    return jsonify(
        {
            "months": sales_excise.months(db_session(), org_id),
            "sources": sales_excise._sources(db_session(), org_id),
            "rates_source": sales_excise.rates_source(),
        }
    ), 200


@api_bp.route("/api/crm/excise", methods=["GET"])
@requires_auth
def excise_month():
    from app.features.compliant.modules.nz_alcohol import sales_excise

    if (denied := _excise_guard()) is not None:
        return denied
    try:
        start = sales_excise.parse_month(request.args.get("month") or date.today().strftime("%Y-%m"))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    return jsonify({"report": sales_excise.month_report(db_session(), UUID(g.org_id), start)}), 200


# ------------------------------------------------------------------
# Analytics
# ------------------------------------------------------------------


@api_bp.route("/api/crm/analytics/monthly-sales", methods=["GET"])
@requires_auth
def monthly_sales():
    org_id = UUID(g.org_id)
    months = query_int("months", default=12, minimum=1, maximum=24)
    data = _crm_service().monthly_sales(org_id, months=months)
    return jsonify({"monthly_sales": data}), 200


@api_bp.route("/api/crm/analytics/customer-breakdown", methods=["GET"])
@requires_auth
def customer_breakdown():
    org_id = UUID(g.org_id)
    top_n = query_int("top_n", default=20, minimum=1, maximum=50)
    data = _crm_service().customer_breakdown(org_id, top_n=top_n)
    return jsonify({"customer_breakdown": data, "customers": data}), 200


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

    limit = query_int("limit", default=10, minimum=1, maximum=50)
    months = request.args.get("months")
    period_n = request.args.get("period_n")
    period_unit = query_text("period_unit", default="months", max_length=8).lower()
    if period_unit not in {"days", "weeks", "months", "years"}:
        raise InvalidInputError({"period_unit": "Choose days, weeks, months or years."})
    start_month = (request.args.get("start_month") or "").strip()
    end_month = (request.args.get("end_month") or "").strip()
    start_date_raw = (request.args.get("start_date") or "").strip()
    end_date_raw = (request.args.get("end_date") or "").strip()

    start_date = None
    end_date = None

    if period_n:
        n = query_int("period_n", default=12, minimum=1, maximum=3650)
        today = date.today()
        # Inclusive "last n <unit>" window ending today.
        end_date = today + timedelta(days=1)
        if period_unit == "days":
            start_date = today - timedelta(days=n - 1)
        elif period_unit == "weeks":
            start_date = today - timedelta(days=(n * 7) - 1)
        elif period_unit == "years":
            if n * 365 > today.toordinal():
                raise InvalidInputError({"period_n": "The period starts before the earliest date."})
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
            except (ValueError, OverflowError):
                return InvalidInputError({"end_date": "Enter a supported end date in YYYY-MM-DD format."}).response()
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


@api_bp.route("/api/crm/analytics/product-sales-by-store", methods=["GET"])
@requires_auth
def product_sales_by_store():
    """Mapped product units by customer/store for an inclusive invoice-date window."""
    try:
        start_date = date.fromisoformat(request.args["start_date"])
        end_inclusive = date.fromisoformat(request.args["end_date"])
        end_date = end_inclusive + timedelta(days=1)
    except (KeyError, ValueError, OverflowError):
        return jsonify({"error": "start_date and end_date must be YYYY-MM-DD"}), 400
    if start_date > end_inclusive:
        return jsonify({"error": "start_date must be on or before end_date"}), 400
    data = _crm_service().product_sales_by_store(UUID(g.org_id), start_date, end_date)
    return jsonify(data), 200


@api_bp.route("/api/crm/analytics/churn-risk", methods=["GET"])
@requires_auth
def churn_risk():
    org_id = UUID(g.org_id)
    data = _crm_service().churn_risk(org_id)
    return jsonify({"churn_risk": data, "customers": data}), 200


@api_bp.route("/api/crm/analytics/customer-contact", methods=["GET"])
@requires_auth
def customer_contact():
    return jsonify(_crm_service().customer_contact(UUID(g.org_id))), 200


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
    from app.features.crm.services.crm_service import MatchingModeChangeError

    org_id = UUID(g.org_id)
    data = read_json(TraceabilitySettingsInput).model_dump(mode="json", exclude_unset=True)
    # SALES-PERM: the matching mode decides whether waiting sales take stock. Switching it
    # (say manual -> fifo) makes the next sync consume the whole waiting backlog, the same
    # effect as /matching/run, so changing it needs inventory.adjust beside sales.manage. The
    # service checks it under a lock, in the transaction that writes (no read-then-write race).
    may_change_mode = has_permission(getattr(g, "current_user", None), "inventory.adjust")
    try:
        updated = _crm_service().update_traceability_config(org_id, data, may_change_mode=may_change_mode)
    except MatchingModeChangeError:
        db_session.rollback()
        logger.warning("access_denied", reason="matching_mode_needs_inventory_adjust", path=request.path)
        return jsonify(
            {
                "error": "Changing how sales are matched changes stock, so it needs permission to adjust stock.",
                "code": "permission_denied",
            }
        ), 403
    except ValueError as e:
        db_session.rollback()
        return jsonify({"error": str(e)}), 400
    return jsonify(updated), 200


# ------------------------------------------------------------------
# Sales-to-batch matching (plan 1.1): hybrid review and manual assignment
# ------------------------------------------------------------------


def _traceability():
    from app.features.crm.services.sales_traceability_service import SalesTraceabilityService

    return SalesTraceabilityService(db_session)


@api_bp.route("/api/crm/matching", methods=["GET"])
@requires_auth
def get_matching_queue():
    return jsonify(_traceability().review_queue(UUID(g.org_id))), 200


@api_bp.route("/api/crm/matching/candidates", methods=["GET"])
@requires_auth
def get_matching_candidates():
    product = (request.args.get("product") or "").strip()
    if not product:
        return jsonify({"error": "product is required"}), 400
    try:
        batches = _traceability().lot_candidates(UUID(g.org_id), product, site_id=request.args.get("site_id"))
    except ValueError as error:
        db_session.rollback()
        return jsonify({"error": str(error)}), 400
    return jsonify({"batches": batches}), 200


def _line_ref(data):
    invoice_id = str(data.get("invoice_id") or "").strip()
    line_key = str(data.get("line_key") or "").strip()
    if not invoice_id or not line_key:
        raise ValueError("invoice_id and line_key are required")
    return invoice_id, line_key


@api_bp.route("/api/crm/matching/confirm", methods=["POST"])
@requires_auth
def confirm_matching_line():
    data = read_json(LineRefInput)
    try:
        invoice_id, line_key = data.invoice_id, data.line_key
        count = _traceability().confirm_line(UUID(g.org_id), invoice_id, line_key)
        db_session.commit()
    except ValueError as e:
        db_session.rollback()
        return jsonify({"error": str(e)}), 400
    return jsonify({"confirmed": count}), 200


# /assign and /run decrement (or put back) finished-product stock, which the policy reserves for
# inventory.adjust; the table can't ask for that beside sales.record, so the routes do.
@api_bp.route("/api/crm/matching/assign", methods=["POST"])
@requires_auth
@requires_permission("inventory.adjust")
def assign_matching_line():
    data = read_json(AssignMatchingLineInput).model_dump(mode="json", exclude_unset=True)
    try:
        invoice_id, line_key = _line_ref(data)
        created = _traceability().assign_line(
            UUID(g.org_id), invoice_id, line_key, data.get("picks") or [], site_id=data.get("site_id")
        )
        db_session.commit()
    except ValueError as e:
        db_session.rollback()
        return jsonify({"error": str(e)}), 400
    return jsonify({"assigned": len(created), "presold": any(a.presold for a in created)}), 200


@api_bp.route("/api/crm/matching/run", methods=["POST"])
@requires_auth
@requires_permission("inventory.adjust")
def run_matching():
    """Re-run matching now (e.g. after changing the matching mode)."""
    try:
        summary = _traceability().reconcile_org(UUID(g.org_id))
        db_session.commit()
    except Exception:
        db_session.rollback()
        logger.exception("sales_matching_run_failed", org_id=g.org_id)
        return jsonify({"error": "Matching failed"}), 500
    return jsonify({"summary": summary}), 200


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
    data = read_json(CreateMappingInput).model_dump(mode="json", exclude_unset=True)

    try:
        mapping = _crm_service().create_mapping(org_id, data, UUID(g.user_id) if g.user_id else None)
        return jsonify({"product_mapping": mapping}), 201
    except ValueError as e:
        if "already exists" in str(e).lower():
            return jsonify({"error": "This mapping already exists"}), 409
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        if "unique" in str(e).lower():
            return jsonify({"error": "This mapping already exists"}), 409
        try:
            db_session().rollback()
        except Exception:
            pass
        raise


@api_bp.route("/api/crm/product-mappings/bulk", methods=["POST"])
@requires_auth
def create_mappings_bulk():
    org_id = UUID(g.org_id)
    data = read_json(BulkMappingsInput).model_dump(mode="json", exclude_unset=True)
    try:
        mappings = _crm_service().create_mappings(org_id, data.get("mappings"), UUID(g.user_id) if g.user_id else None)
        return jsonify({"product_mappings": mappings}), 201
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception:
        try:
            db_session().rollback()
        except Exception:
            pass
        raise


@api_bp.route("/api/crm/product-mappings/<mapping_id>", methods=["PUT"])
@requires_auth
def update_mapping(mapping_id: str):
    org_id = UUID(g.org_id)
    data = read_json(UpdateMappingInput).model_dump(mode="json", exclude_unset=True)
    if "biz_e_product_name" in data and data["biz_e_product_name"] is None:
        raise InvalidInputError({"biz_e_product_name": "This field cannot be null."})
    if "xero_description_pattern" in data and data["xero_description_pattern"] is None:
        raise InvalidInputError({"xero_description_pattern": "This field cannot be null."})
    mapping_uuid = _uuid_or_none(mapping_id)
    if mapping_uuid is None:
        return jsonify({"error": "Invalid mapping ID"}), 400
    try:
        mapping = _crm_service().update_mapping(mapping_uuid, org_id, data)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    if not mapping:
        return jsonify({"error": "Mapping not found"}), 404
    return jsonify({"product_mapping": mapping}), 200


@api_bp.route("/api/crm/product-mappings/<mapping_id>", methods=["DELETE"])
@requires_auth
def delete_mapping(mapping_id: str):
    org_id = UUID(g.org_id)
    mapping_uuid = _uuid_or_none(mapping_id)
    if mapping_uuid is None:
        return jsonify({"error": "Invalid mapping ID"}), 400
    ok = _crm_service().delete_mapping(mapping_uuid, org_id)
    if not ok:
        return jsonify({"error": "Mapping not found"}), 404
    return jsonify({"ok": True}), 200
