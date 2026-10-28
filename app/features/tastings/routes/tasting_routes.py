"""NZ Alcohol tasting HTTP boundary; normal session and CSRF middleware applies."""

from datetime import date, datetime, time, timedelta

import structlog
from flask import Blueprint, abort, g, jsonify, redirect, request
from sqlalchemy.exc import IntegrityError

from app.core.db import db_session
from app.core.db.models.inventory_item import InventoryItem
from app.core.db.models.user import User
from app.core.security.access_policy import has_permission
from app.core.security.permissions import requires_auth
from app.features.compliant.service import nz_alcohol_active
from app.features.crm.models.xero_contact import XeroContact
from app.features.tastings.repositories.tasting_repo import TastingRepository
from app.features.tastings.services import tasting_service as service

logger = structlog.get_logger(__name__)

bp = Blueprint("tastings", __name__, template_folder="../frontend/templates")


@bp.before_request
def require_subscription():
    if not nz_alcohol_active(db_session(), getattr(g, "current_org_id", None)):
        abort(404)


@bp.errorhandler(service.TastingError)
def invalid_request(error):
    db_session().rollback()
    logger.warning(
        "tastings_request_rejected",
        org_id=str(getattr(g, "current_org_id", "")),
        user_id=str(getattr(g, "user_id", "")),
        status=error.status,
        operation=request.endpoint,
    )
    return jsonify(error=str(error)), error.status


@bp.get("/crm/tastings")
@requires_auth
def home():
    event_id = request.args.get("tasting_id")
    if event_id:
        event = service.get_event(db_session(), g.current_org_id, event_id)
        return redirect("/crm/tasks?task_id=" + str(event.task_id))
    return redirect("/crm/tasks?type=tasting")


@bp.get("/api/crm/tastings")
@requires_auth
def list_tastings():
    try:
        start = date.fromisoformat(
            request.args.get("start", service.utc_now().astimezone(service.NZ).date().replace(day=1).isoformat())
        )
        end = date.fromisoformat(request.args["end"]) if "end" in request.args else start + timedelta(days=62)
    except (ValueError, TypeError):
        raise service.TastingError("Use ISO start/end dates") from None
    if not 0 < (end - start).days <= 93:
        raise service.TastingError("Choose a period of at most 93 days")
    rows = TastingRepository(db_session()).events(
        g.current_org_id, datetime.combine(start, time.min, service.NZ), datetime.combine(end, time.min, service.NZ)
    )
    names = {
        row.id: ((" ".join(filter(None, [row.first_name, row.last_name]))) or row.email)
        for row in db_session()
        .query(User)
        .filter(User.org_id == g.current_org_id, User.id.in_([event.rep_id for event in rows[:200]]))
    }
    return jsonify(
        tastings=[
            {**service.event_dict(db_session(), row, detail=False), "rep_name": names.get(row.rep_id)}
            for row in rows[:200]
        ],
        truncated=len(rows) > 200,
    )


def _offset(name="offset"):
    try:
        value = int(request.args.get(name, "0"))
    except ValueError:
        raise service.TastingError("Offset must be a nonnegative integer") from None
    if not 0 <= value <= 100000:
        raise service.TastingError("Offset must be between zero and 100000")
    return value


