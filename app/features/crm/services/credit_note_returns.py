"""Pending stock-return decisions created by mapped, authorised Xero credit-note lines."""

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.db.models.audit_log import AuditLog
from app.features.crm.models.xero_credit_note import XeroCreditNote
from app.features.crm.models.xero_credit_note_line import XeroCreditNoteLine
from app.features.crm.repositories.xero_credit_note_repo import XeroCreditNoteRepository


class ReturnDecisionConflictError(ValueError):
    pass


def pending(session: Session, org_id: UUID, *, page: int = 1, page_size: int = 25) -> dict:
    rows, total = XeroCreditNoteRepository(session).pending_returns(org_id, page=page, page_size=page_size)
    # GL-P01b: how much of each line has already come back (one query for the page).
    from sqlalchemy import func

    from app.features.crm.models.sales_return import SalesReturn

    line_ids = [line.id for line, _note, _mapping in rows]
    returned = (
        dict(
            session.query(SalesReturn.credit_note_line_id, func.sum(SalesReturn.quantity))
            .filter(SalesReturn.org_id == org_id, SalesReturn.credit_note_line_id.in_(line_ids))
            .group_by(SalesReturn.credit_note_line_id)
            .all()
        )
        if line_ids
        else {}
    )
    items = []
    for line, note, mapping in rows:
        items.append(
            {
                "credit_note_id": str(note.id),
                "line_id": str(line.id),
                "line_key": line.line_key,
                "credit_note_number": note.number or note.xero_credit_note_id,
                "contact": note.contact,
                "date": note.date.isoformat() if note.date else None,
                "currency": note.currency,
                "total": str(note.total),
                "item_code": line.item_code,
                "description": line.description,
                "quantity": str(line.quantity) if line.quantity is not None else None,
                "line_amount": str(line.line_amount) if line.line_amount is not None else None,
                "product_name": mapping.biz_e_product_name,
                "returned": str(returned.get(line.id) or 0),
            }
        )
    return {"items": items, "page": page, "page_size": page_size, "total": total, "has_more": page * page_size < total}


def record_no_return(
    session: Session,
    org_id: UUID,
    credit_note_id: UUID,
    line_id: UUID,
    user_id: UUID,
    note: str,
) -> XeroCreditNoteLine:
    line = (
        session.query(XeroCreditNoteLine)
        .join(
            XeroCreditNote,
            (XeroCreditNote.org_id == XeroCreditNoteLine.org_id)
            & (XeroCreditNote.id == XeroCreditNoteLine.credit_note_id),
        )
        .filter(
            XeroCreditNoteLine.org_id == org_id,
            XeroCreditNoteLine.id == line_id,
            XeroCreditNoteLine.credit_note_id == credit_note_id,
            XeroCreditNoteLine.is_current.is_(True),
            XeroCreditNoteLine.product_mapping_id.isnot(None),
            XeroCreditNote.id == credit_note_id,
            XeroCreditNote.status.in_(["AUTHORISED", "PAID"]),
        )
        .with_for_update(of=XeroCreditNoteLine)
        .one_or_none()
    )
    if line is None:
        raise LookupError("Credit note line not found")
    if line.no_return_at is not None:
        raise ReturnDecisionConflictError("A no-return decision has already been recorded for this line")
    if not note.strip() or len(note.strip()) > 500:
        raise ValueError("Add a note of 1 to 500 characters")

    clean_note = note.strip()
    # GL-P01b: after a partial return this decision covers the rest ("no more goods"), so the
    # record keeps how much did come back and the two never contradict each other.
    from sqlalchemy import func

    from app.features.crm.models.sales_return import SalesReturn

    returned_before = (
        session.query(func.coalesce(func.sum(SalesReturn.quantity), 0))
        .filter(SalesReturn.org_id == org_id, SalesReturn.credit_note_line_id == line.id)
        .scalar()
    )
    line.no_return_note = clean_note
    line.no_return_by_user_id = user_id
    line.no_return_at = datetime.now(UTC)
    session.add(
        AuditLog(
            org_id=org_id,
            user_id=user_id,
            action="credit_note_line_no_return",
            entity="xero_credit_note_line",
            entity_id=line.id,
            meta_data={
                "credit_note_id": str(credit_note_id),
                "line_key": line.line_key,
                "note": clean_note,
                "returned_before": str(returned_before),
                "scope": "remainder" if returned_before else "whole line",
            },
        )
    )
    session.flush()
    return line
