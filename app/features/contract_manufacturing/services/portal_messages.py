"""One tenant-scoped conversation per published contract order."""

from app.features.contract_manufacturing.models.portal import PortalMessage, PortalPublication
from app.features.contract_manufacturing.services.orders import (
    ContractOrderService,
    OrderError,
    identifier,
    object_body,
    text_value,
)
from app.features.contract_manufacturing.services.portal_auth import audit

MAX_VISIBLE_MESSAGES = 100


def _latest_shared_order(db, org_id, order):
    publication = (
        db.query(PortalPublication)
        .filter_by(org_id=org_id, order_id=order.id, customer_id=order.customer_id)
        .order_by(PortalPublication.revision.desc())
        .first()
    )
    if publication is None or publication.revoked_at is not None:
        raise OrderError("A current portal publication is required", 409)


def _message_body(data):
    object_body(data, {"body"})
    return text_value(data.get("body"), "message", 2000)


def send_staff_message(db, org_id, actor_id, order_id, data):
    body = _message_body(data)
    order = ContractOrderService(db, org_id).order(order_id, lock=True)
    _latest_shared_order(db, org_id, order)
    row = PortalMessage(
        org_id=org_id,
        order_id=order.id,
        customer_id=order.customer_id,
        sender_staff_id=actor_id,
        body=body,
    )
    db.add(row)
    db.flush()
    audit(db, org_id, "staff_message_sent", row)
    return row


def send_customer_message(db, principal, order_id, data):
    from app.features.contract_manufacturing.services.portal_sharing import shared_order

    body = _message_body(data)
    order = ContractOrderService(db, principal.org_id).order(identifier(order_id, "order_id"), lock=True)
    if order.customer_id != principal.customer_id:
        raise OrderError("Order not found", 404)
    shared_order(db, principal, order.id)
    row = PortalMessage(
        org_id=principal.org_id,
        order_id=order.id,
        customer_id=principal.customer_id,
        sender_portal_id=principal.id,
        body=body,
    )
    db.add(row)
    db.flush()
    audit(db, principal.org_id, "customer_message_sent", row)
    return row


def message_dto(row):
    return {
        "id": str(row.id),
        "sender": "producer" if row.sender_staff_id is not None else "customer",
        "body": row.body,
        "created_at": row.created_at.isoformat(),
    }


def messages_for_order(db, org_id, customer_id, order_id):
    rows = (
        db.query(PortalMessage)
        .filter_by(org_id=org_id, customer_id=customer_id, order_id=order_id)
        .order_by(PortalMessage.created_at.desc(), PortalMessage.id.desc())
        .limit(MAX_VISIBLE_MESSAGES)
        .all()
    )
    return [message_dto(row) for row in reversed(rows)]
