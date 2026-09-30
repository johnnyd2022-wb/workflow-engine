"""Customer responses to explicitly published label proof copies."""

from datetime import UTC, datetime

from app.features.contract_manufacturing.models.portal import PortalApproval, PortalDocument, PortalPublication
from app.features.contract_manufacturing.services.orders import (
    ContractOrderService,
    OrderError,
    identifier,
    object_body,
    text_value,
)
from app.features.contract_manufacturing.services.portal_auth import audit


def _latest_publication(db, org_id, order_id, customer_id):
    row = (
        db.query(PortalPublication)
        .filter_by(org_id=org_id, order_id=order_id, customer_id=customer_id)
        .order_by(PortalPublication.revision.desc())
        .first()
    )
    if row is None or row.revoked_at is not None:
        raise OrderError("A current portal publication is required", 409)
    return row


def _shared_documents(publication):
    documents = publication.payload.get("documents") or {}
    return {item["id"]: item["title"] for item in documents.get("items", []) if isinstance(item, dict)}


def request_approval(db, org_id, actor_id, order_id, data):
    object_body(data, {"document_id", "prompt"})
    order = ContractOrderService(db, org_id).order(order_id, lock=True)
    document_id = identifier(data.get("document_id"), "document_id")
    prompt = text_value(data.get("prompt"), "prompt", 500)
    publication = _latest_publication(db, org_id, order.id, order.customer_id)
    if str(document_id) not in _shared_documents(publication):
        raise OrderError("Publish this document to the customer before requesting approval", 409)
    document = (
        db.query(PortalDocument)
        .filter_by(org_id=org_id, order_id=order.id, customer_id=order.customer_id, id=document_id, revoked_at=None)
        .first()
    )
    if document is None:
        raise OrderError("Shared document not found", 404)
    if db.query(PortalApproval.id).filter_by(org_id=org_id, order_id=order.id, document_id=document_id).first():
        raise OrderError("This document already has an approval request", 409)
    row = PortalApproval(
        org_id=org_id,
        order_id=order.id,
        customer_id=order.customer_id,
        document_id=document_id,
        prompt=prompt,
        requested_by=actor_id,
    )
    db.add(row)
    db.flush()
    audit(db, org_id, "approval_requested", row)
    return row


def approval_dto(row, title):
    return {
        "id": str(row.id),
        "document_id": str(row.document_id),
        "document_title": title,
        "prompt": row.prompt,
        "decision": row.decision,
        "response_note": row.response_note,
        "requested_at": row.requested_at.isoformat(),
        "responded_at": row.responded_at.isoformat() if row.responded_at else None,
    }


def customer_approvals(db, principal, publication):
    titles = _shared_documents(publication)
    if not titles:
        return []
    rows = (
        db.query(PortalApproval, PortalDocument)
        .join(PortalDocument, PortalApproval.document_id == PortalDocument.id)
        .filter(
            PortalApproval.org_id == principal.org_id,
            PortalApproval.customer_id == principal.customer_id,
            PortalApproval.order_id == publication.order_id,
            PortalApproval.document_id.in_(titles),
            PortalDocument.org_id == principal.org_id,
            PortalDocument.order_id == publication.order_id,
            PortalDocument.customer_id == principal.customer_id,
            PortalDocument.revoked_at.is_(None),
        )
        .order_by(PortalApproval.requested_at, PortalApproval.id)
        .all()
    )
    return [approval_dto(row, titles[str(row.document_id)]) for row, _ in rows]


def staff_approvals(db, org_id, order_id):
    rows = (
        db.query(PortalApproval, PortalDocument)
        .join(PortalDocument, PortalApproval.document_id == PortalDocument.id)
        .filter(
            PortalApproval.org_id == org_id,
            PortalApproval.order_id == order_id,
            PortalDocument.org_id == org_id,
            PortalDocument.order_id == order_id,
        )
        .order_by(PortalApproval.requested_at, PortalApproval.id)
        .all()
    )
    return [approval_dto(row, document.title) for row, document in rows]


def respond_approval(db, principal, order_id, approval_id, data):
    from app.features.contract_manufacturing.services.portal_sharing import shared_order

    object_body(data, {"decision", "response_note"})
    decision = data.get("decision")
    if decision not in ("approved", "changes_requested"):
        raise OrderError("Choose approved or changes requested")
    note = text_value(data.get("response_note"), "response_note", 1000, False)
    if decision == "changes_requested" and not note:
        raise OrderError("Describe the requested changes")
    order_id = identifier(order_id, "order_id")
    order = ContractOrderService(db, principal.org_id).order(order_id, lock=True)
    if order.customer_id != principal.customer_id:
        raise OrderError("Order not found", 404)
    visible = shared_order(db, principal, order_id)
    approval_id = identifier(approval_id, "approval_id")
    if str(approval_id) not in {item["id"] for item in visible["waiting_on_you"]["approvals"]}:
        raise OrderError("Approval request not found", 404)
    row = (
        db.query(PortalApproval)
        .filter_by(
            org_id=principal.org_id,
            customer_id=principal.customer_id,
            order_id=order_id,
            id=approval_id,
        )
        .with_for_update()
        .first()
    )
    if row is None:
        raise OrderError("Approval request not found", 404)
    document = (
        db.query(PortalDocument)
        .filter_by(
            org_id=principal.org_id,
            customer_id=principal.customer_id,
            order_id=order_id,
            id=row.document_id,
            revoked_at=None,
        )
        .first()
    )
    if document is None:
        raise OrderError("Approval request not found", 404)
    if row.responded_at is not None:
        raise OrderError("This approval already has a response", 409)
    row.decision = decision
    row.response_note = note
    row.responded_by = principal.id
    row.responded_at = datetime.now(UTC)
    db.flush()
    audit(db, principal.org_id, "approval_responded", row)
    return row
