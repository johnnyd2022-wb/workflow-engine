"""Customer reorder enquiries; acceptance and new orders remain staff decisions."""

from app.features.contract_manufacturing.models.portal import PortalReorderRequest
from app.features.contract_manufacturing.services.orders import (
    ContractOrderService,
    OrderError,
    object_body,
    text_value,
)
from app.features.contract_manufacturing.services.portal_auth import audit


def reorder_dto(row):
    return {"id": str(row.id), "note": row.note, "requested_at": row.requested_at.isoformat()}


def reorder_for_order(db, org_id, customer_id, order_id):
    row = db.query(PortalReorderRequest).filter_by(org_id=org_id, customer_id=customer_id, order_id=order_id).first()
    return reorder_dto(row) if row else None


def request_reorder(db, principal, order_id, data):
    from app.features.contract_manufacturing.services.portal_sharing import shared_order

    object_body(data, {"note"})
    note = text_value(data.get("note"), "note", 1000, False)
    # Serialize customer retries and publication withdrawal on the existing order lock.
    order = ContractOrderService(db, principal.org_id).order(order_id, lock=True)
    if order.customer_id != principal.customer_id:
        raise OrderError("Order not found", 404)
    publication = shared_order(db, principal, order.id)
    if order.status != "completed" or publication["status"] != "completed":
        raise OrderError("Reorders are available for published completed orders", 409)
    existing = (
        db.query(PortalReorderRequest)
        .filter_by(org_id=principal.org_id, customer_id=principal.customer_id, order_id=order.id)
        .first()
    )
    if existing:
        return existing, False
    row = PortalReorderRequest(
        org_id=principal.org_id,
        customer_id=principal.customer_id,
        order_id=order.id,
        requested_by=principal.id,
        note=note,
    )
    db.add(row)
    db.flush()
    audit(db, principal.org_id, "reorder_requested", row)
    return row, True
