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
* ``destroyed``  - nothing usable: a lot is recorded and written off at once (wastage register).

Goods go back into the batch they were sold from only when received at that batch's place;
received anywhere else they are a new lot there, so excise classifies the return by where it
was actually received.

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
    most = Decimal(0)
    for allocation in candidates:
        left = Decimal(str(allocation.quantity)) - _returned_on_allocation(session, org_id, allocation.id)
        if left >= qty:
            return allocation
        most = max(most, left)
    if candidates:
        # The credited invoice's sale lines are known, so every return against them must land on
        # one: that is the guard the invoice path shares, so the two can never add up past what
        # was sold. A quantity no single line can take is recorded in parts.
        if most <= 0:
            raise ReturnError("Everything sold on the credited invoice has already come back")
        raise ReturnError(
            f"Only {most.normalize():f} can come back against one sale line on the credited invoice; "
            "record the rest separately"
        )
    return None


def _place(session: Session, org_id: UUID, location_id: UUID | None, fallback: InventoryItem | None):
    """Where the goods were received: a named area (and its site), else where the batch is."""
    from app.core.db.models.stock_location import StockLocation

    if location_id is not None:
        loc = (
            session.query(StockLocation)
            .filter(StockLocation.org_id == org_id, StockLocation.id == location_id)
            .one_or_none()
        )
        if loc is None:
            raise LookupError("Stock area not found")
        return loc.site_id, loc.id
    if fallback is not None:
        return fallback.site_id, fallback.location_id
    return None, None


def _contact_for(session: Session, org_id: UUID, invoice_id: str | None, name: str | None) -> UUID | None:
    from app.features.crm.models.xero_contact import XeroContact
    from app.features.crm.models.xero_invoice import XeroInvoice

    if invoice_id:
        found = (
            session.query(XeroInvoice.contact_id)
            .filter(XeroInvoice.org_id == org_id, XeroInvoice.xero_invoice_id == invoice_id)
            .scalar()
        )
        if found:
            return found
    if name:
        return (
            session.query(XeroContact.id)
            .filter(XeroContact.org_id == org_id, XeroContact.name == name)
            .order_by(XeroContact.id)
            .limit(1)
            .scalar()
        )
    return None


