"""Dispatching a contract order's goods (GL-P08 part 2).

Goods leaving the CCA are either transferred to another CCA or removed for duty. The order's
duty responsibility decides which:

- the customer is liable (``customer_licensee`` or ``customer_underbond``): a transfer to the
  customer's CCA. It is left out of duty and listed in Customs → Transfers until the customer
  acknowledges receipt;
- the producer is liable: a removal, entered on the excise draft for the day it left.

A dispatch takes the stock off the lots the order's batches made, nothing else.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import ROUND_FLOOR, Decimal, InvalidOperation
from uuid import UUID
from zoneinfo import ZoneInfo

from app.core.backend.event_writer import EventWriter
from app.core.db.models.inventory_item import InventoryItem, InventoryType
from app.core.domain.inventory_quantity_guard import InventoryQuantityWriteReason, allow_inventory_quantity_write
from app.core.utils.inventory_quantity import coerce_stored_quantity, parse_stored_quantity_to_decimal
from app.core.utils.unit_conversion import is_count_unit
from app.features.contract_manufacturing.models.dispatch import ContractDispatch, ContractDispatchLine
from app.features.contract_manufacturing.models.orders import ContractCustomer, ContractOrder, ContractOrderExecution
from app.features.contract_manufacturing.services.orders import OrderError

NZ = ZoneInfo("Pacific/Auckland")  # moves are entered and dated in NZ time
RECEIPT_OVERDUE_DAYS = 14  # the same as a sale to another CCA (cca_transfers)


def _nz_day(moment: datetime) -> date:
    return moment.astimezone(NZ).date()


def _text(value, label: str, limit: int, required: bool = True) -> str | None:
    if value is None or (isinstance(value, str) and not value.strip()):
        if required:
            raise OrderError(f"Enter the {label}")
        return None
    if not isinstance(value, str) or len(value.strip()) > limit:
        raise OrderError(f"The {label} must be text of at most {limit} characters")
    return value.strip()


def _when(value) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise OrderError("Enter when the goods left")
    try:
        moment = datetime.fromisoformat(value.strip())
    except ValueError:
        raise OrderError("When the goods left must be a date and time like 2026-10-01T14:30") from None
    return moment.replace(tzinfo=NZ) if moment.tzinfo is None else moment


def _quantity(value) -> Decimal:
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise OrderError("Each quantity must be a number") from None
    if not amount.is_finite() or amount <= 0 or amount.adjusted() > 12:
        raise OrderError("Each quantity must be more than zero")
    return amount


def _order(db, org_id: UUID, order_id: UUID, lock: bool = False) -> ContractOrder:
    query = db.query(ContractOrder).filter(ContractOrder.org_id == org_id, ContractOrder.id == order_id)
    row = (query.with_for_update() if lock else query).one_or_none()
    if row is None:
        raise OrderError("Order not found", 404)
    return row


def _lots_query(db, org_id: UUID, order_id: UUID):
    executions = db.query(ContractOrderExecution.execution_id).filter(
        ContractOrderExecution.org_id == org_id, ContractOrderExecution.order_id == order_id
    )
    return db.query(InventoryItem).filter(
        InventoryItem.org_id == org_id,
        InventoryItem.source_execution_id.in_(executions),
        InventoryItem.inventory_type == InventoryType.FINAL_PRODUCT.value,
    )


def dispatchable(db, org_id: UUID, order_id: UUID) -> list[dict]:
    """The finished lots the order's batches made, with what is left of each."""
    _order(db, org_id, order_id)
    out = []
    for item in _lots_query(db, org_id, order_id).order_by(InventoryItem.created_at, InventoryItem.id):
        left = parse_stored_quantity_to_decimal(item.quantity)
        if is_count_unit(item.unit):
            left = left.to_integral_value(rounding=ROUND_FLOOR)
        if left <= 0:
            continue
        out.append(
            {
                "inventory_item_id": str(item.id),
                "product_name": item.name,
                "batch": item.supplier_batch_number or (item.extra_data or {}).get("batch_number"),
                "available": format(left.normalize(), "f"),
                "unit": item.unit,
            }
        )
    return out


def treatment_for(order: ContractOrder) -> str:
    return "removal" if order.duty_responsibility == "producer_licensee" else "cca_transfer"


def status_of(row: ContractDispatch, today: date | None = None) -> str:
    """The same words as a sale to another CCA, so the Transfers register reads one way."""
    if row.treatment == "removal":
        return "removed"
    if row.received_on is not None:
        return "received"
    today = today or date.today()
    return "receipt_overdue" if (today - _nz_day(row.moved_at)).days > RECEIPT_OVERDUE_DAYS else "awaiting_receipt"


def dispatch_dict(row: ContractDispatch, today: date | None = None) -> dict:
    return {
        "id": str(row.id),
        "order_id": str(row.order_id),
        "treatment": row.treatment,
        "status": status_of(row, today),
        "destination_name": row.destination_name,
        "destination_cca": row.destination_cca,
        "moved_at": row.moved_at.astimezone(NZ).isoformat(),
        "carrier": row.carrier,
        "consignment_note": row.consignment_note,
        "received_on": row.received_on.isoformat() if row.received_on else None,
        "receipt_reference": row.receipt_reference,
        "lines": [
            {
                "inventory_item_id": str(line.inventory_item_id),
                "product_name": line.product_name,
                "quantity": format(Decimal(line.quantity).normalize(), "f"),
                "unit": line.unit,
            }
            for line in row.lines
        ],
    }


