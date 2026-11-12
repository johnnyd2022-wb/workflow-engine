"""Writing cost facts: manual / free lot prices and costing settings (live-cogs 8.1a).

Spec .agents/specs/live-cogs.md, "lot_cost_entries" (price facts). Callers own the commit.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.db.models.inventory_item import InventoryItem
from app.core.utils.time import utc_now
from app.features.costing.models import DIRECT_KINDS, CostFlow, CostingSettings, LotCostEntry

MAX_MONEY = Decimal("100000000000000")  # NUMERIC(18,4) holds < 10^14
ENTRY_KINDS = ("manual", "free")


class CostingError(ValueError):
    """The request can't be carried out; the message is safe to show (400)."""


class CostingNotFoundError(LookupError):
    """No such lot / entry / execution in this organisation (404)."""


def parse_amount(raw: Any, what: str, *, allow_zero: bool) -> Decimal:
    if isinstance(raw, bool) or raw is None or raw == "":
        raise CostingError(f"{what} is required")
    try:
        value = Decimal(str(raw).strip())
    except (InvalidOperation, ValueError, TypeError):
        raise CostingError(f"{what} must be a number") from None
    if not value.is_finite():
        raise CostingError(f"{what} must be a number")
    if value < 0 or (value == 0 and not allow_zero):
        raise CostingError(f"{what} must be {'0 or more' if allow_zero else 'more than 0'}")
    if value >= MAX_MONEY:
        raise CostingError(f"{what} is too large")
    if value != value.quantize(Decimal("0.0001")):
        raise CostingError(f"{what} can have at most 4 decimal places")
    return value


def may_enter_cost(db: Session, user, org_id: UUID) -> bool:
    """True when ``user`` may type a price for stock they add here: ``costs.manage`` in an org
    with the costing feature. Add Inventory paths ignore a cost field otherwise."""
    from app.core.security.access_policy import has_permission
    from app.core.security.entitlements import org_has_feature
    from app.features.costing import FEATURE_KEY

    return bool(has_permission(user, "costs.manage") and org_has_feature(db, org_id, FEATURE_KEY))


def created_flow(db: Session, org_id: UUID, item_id: UUID) -> CostFlow | None:
    return (
        db.query(CostFlow)
        .filter(
            CostFlow.org_id == org_id,
            CostFlow.inventory_item_id == item_id,
            CostFlow.direction == "in",
            CostFlow.kind == "created",
        )
        .order_by(CostFlow.created_at, CostFlow.id)
        .first()
    )


def price_new_lot(db: Session, org_id: UUID, item: InventoryItem, amount: Decimal, user_id=None) -> None:
    """Price a lot just added by hand, CSV or scan on its ``created`` flow (no commit)."""
    db.flush()
    flow = created_flow(db, org_id, item.id)
    if flow is None:
        raise CostingError("This lot can't take a price when it's added")
    set_lot_price(
        db, org_id, item.id, amount=amount, quantity=item.quantity, kind="manual", cost_flow_id=flow.id, user_id=user_id
    )


