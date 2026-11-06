"""GL-P01b: record goods a customer sent back.

Money, goods and duty stay three separate records (docs/returns-and-credits.md):

* a Xero credit note (GL-P01a) is the money; it never moves stock;
* a ``SalesReturn`` (this module) is the goods; only it moves stock;
* goods back inside the licensed area become a *possible* duty credit on the excise draft
  (``excise._customer_returns``), never claimed automatically.

By condition:

* ``resaleable`` - back into the batch it was sold from when the sale line is known
  (the FIFO allocation behind the credited invoice), else into a new lot;
* ``damaged``    - into a new lot of its own, placed on quality hold (GL-P02);
* ``destroyed``  - nothing back in stock; the record says so.

A line can't have more returned than was credited (or sold), counting earlier returns.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from uuid import UUID, uuid4

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.db.models.audit_log import AuditLog
from app.core.db.models.inventory_item import InventoryItem, InventoryType
from app.core.db.repositories.inventory_repo import InventoryRepository
from app.core.services import lot_holds
from app.core.utils.time import utc_now
from app.features.crm.models.product_mapping import ProductMapping
from app.features.crm.models.sales_fifo_allocation import SalesFifoAllocation
from app.features.crm.models.sales_return import CONDITIONS, SalesReturn
from app.features.crm.models.xero_credit_note import XeroCreditNote
from app.features.crm.models.xero_credit_note_line import XeroCreditNoteLine

MAX_NOTE = 500


class ReturnError(ValueError):
    """A return that can't be recorded as asked; the message is shown as-is."""


class ReturnConflictError(ReturnError):
    pass


def _quantity(value) -> Decimal:
    try:
        qty = Decimal(str(value).strip())
    except (InvalidOperation, AttributeError, ValueError):
        raise ReturnError("Enter how many came back") from None
    if not qty.is_finite() or qty <= 0:
        raise ReturnError("Enter how many came back")
    if qty > Decimal("1e9"):
        raise ReturnError("That quantity is too large")
    return qty


def _returned_on_line(session: Session, org_id: UUID, line_id: UUID) -> Decimal:
    total = (
        session.query(func.coalesce(func.sum(SalesReturn.quantity), 0))
        .filter(SalesReturn.org_id == org_id, SalesReturn.credit_note_line_id == line_id)
        .scalar()
    )
    return Decimal(str(total))


def _returned_on_allocation(session: Session, org_id: UUID, allocation_id: UUID) -> Decimal:
    total = (
        session.query(func.coalesce(func.sum(SalesReturn.quantity), 0))
        .filter(SalesReturn.org_id == org_id, SalesReturn.allocation_id == allocation_id)
        .scalar()
    )
    return Decimal(str(total))


def _sale_line_for(session: Session, org_id: UUID, note: XeroCreditNote, mapping: ProductMapping, qty: Decimal):
    """The FIFO sale line on a credited invoice that this return most likely came from.

    Newest first (a credit usually follows the latest delivery), skipping tasting sales (they
    never moved warehouse stock) and lines already fully returned.
    """
    invoice_ids = [str(i) for i in (note.allocated_invoice_ids or [])]
    if not invoice_ids:
        return None
    candidates = (
        session.query(SalesFifoAllocation)
        .filter(
            SalesFifoAllocation.org_id == org_id,
            SalesFifoAllocation.xero_invoice_id.in_(invoice_ids),
            SalesFifoAllocation.tasting_allocation_id.is_(None),
            (SalesFifoAllocation.product_mapping_id == mapping.id)
            | (SalesFifoAllocation.product_name == mapping.biz_e_product_name),
        )
        .order_by(SalesFifoAllocation.created_at.desc(), SalesFifoAllocation.id)
        .all()
    )
    for allocation in candidates:
        left = Decimal(str(allocation.quantity)) - _returned_on_allocation(session, org_id, allocation.id)
        if left >= qty:
            return allocation
    return None