def _write_off(session: Session, org_id: UUID, lot: InventoryItem, qty: Decimal, reason: str, user_id) -> UUID:
    """The same dual write as recording waste (inventory_wastage + a WASTAGE movement)."""
    from app.core.db.models.inventory_movement import InventoryMovement, InventoryMovementType
    from app.core.db.models.inventory_wastage import InventoryWastage
    from app.core.domain.inventory_quantity_guard import InventoryQuantityWriteReason, allow_inventory_quantity_write
    from app.core.utils.inventory_quantity import coerce_stored_quantity, parse_stored_quantity_to_decimal

    with allow_inventory_quantity_write(InventoryQuantityWriteReason.WASTAGE_RECORD):
        lot.quantity = coerce_stored_quantity(parse_stored_quantity_to_decimal(lot.quantity) - qty)
        record = InventoryWastage(
            org_id=org_id,
            inventory_item_id=lot.id,
            quantity_wasted=str(qty),
            unit=lot.unit,
            reason=reason[:500],
            recorded_by=str(user_id) if user_id else None,
        )
        session.add(record)
        session.flush()
        session.add(
            InventoryMovement(
                org_id=org_id,
                inventory_item_id=lot.id,
                source_wastage_id=record.id,
                movement_type=InventoryMovementType.WASTAGE.value,
                quantity=coerce_stored_quantity(-qty),
                unit=lot.unit,
                movement_metadata={"wastage_record_id": str(record.id), "customer_return": True},
            )
        )
        session.flush()
    return record.id


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
    allocation_id: UUID | None = None,
    product_name: str | None = None,
    unit: str | None = None,
    location_id: UUID | None = None,
) -> SalesReturn:
    """Record one physical return. Caller commits.

    Sources, most specific first: a sale line (``allocation_id``, from an invoice), a credited
    line (``credit_note_line_id``), or just a product name.
    """
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
    contact_name = None
    if allocation_id is not None:
        allocation = (
            session.query(SalesFifoAllocation)
            .filter(
                SalesFifoAllocation.org_id == org_id,
                SalesFifoAllocation.id == allocation_id,
                SalesFifoAllocation.tasting_allocation_id.is_(None),
            )
            .with_for_update()
            .one_or_none()
        )
        if allocation is None:
            raise LookupError("Sale line not found")
        left = Decimal(str(allocation.quantity)) - _returned_on_allocation(session, org_id, allocation.id)
        if qty > left:
            raise ReturnError(f"Only {left.normalize():f} more can be returned from this sale")
        product_name = allocation.product_name
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
            raise ReturnConflictError("This line was recorded as credit only: no more goods are expected")
        credited = abs(Decimal(str(line.quantity))) if line.quantity is not None else None
        already = _returned_on_line(session, org_id, line.id)
        if credited is not None and already + qty > credited:
            raise ReturnError(f"Only {(credited - already).normalize():f} more can be returned against this credit")
        contact_name = credit_note.contact
        if allocation is None:
            product_name = mapping.biz_e_product_name
            allocation = _sale_line_for(session, org_id, credit_note, mapping, qty)
    if allocation is None:
        product_name = (product_name or "").strip()
        if not product_name:
            raise ReturnError("Say which product came back")
        if len(product_name) > 500:
            raise ReturnError("That product name is too long")
    xero_invoice_id = allocation.xero_invoice_id if allocation else None
    unit = allocation.unit if allocation else unit
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

    original = session.get(InventoryItem, allocation.inventory_item_id) if allocation else None
    site_id, received_at_location = _place(session, org_id, location_id, original)

    # The stock moves first, then the row is written whole: the table's check ties condition to
    # what happened to the stock, and Postgres can't defer a CHECK to the end of the transaction.
    return_id = uuid4()
    repo = InventoryRepository(session)
    hold = None
    wastage_id = None
    same_place = original is not None and (original.site_id, original.location_id) == (site_id, received_at_location)
    if condition == "resaleable" and same_place:
        # Back into the very batch it was sold from, received where that batch is: its history
        # and its duty stay its own.
        repo.reverse_final_product_fifo_consumption(
            org_id,
            original.id,
            qty,
            reference=f"Customer return {return_id}",
            commit=False,
            sale_context={"customer_return_id": str(return_id), "invoice": xero_invoice_id},
        )
        resulting_lot_id = original.id
    else:
        # Somewhere else, damaged or destroyed: a lot of its own at the place it was received,
        # carrying the batch number so the trace still reads through.
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
            site_id=site_id,
            location_id=received_at_location,
        )
        resulting_lot_id = lot.id
        if condition == "damaged":
            hold = lot_holds.place_hold(
                session, org_id, lot.id, f"Returned damaged{': ' + note if note else ''}"[:500], user_id
            )[0]
        elif condition == "destroyed":
            wastage_id = _write_off(
                session, org_id, lot, qty, f"Customer return destroyed{': ' + note if note else ''}", user_id
            )

    ret = SalesReturn(
        id=return_id,
        org_id=org_id,
        credit_note_line_id=credit_note_line_id,
        allocation_id=allocation.id if allocation else None,
        xero_invoice_id=xero_invoice_id,
        contact_id=_contact_for(session, org_id, xero_invoice_id, contact_name),
        product_name=product_name,
        quantity=qty,
        unit=unit,
        condition=condition,
        received_on=received_on,
        site_id=site_id,
        location_id=received_at_location,
        original_lot_id=original.id if original is not None else None,
        resulting_lot_id=resulting_lot_id,
        hold_id=hold.id if hold else None,
        wastage_id=wastage_id,
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
                "allocation_id": str(ret.allocation_id) if ret.allocation_id else None,
                "resulting_lot_id": str(resulting_lot_id),
                "location_id": str(received_at_location) if received_at_location else None,
            },
        )
    )
    session.flush()
    return ret


def _plain(value) -> str:
    """6, 2.5 -- not 6.0000."""
    return format(Decimal(str(value)).normalize(), "f")


def returnable_sale_lines(session: Session, org_id: UUID, xero_invoice_id: str) -> list[dict]:
    """The sale lines on one invoice that goods could come back from, with what's left of each."""
    rows = (
        session.query(SalesFifoAllocation)
        .filter(
            SalesFifoAllocation.org_id == org_id,
            SalesFifoAllocation.xero_invoice_id == xero_invoice_id,
            SalesFifoAllocation.tasting_allocation_id.is_(None),
        )
        .order_by(SalesFifoAllocation.product_name, SalesFifoAllocation.created_at)
        .all()
    )
    returned = (
        dict(
            session.query(SalesReturn.allocation_id, func.sum(SalesReturn.quantity))
            .filter(SalesReturn.org_id == org_id, SalesReturn.allocation_id.in_([r.id for r in rows]))
            .group_by(SalesReturn.allocation_id)
            .all()
        )
        if rows
        else {}
    )
    out = []
    for row in rows:
        back = Decimal(str(returned.get(row.id) or 0))
        out.append(
            {
                "allocation_id": str(row.id),
                "product_name": row.product_name,
                "unit": row.unit,
                "sold": _plain(row.quantity),
                "returned": _plain(back),
                "returnable": _plain(Decimal(str(row.quantity)) - back),
            }
        )
    return out


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
        "written_off": ret.wastage_id is not None,
        "location_id": str(ret.location_id) if ret.location_id else None,
        "contact_id": str(ret.contact_id) if ret.contact_id else None,
        "note": ret.note,
        "created_at": ret.created_at.isoformat() if ret.created_at else None,
    }


def recent(session: Session, org_id: UUID, limit: int = 50, contact_id: UUID | None = None) -> list[SalesReturn]:
    query = session.query(SalesReturn).filter(SalesReturn.org_id == org_id)
    if contact_id is not None:
        query = query.filter(SalesReturn.contact_id == contact_id)
    return query.order_by(SalesReturn.received_on.desc(), SalesReturn.created_at.desc()).limit(limit).all()