def lot_provenance(db: Session, org_id: UUID, item: InventoryItem) -> dict | None:
    """Where a lot's cost comes from, for the cost panel: the newest purchase recorded into it,
    the batch that made it, or the lot it was moved from. Hrefs are same-origin paths."""
    from app.core.db.models.execution import Execution
    from app.core.db.models.process import Process
    from app.features.costing.models import PurchaseAllocation, PurchaseDocument, PurchaseLine

    doc = (
        db.query(PurchaseDocument)
        .join(
            PurchaseLine,
            (PurchaseLine.org_id == PurchaseDocument.org_id) & (PurchaseLine.document_id == PurchaseDocument.id),
        )
        .join(
            PurchaseAllocation,
            (PurchaseAllocation.org_id == PurchaseLine.org_id)
            & (PurchaseAllocation.purchase_line_id == PurchaseLine.id),
        )
        .filter(
            PurchaseAllocation.org_id == org_id,
            PurchaseAllocation.inventory_item_id == item.id,
            PurchaseAllocation.status == "active",
        )
        .order_by(PurchaseDocument.document_date.desc().nullslast())
        .first()
    )
    if doc is not None:
        return {
            "kind": "purchase",
            "name": doc.payee_name,
            "date": doc.document_date.isoformat() if doc.document_date else None,
            "href": "/core/costing/purchases",
        }
    if item.source_execution_id:
        row = (
            db.query(Execution.started_at, Process.name)
            .join(Process, Process.id == Execution.process_id)
            .filter(Execution.org_id == org_id, Execution.id == item.source_execution_id)
            .first()
        )
        if row is not None:
            return {
                "kind": "batch",
                "name": row[1],
                "date": row[0].date().isoformat() if row[0] else None,
                "href": "/core/executions/live",
            }
    if item.transfer_receipt_id:
        from app.core.db.models.site_transfer import SiteStockReceipt, SiteStockTransfer

        receipt = (
            db.query(SiteStockReceipt)
            .filter(SiteStockReceipt.org_id == org_id, SiteStockReceipt.id == item.transfer_receipt_id)
            .one_or_none()
        )
        transfer = (
            db.query(SiteStockTransfer)
            .filter(SiteStockTransfer.org_id == org_id, SiteStockTransfer.id == receipt.transfer_id)
            .one_or_none()
            if receipt is not None
            else None
        )
        if transfer is not None and transfer.source_item_id and transfer.source_item_id != item.id:
            return {
                "kind": "transfer",
                "name": item.name,
                "date": None,
                "href": f"/core/inventory/view?item={transfer.source_item_id}",
            }
    return None


def _parse_uuid(raw: Any) -> UUID | None:
    try:
        return UUID(str(raw))
    except (ValueError, TypeError, AttributeError):
        return None


def get_lot(db: Session, org_id: UUID, item_id: Any, *, for_update: bool = False) -> InventoryItem:
    item_uuid = _parse_uuid(item_id)
    if item_uuid is None:
        raise CostingNotFoundError("Lot not found")
    query = db.query(InventoryItem).filter(InventoryItem.org_id == org_id, InventoryItem.id == item_uuid)
    if for_update:
        query = query.with_for_update()
    item = query.one_or_none()
    if item is None:
        raise CostingNotFoundError("Lot not found")
    return item


def editable_reason(db: Session, org_id: UUID, item: InventoryItem) -> str | None:
    """None when a price can be typed on this lot; otherwise why not."""
    if item.contract_customer_id:
        return "This stock belongs to a customer, so it costs you nothing"
    if item.transfer_receipt_id or item.source_execution_step_id:
        return "This lot's cost comes from where it was made or moved from"
    other = (
        db.query(CostFlow.id)
        .filter(
            CostFlow.org_id == org_id,
            CostFlow.inventory_item_id == item.id,
            CostFlow.direction == "in",
            CostFlow.kind.notin_(DIRECT_KINDS),
        )
        .first()
    )
    if other:
        return "This lot's cost comes from where it was made or moved from"
    from app.features.costing.models import PurchaseAllocation

    paid = (
        db.query(PurchaseAllocation.id)
        .filter(
            PurchaseAllocation.org_id == org_id,
            PurchaseAllocation.inventory_item_id == item.id,
            PurchaseAllocation.status.in_(("active", "orphaned")),
            PurchaseAllocation.amount >= 0,
        )
        .first()
    )
    if paid:
        return "This lot is priced by a purchase; change the purchase instead"
    return None


def active_entries(db: Session, org_id: UUID, item_id: UUID) -> list[LotCostEntry]:
    return (
        db.query(LotCostEntry)
        .filter(
            LotCostEntry.org_id == org_id,
            LotCostEntry.inventory_item_id == item_id,
            LotCostEntry.is_active.is_(True),
        )
        .order_by(LotCostEntry.created_at, LotCostEntry.id)
        .all()
    )