def record_return(
    session: Session,
    org_id: UUID,
    user_id: UUID | None,
    *,
    condition: str,
    quantity,
    received_on: date,
    note: str | None = None,
    credit_note_line_id: UUID | None = None,
    product_name: str | None = None,
    unit: str | None = None,
) -> SalesReturn:
    """Record one physical return. Caller commits."""
    if condition not in CONDITIONS:
        raise ReturnError("Say what condition it came back in")
    qty = _quantity(quantity)
    note = (note or "").strip() or None
    if note and len(note) > MAX_NOTE:
        raise ReturnError(f"Keep the note under {MAX_NOTE} characters")
    # Server time is UTC; New Zealand is up to a day ahead, so "today there" is still allowed.
    if received_on > utc_now().date() + timedelta(days=1):
        raise ReturnError("The return can't be received in the future")

    allocation = None
    xero_invoice_id = None
    if credit_note_line_id is not None:
        found = (
            session.query(XeroCreditNoteLine, XeroCreditNote, ProductMapping)
            .join(
                XeroCreditNote,
                (XeroCreditNote.org_id == XeroCreditNoteLine.org_id)
                & (XeroCreditNote.id == XeroCreditNoteLine.credit_note_id),
            )
            .join(
                ProductMapping,
                (ProductMapping.org_id == XeroCreditNoteLine.org_id)
                & (ProductMapping.id == XeroCreditNoteLine.product_mapping_id),
            )
            .filter(
                XeroCreditNoteLine.org_id == org_id,
                XeroCreditNoteLine.id == credit_note_line_id,
                XeroCreditNoteLine.is_current.is_(True),
                XeroCreditNote.status.in_(["AUTHORISED", "PAID"]),
            )
            .with_for_update(of=XeroCreditNoteLine)
            .one_or_none()
        )
        if found is None:
            raise LookupError("Credit note line not found")
        line, credit_note, mapping = found
        if line.no_return_at is not None:
            raise ReturnConflictError("This line was recorded as credit only, with no goods back")
        credited = abs(Decimal(str(line.quantity))) if line.quantity is not None else None
        if credited is not None and _returned_on_line(session, org_id, line.id) + qty > credited:
            left = credited - _returned_on_line(session, org_id, line.id)
            raise ReturnError(f"Only {left.normalize():f} more can be returned against this credit")
        product_name = mapping.biz_e_product_name
        allocation = _sale_line_for(session, org_id, credit_note, mapping, qty)
        if allocation is not None:
            xero_invoice_id = allocation.xero_invoice_id
            unit = allocation.unit
    else:
        product_name = (product_name or "").strip()
        if not product_name:
            raise ReturnError("Say which product came back")
        if len(product_name) > 500:
            raise ReturnError("That product name is too long")

    if not unit:
        unit = (
            session.query(InventoryItem.unit)
            .filter(
                InventoryItem.org_id == org_id,
                InventoryItem.name == product_name,
                InventoryItem.inventory_type == InventoryType.FINAL_PRODUCT.value,
            )
            .order_by(InventoryItem.created_at.desc())
            .limit(1)
            .scalar()
        )
    if not unit:
        raise ReturnError("Say what unit it came back in")

    # The stock moves first, then the row is written whole: the table's check ties condition to
    # "something came back", and Postgres can't defer a CHECK to the end of the transaction.
    return_id = uuid4()
    repo = InventoryRepository(session)
    reference = f"Customer return {return_id}"
    resulting_lot_id = None
    hold = None
    if condition == "resaleable" and allocation is not None:
        # Back into the very batch it was sold from, so its history and duty stay its own.
        repo.reverse_final_product_fifo_consumption(
            org_id,
            allocation.inventory_item_id,
            qty,
            reference=reference,
            commit=False,
            sale_context={"customer_return_id": str(return_id), "invoice": xero_invoice_id},
        )
        resulting_lot_id = allocation.inventory_item_id
    elif condition in ("resaleable", "damaged"):
        original = session.get(InventoryItem, allocation.inventory_item_id) if allocation else None
        extra = {"customer_return": {"return_id": str(return_id), "received_on": received_on.isoformat()}}
        batch = (original.extra_data or {}).get("batch_number") if original is not None else None
        if batch is not None:
            extra["batch_number"] = batch
        lot = repo.create_inventory_item(
            org_id=org_id,
            name=product_name,
            quantity=qty,
            unit=unit,
            inventory_type=InventoryType.FINAL_PRODUCT.value,
            extra_data=extra,
            commit=False,
            site_id=original.site_id if original is not None else None,
            location_id=original.location_id if original is not None else None,
        )
        resulting_lot_id = lot.id
        if condition == "damaged":
            hold = lot_holds.place_hold(
                session, org_id, lot.id, f"Returned damaged{': ' + note if note else ''}"[:500], user_id
            )[0]

    ret = SalesReturn(
        id=return_id,
        org_id=org_id,
        credit_note_line_id=credit_note_line_id,
        allocation_id=allocation.id if allocation else None,
        xero_invoice_id=xero_invoice_id,
        product_name=product_name,
        quantity=qty,
        unit=unit,
        condition=condition,
        received_on=received_on,
        original_lot_id=allocation.inventory_item_id if allocation else None,
        resulting_lot_id=resulting_lot_id,
        hold_id=hold.id if hold else None,
        note=note,
        recorded_by=user_id,
        created_at=utc_now(),
    )
    session.add(ret)
    session.flush()
    session.add(
        AuditLog(
            org_id=org_id,
            user_id=user_id,
            action="customer_return_recorded",
            entity="sales_return",
            entity_id=ret.id,
            meta_data={
                "condition": condition,
                "quantity": str(qty),
                "product": product_name,
                "credit_note_line_id": str(credit_note_line_id) if credit_note_line_id else None,
                "resulting_lot_id": str(ret.resulting_lot_id) if ret.resulting_lot_id else None,
            },
        )
    )
    session.flush()
    return ret


def serialise(ret: SalesReturn) -> dict:
    return {
        "id": str(ret.id),
        "credit_note_line_id": str(ret.credit_note_line_id) if ret.credit_note_line_id else None,
        "xero_invoice_id": ret.xero_invoice_id,
        "product_name": ret.product_name,
        "quantity": str(ret.quantity),
        "unit": ret.unit,
        "condition": ret.condition,
        "received_on": ret.received_on.isoformat(),
        "original_lot_id": str(ret.original_lot_id) if ret.original_lot_id else None,
        "resulting_lot_id": str(ret.resulting_lot_id) if ret.resulting_lot_id else None,
        "on_hold": ret.hold_id is not None,
        "note": ret.note,
        "created_at": ret.created_at.isoformat() if ret.created_at else None,
    }


def recent(session: Session, org_id: UUID, limit: int = 50) -> list[SalesReturn]:
    return (
        session.query(SalesReturn)
        .filter(SalesReturn.org_id == org_id)
        .order_by(SalesReturn.received_on.desc(), SalesReturn.created_at.desc())
        .limit(limit)
        .all()
    )