@bp.get("/api/crm/tastings/choices")
@requires_auth
def choices():
    db = db_session()
    org_id = g.current_org_id
    term = request.args.get("q", "").strip()
    if len(term) > 100:
        raise service.TastingError("Search is too long")
    # Escape LIKE metacharacters: this is a literal bounded search, not a wildcard API.
    match = "%" + term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
    offset = _offset()
    people_offset = _offset("people_offset")
    people_term = request.args.get("people_q", "").strip()
    if len(people_term) > 100:
        raise service.TastingError("People search is too long")
    people_match = "%" + people_term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
    from sqlalchemy import or_

    reps = (
        db.query(User)
        .filter(
            User.org_id == org_id,
            User.is_active.is_(True),
            or_(
                User.email.ilike(people_match, escape="\\"),
                User.first_name.ilike(people_match, escape="\\"),
                User.last_name.ilike(people_match, escape="\\"),
            ),
        )
        .order_by(User.email)
        .offset(people_offset)
        .limit(51)
        .all()
    )
    contacts = (
        db.query(XeroContact)
        .filter(XeroContact.org_id == org_id, XeroContact.name.ilike(people_match, escape="\\"))
        .order_by(XeroContact.name, XeroContact.id)
        .offset(people_offset)
        .limit(51)
        .all()
    )
    # SQL NULL extra_data is valid producer stock too; source eligibility is rechecked
    # under lock on dispatch, including contract-order assignment and provenance.
    from sqlalchemy import exists, or_, select

    from app.core.db.models.execution_step import ExecutionStep
    from app.features.contract_manufacturing.models.orders import ContractOrderExecution

    query = db.query(InventoryItem).filter(
        InventoryItem.org_id == org_id,
        InventoryItem.inventory_type == "final_product",
        InventoryItem.quantity > 0,
        InventoryItem.contract_customer_id.is_(None),
        InventoryItem.transfer_receipt_id.is_(None),
        or_(InventoryItem.extra_data.is_(None), ~InventoryItem.extra_data.has_key("contract_customer_id")),
        ~InventoryItem.name.ilike("%library stock"),
        or_(InventoryItem.extra_data.is_(None), ~InventoryItem.extra_data.contains({"library_stock": True})),
        or_(
            InventoryItem.name.ilike(match, escape="\\"), InventoryItem.supplier_batch_number.ilike(match, escape="\\")
        ),
        or_(
            InventoryItem.source_execution_id.is_not(None),
            InventoryItem.source_execution_step_id.is_not(None),
            InventoryItem.extra_data.has_key("opening_stock"),
        ),
    )
    direct_order = exists(
        select(ContractOrderExecution.id).where(
            ContractOrderExecution.org_id == org_id,
            ContractOrderExecution.execution_id == InventoryItem.source_execution_id,
        )
    )
    step_order = exists(
        select(ContractOrderExecution.id)
        .join(
            ExecutionStep,
            (ExecutionStep.execution_id == ContractOrderExecution.execution_id)
            & (ExecutionStep.org_id == ContractOrderExecution.org_id),
        )
        .where(ContractOrderExecution.org_id == org_id, ExecutionStep.id == InventoryItem.source_execution_step_id)
    )
    query = query.filter(~direct_order, ~step_order)
    stock = query.order_by(InventoryItem.name, InventoryItem.id).offset(offset).limit(51).all()
    return jsonify(
        reps=[
            {"id": str(row.id), "name": ((" ".join(filter(None, [row.first_name, row.last_name]))) or row.email)}
            for row in reps[:50]
        ],
        contacts=[{"id": str(row.id), "name": row.name} for row in contacts[:50]],
        stock=[
            {
                "id": str(row.id),
                "name": row.name,
                "quantity": str(row.quantity),
                "unit": row.unit,
                "batch": row.supplier_batch_number,
            }
            for row in stock[:50]
        ],
        has_more=len(stock) > 50,
        people_has_more=len(reps) > 50 or len(contacts) > 50,
    )


@bp.get("/api/crm/tastings/pool")
@requires_auth
def pool():
    rows = TastingRepository(db_session()).pool(g.current_org_id, _offset())
    return jsonify(lots=[service.pool_dict(row) for row in rows[:50]], has_more=len(rows) > 50)


@bp.get("/api/crm/tastings/<event_id>")
@requires_auth
def get_tasting(event_id):
    return jsonify(
        tasting=service.event_dict(db_session(), service.get_event(db_session(), g.current_org_id, event_id))
    )


def _write(operation, *args):
    db = db_session()
    try:
        row = operation(db, g.current_org_id, service.uid(g.user_id), *args)
        db.commit()
    except IntegrityError:
        db.rollback()
        raise service.TastingError(
            "This operation conflicts with an existing tasting record; reload and retry", 409
        ) from None
    logger.info(
        "tastings_operation_recorded",
        org_id=str(g.current_org_id),
        user_id=str(g.user_id),
        tasting_id=str(row.id),
        operation=request.endpoint,
        state=row.status,
    )
    return jsonify(tasting=service.event_dict(db, row))


@bp.post("/api/crm/tastings")
@requires_auth
def create_tasting():
    return _write(service.save_event, request.get_json(silent=True)), 201


@bp.put("/api/crm/tastings/<event_id>")
@requires_auth
def update_tasting(event_id):
    return _write(service.save_event, request.get_json(silent=True), event_id)


@bp.post("/api/crm/tastings/<event_id>/dispatch")
@requires_auth
def dispatch_tasting(event_id):
    if not has_permission(g.current_user, "inventory.adjust"):
        logger.warning(
            "tastings_access_denied", org_id=str(g.current_org_id), user_id=str(g.user_id), operation=request.endpoint
        )
        abort(403)
    return _write(service.dispatch, event_id, request.get_json(silent=True), request.headers.get("Idempotency-Key"))


@bp.post("/api/crm/tastings/<event_id>/finalise")
@requires_auth
def finalise_tasting(event_id):
    return _write(service.finalise, event_id, request.get_json(silent=True))


@bp.get("/api/crm/tastings/<event_id>/invoice-lines")
@requires_auth
def tasting_invoice_lines(event_id):
    """Xero lines that may be bottles sold at this tasting or event, to link when closing it."""
    return jsonify({"lines": service.invoice_line_choices(db_session(), g.current_org_id, event_id)})


@bp.post("/api/crm/tastings/<event_id>/cancel")
@requires_auth
def cancel_tasting(event_id):
    data = request.get_json(silent=True)
    if data not in (None, {}):
        raise service.TastingError("Cancellation takes an empty request")
    return _write(service.cancel, event_id)