def set_lot_price(
    db: Session,
    org_id: UUID,
    item_id: Any,
    *,
    amount: Any = None,
    quantity: Any = None,
    kind: str = "manual",
    cost_flow_id: Any = None,
    note: str | None = None,
    user_id: UUID | None = None,
    replace_all: bool = False,
) -> LotCostEntry:
    """Record a typed or free price, replacing the active one in the same slot (lot + flow).
    ``replace_all`` (the lot cost panel's "what was paid" / "free"): the new whole-lot price
    replaces every hand-entered price on the lot, flow-specific ones included, so it takes effect."""
    if kind not in ENTRY_KINDS:
        raise CostingError("kind must be 'manual' or 'free'")
    item = get_lot(db, org_id, item_id, for_update=True)
    reason = editable_reason(db, org_id, item)
    if reason:
        raise CostingError(reason)

    if kind == "free":
        if amount not in (None, "", 0, "0") and parse_amount(amount, "Amount", allow_zero=True) != 0:
            raise CostingError("A free lot has no amount")
        amount_value = Decimal("0")
        quantity_value = (
            Decimal("1") if quantity in (None, "") else parse_amount(quantity, "Quantity", allow_zero=False)
        )
    else:
        amount_value = parse_amount(amount, "Amount", allow_zero=True)
        quantity_value = parse_amount(quantity, "Quantity", allow_zero=False)

    flow_uuid = None
    if cost_flow_id not in (None, ""):
        flow_uuid = _parse_uuid(cost_flow_id)
        flow = (
            db.query(CostFlow)
            .filter(
                CostFlow.org_id == org_id,
                CostFlow.id == flow_uuid,
                CostFlow.inventory_item_id == item.id,
                CostFlow.direction == "in",
                CostFlow.kind.in_(DIRECT_KINDS),
            )
            .one_or_none()
            if flow_uuid
            else None
        )
        if flow is None:
            raise CostingError("That stock receipt isn't part of this lot")
        if quantity_value > Decimal(str(flow.quantity)):
            raise CostingError(f"This receipt was {flow.quantity} {item.unit}; a price can't cover more than that")

    if replace_all and flow_uuid is not None:
        raise CostingError("A whole-lot price has no receipt")
    for existing in active_entries(db, org_id, item.id):
        if existing.cost_flow_id == flow_uuid or replace_all:
            existing.is_active = False
            existing.deactivated_at = utc_now()
    db.flush()

    entry = LotCostEntry(
        org_id=org_id,
        inventory_item_id=item.id,
        cost_flow_id=flow_uuid,
        kind=kind,
        amount=amount_value,
        quantity=quantity_value,
        note=(note or None) and str(note)[:500],
        is_active=True,
        created_by_user_id=user_id,
    )
    db.add(entry)
    db.flush()
    return entry


def deactivate_entry(db: Session, org_id: UUID, item_id: Any, entry_id: Any) -> LotCostEntry:
    item = get_lot(db, org_id, item_id, for_update=True)
    entry_uuid = _parse_uuid(entry_id)
    entry = (
        db.query(LotCostEntry)
        .filter(
            LotCostEntry.org_id == org_id,
            LotCostEntry.inventory_item_id == item.id,
            LotCostEntry.id == entry_uuid,
            LotCostEntry.is_active.is_(True),
        )
        .one_or_none()
        if entry_uuid
        else None
    )
    if entry is None:
        raise CostingNotFoundError("Price not found")
    entry.is_active = False
    entry.deactivated_at = utc_now()
    db.flush()
    return entry


def get_settings(db: Session, org_id: UUID) -> dict:
    row = db.query(CostingSettings).filter(CostingSettings.org_id == org_id).one_or_none()
    return {
        "use_last_known_price": True if row is None else bool(row.use_last_known_price),
        "split_basis": "quantity" if row is None else row.split_basis,
    }


def set_settings(db: Session, org_id: UUID, **changes) -> dict:
    allowed = {"use_last_known_price", "split_basis"}
    if not changes or set(changes) - allowed:
        raise CostingError("Only use_last_known_price and split_basis can be changed")
    if "use_last_known_price" in changes and not isinstance(changes["use_last_known_price"], bool):
        raise CostingError("use_last_known_price must be true or false")
    if "split_basis" in changes and changes["split_basis"] not in ("quantity", "litres"):
        raise CostingError("split_basis must be quantity or litres")
    from uuid import uuid4

    from sqlalchemy.dialects.postgresql import insert

    now = utc_now()
    db.execute(
        insert(CostingSettings.__table__)
        .values(id=uuid4(), org_id=org_id, **changes, created_at=now, updated_at=now)
        .on_conflict_do_update(index_elements=["org_id"], set_={**changes, "updated_at": now})
    )
    db.expire_all()
    return get_settings(db, org_id)