def dispatches(db, org_id: UUID, order_id: UUID) -> list[dict]:
    _order(db, org_id, order_id)
    rows = (
        db.query(ContractDispatch)
        .filter(ContractDispatch.org_id == org_id, ContractDispatch.order_id == order_id)
        .order_by(ContractDispatch.moved_at.desc())
    )
    return [dispatch_dict(r) for r in rows]


def dispatch(db, org_id: UUID, order_id: UUID, data, user_id) -> ContractDispatch:
    """Take the chosen quantities off the order's lots and record where they went."""
    if not isinstance(data, dict):
        raise OrderError("Send the dispatch as an object")
    order = _order(db, org_id, order_id, lock=True)
    if order.status not in {"confirmed", "completed"}:
        raise OrderError("Only a confirmed or completed order can be dispatched", 409)
    moved_at = _when(data.get("moved_at"))
    if _nz_day(moved_at) > date.today() + timedelta(days=1):
        raise OrderError("The goods can't leave in the future")
    carrier = _text(data.get("carrier"), "carrier", 200)
    note = _text(data.get("consignment_note"), "consignment note", 200, required=False)
    picks = data.get("lines")
    if not isinstance(picks, list) or not picks or len(picks) > 50:
        raise OrderError("Choose at least one batch to dispatch")
    wanted: dict[UUID, Decimal] = {}
    for pick in picks:
        if not isinstance(pick, dict):
            raise OrderError("Choose at least one batch to dispatch")
        try:
            item_id = UUID(str(pick.get("inventory_item_id")))
        except ValueError:
            raise OrderError("Choose a batch made for this order") from None
        wanted[item_id] = wanted.get(item_id, Decimal(0)) + _quantity(pick.get("quantity"))
    lots = {
        item.id: item
        for item in _lots_query(db, org_id, order_id)
        .filter(InventoryItem.id.in_(list(wanted)))
        .order_by(InventoryItem.id)
        .with_for_update()
    }
    customer = (
        db.query(ContractCustomer)
        .filter(ContractCustomer.org_id == org_id, ContractCustomer.id == order.customer_id)
        .one()
    )
    treatment = treatment_for(order)
    row = ContractDispatch(
        org_id=org_id,
        order_id=order.id,
        treatment=treatment,
        destination_name=customer.name,
        destination_cca=order.customer_cca_reference if treatment == "cca_transfer" else None,
        moved_at=moved_at,
        carrier=carrier,
        consignment_note=note,
        recorded_by_user_id=user_id,
    )
    db.add(row)
    db.flush()
    events = EventWriter(db, org_id)
    for item_id, amount in wanted.items():
        item = lots.get(item_id)
        if item is None:
            raise OrderError("Choose a batch made for this order")
        current = parse_stored_quantity_to_decimal(item.quantity)
        if is_count_unit(item.unit) and amount != amount.to_integral_value():
            raise OrderError(f"{item.name} is counted in whole {item.unit}")
        if amount > current:
            raise OrderError(f"{item.supplier_batch_number or item.name} only has {current.normalize():f} {item.unit}")
        with allow_inventory_quantity_write(InventoryQuantityWriteReason.CONTRACT_DISPATCH):
            item.quantity = coerce_stored_quantity(current - amount)
            db.flush()
        db.add(
            ContractDispatchLine(
                org_id=org_id,
                dispatch_id=row.id,
                inventory_item_id=item.id,
                product_name=item.name,
                quantity=amount,
                unit=item.unit,
            )
        )
        events.emit(
            event_type="inventory_item.quantity_adjusted",
            entity_type="inventory_item",
            entity_id=item.id,
            payload={
                "quantity_before": str(current),
                "quantity_after": str(item.quantity),
                "delta": str(-amount),
                "reason": "contract_dispatch",
                "reference": order.reference,
                "contract_dispatch_id": str(row.id),
            },
            diff={"quantity": {"before": str(current), "after": str(item.quantity)}},
        )
    db.flush()
    events.emit(
        event_type="contract_order.dispatched",
        entity_type="contract_order",
        entity_id=order.id,
        payload={
            "reference": order.reference,
            "contract_dispatch_id": str(row.id),
            "treatment": treatment,
            "destination_cca": row.destination_cca,
            "moved_at": row.moved_at.isoformat(),
            "carrier": carrier,
        },
    )
    db.expire(row, ["lines"])
    return row


def record_receipt(db, org_id: UUID, order_id: UUID, dispatch_id: UUID, data) -> ContractDispatch:
    """The customer's written acknowledgement that the goods arrived at their CCA."""
    if not isinstance(data, dict):
        raise OrderError("Send the receipt as an object")
    row = (
        db.query(ContractDispatch)
        .filter(
            ContractDispatch.org_id == org_id,
            ContractDispatch.order_id == order_id,
            ContractDispatch.id == dispatch_id,
        )
        .with_for_update()
        .one_or_none()
    )
    if row is None:
        raise OrderError("Dispatch not found", 404)
    if row.treatment != "cca_transfer":
        raise OrderError("Goods removed for duty have no receipt to record", 409)
    try:
        received = date.fromisoformat(str(data.get("received_on")).strip())
    except ValueError:
        raise OrderError("The date it was received must be a date like 2026-10-01") from None
    if received < _nz_day(row.moved_at):
        raise OrderError("The goods can't be received before they left")
    if received > date.today() + timedelta(days=1):
        raise OrderError("The receipt date can't be in the future")
    row.received_on = received
    row.receipt_reference = _text(data.get("receipt_reference"), "receipt (who acknowledged it, or the document)", 500)
    db.flush()
    return row
