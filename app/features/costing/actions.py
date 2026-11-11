"""Recording purchases into stock (live-cogs 8.1c-1; spec "8.1c-1 build contract").

Line arithmetic, the record / link / refund / not-stock / skip / reopen / review actions, the
purchases list and its tab rule, candidate lots, and what happens when Xero later changes a line
that has been acted on. Callers own the commit; every action locks its line.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.db.models.inventory_item import InventoryItem, InventoryType
from app.core.utils.time import utc_now
from app.features.costing.models import (
    DIRECT_KINDS,
    CostFlow,
    CostingSettings,
    LotCostEntry,
    PurchaseAllocation,
    PurchaseDocument,
    PurchaseLine,
)
from app.features.costing.service import CostingError, CostingNotFoundError, editable_reason, parse_amount

MONEY = Decimal("0.0001")
ZERO = Decimal("0")
RECORDABLE_TYPES = (InventoryType.RAW_MATERIAL.value, InventoryType.FINAL_PRODUCT.value)
TABS = ("to_record", "recorded", "skipped", "not_stock")


def _q(value: Decimal) -> Decimal:
    return value.quantize(MONEY, rounding=ROUND_HALF_UP)


def _uuid(raw) -> UUID | None:
    try:
        return UUID(str(raw))
    except (ValueError, TypeError, AttributeError):
        return None


def _d(raw) -> Decimal:
    try:
        return Decimal(str(raw))
    except (InvalidOperation, ValueError, TypeError):
        return ZERO


# --- loading ---------------------------------------------------------------------------------------


def get_line(db: Session, org_id: UUID, line_id: Any, *, for_update: bool = True) -> PurchaseLine:
    uid = _uuid(line_id)
    if uid is None:
        raise CostingNotFoundError("Purchase not found")
    q = db.query(PurchaseLine).filter(PurchaseLine.org_id == org_id, PurchaseLine.id == uid)
    if for_update:
        q = q.with_for_update()
    line = q.one_or_none()
    if line is None:
        raise CostingNotFoundError("Purchase not found")
    return line


def _document(db: Session, line: PurchaseLine) -> PurchaseDocument:
    return (
        db.query(PurchaseDocument)
        .filter(PurchaseDocument.org_id == line.org_id, PurchaseDocument.id == line.document_id)
        .one()
    )


def line_allocations(db: Session, line: PurchaseLine, *, statuses=("active",)) -> list[PurchaseAllocation]:
    return (
        db.query(PurchaseAllocation)
        .filter(
            PurchaseAllocation.org_id == line.org_id,
            PurchaseAllocation.purchase_line_id == line.id,
            PurchaseAllocation.status.in_(statuses),
        )
        .order_by(PurchaseAllocation.created_at, PurchaseAllocation.id)
        .all()
    )


# --- arithmetic --------------------------------------------------------------------------------------


def allocated(db: Session, line: PurchaseLine) -> Decimal:
    return sum((_d(a.amount) for a in line_allocations(db, line)), ZERO)


def open_amount(db: Session, line: PurchaseLine) -> Decimal | None:
    if line.amount_ex_tax is None:
        return None
    return _d(line.amount_ex_tax) - allocated(db, line) - _d(line.not_stock_amount)


def derive_state(db: Session, line: PurchaseLine, *, keep_skipped: bool = False) -> None:
    """Spec "Line arithmetic". ``skipped`` survives only when the caller says so."""
    if keep_skipped and line.state == "skipped":
        return
    amount = _d(line.amount_ex_tax) if line.amount_ex_tax is not None else None
    alloc = allocated(db, line)
    not_stock = _d(line.not_stock_amount)
    if amount is None:
        line.state = "open"
        return
    remaining = amount - alloc - not_stock
    if alloc != 0 and remaining == 0:
        line.state = "recorded"
    elif amount != 0 and not_stock == amount:
        line.state = "not_stock"
    elif alloc != 0:
        line.state = "partly_recorded"
    else:
        line.state = "open"


def _actionable(db: Session, line: PurchaseLine) -> tuple[PurchaseDocument, Decimal]:
    doc = _document(db, line)
    if line.amount_ex_tax is None:
        raise CostingError("This purchase has no amount in your base currency yet")
    if line.superseded_at is not None or doc.status != "active":
        raise CostingError("This purchase has changed in Xero; review it instead")
    return doc, open_amount(db, line)


def _same_sign(a: Decimal, b: Decimal) -> bool:
    return (a >= 0) == (b >= 0)


def _apply_rest(db: Session, line: PurchaseLine, rest: str | None) -> None:
    if rest not in (None, "", "later", "not_stock"):
        raise CostingError("rest must be 'not_stock' or 'later'")
    if rest == "not_stock":
        line.not_stock_amount = _d(line.not_stock_amount) + open_amount(db, line)


def deactivate_manual_prices(db: Session, org_id: UUID, item_id: UUID) -> None:
    """A purchase replaces a typed price on that lot (flow and whole-lot entries)."""
    now = utc_now()
    for entry in (
        db.query(LotCostEntry)
        .filter(
            LotCostEntry.org_id == org_id,
            LotCostEntry.inventory_item_id == item_id,
            LotCostEntry.is_active.is_(True),
        )
        .all()
    ):
        entry.is_active = False
        entry.deactivated_at = now


def _created_flow(db: Session, org_id: UUID, item_id: UUID) -> CostFlow | None:
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


def _flow_priced_quantity(db: Session, org_id: UUID, flow_id: UUID) -> Decimal:
    rows = (
        db.query(PurchaseAllocation.quantity)
        .filter(
            PurchaseAllocation.org_id == org_id,
            PurchaseAllocation.cost_flow_id == flow_id,
            PurchaseAllocation.status.in_(("active", "orphaned")),
        )
        .all()
    )
    return sum((_d(r[0]) for r in rows), ZERO)


# --- actions ------------------------------------------------------------------------------------------


def record(db: Session, org_id: UUID, line_id, rows: list, rest: str | None, user_id=None) -> PurchaseLine:
    from app.core.db.repositories.inventory_repo import InventoryRepository

    line = get_line(db, org_id, line_id)
    doc, remaining = _actionable(db, line)
    if doc.kind != "spend":
        raise CostingError("A refund reduces the cost of stock; it doesn't create any")
    if not isinstance(rows, list) or not rows:
        raise CostingError("Send at least one row")
    parsed = []
    for row in rows:
        if not isinstance(row, dict):
            raise CostingError("Each row is an object")
        name = str(row.get("name") or "").strip()
        unit = str(row.get("unit") or "").strip()
        inventory_type = row.get("inventory_type") or InventoryType.RAW_MATERIAL.value
        if not name or not unit:
            raise CostingError("Each row needs a name and a unit")
        if inventory_type not in RECORDABLE_TYPES:
            raise CostingError("inventory_type must be raw_material or final_product")
        parsed.append(
            (
                row,
                name,
                unit,
                inventory_type,
                parse_amount(row.get("quantity"), "Quantity", allow_zero=False),
                parse_amount(row.get("amount"), "Amount", allow_zero=True),
            )
        )
    total = sum((p[5] for p in parsed), ZERO)
    if total > remaining:
        raise CostingError(f"Rows total {total}, more than the {remaining} left on this purchase")

    repo = InventoryRepository(db)
    for row, name, unit, inventory_type, quantity, amount in parsed:
        try:
            item = repo.create_inventory_item(
                org_id=org_id,
                name=name,
                quantity=str(quantity),
                unit=unit,
                inventory_type=inventory_type,
                supplier=doc.payee_name,
                purchase_date=doc.document_date,
                supplier_batch_number=(row.get("supplier_batch_number") or None),
                expiry_date=_date(row.get("expiry_date")),
                location_id=_uuid(row.get("location_id")) if row.get("location_id") else None,
                site_id=_uuid(row.get("site_id")) if row.get("site_id") else None,
                commit=False,
            )
        except ValueError as error:
            raise CostingError(str(error)) from None
        flow = _created_flow(db, org_id, item.id)
        db.add(
            PurchaseAllocation(
                org_id=org_id,
                purchase_line_id=line.id,
                inventory_item_id=item.id,
                cost_flow_id=flow.id,
                amount=amount,
                quantity=quantity,
                status="active",
                created_by_user_id=user_id,
            )
        )
    db.flush()
    _apply_rest(db, line, rest)
    derive_state(db, line)
    db.flush()
    return line


def _date(raw) -> date | None:
    if raw in (None, ""):
        return None
    try:
        return date.fromisoformat(str(raw))
    except ValueError:
        raise CostingError("expiry_date must be YYYY-MM-DD") from None


def _qualifying_lot(db: Session, org_id: UUID, item_id) -> InventoryItem:
    uid = _uuid(item_id)
    item = (
        db.query(InventoryItem)
        .filter(InventoryItem.org_id == org_id, InventoryItem.id == uid)
        .with_for_update()
        .one_or_none()
        if uid
        else None
    )
    if item is None:
        raise CostingNotFoundError("Lot not found")
    return item


def link(db: Session, org_id: UUID, line_id, lots: list, rest: str | None, user_id=None) -> PurchaseLine:
    line = get_line(db, org_id, line_id)
    doc, remaining = _actionable(db, line)
    if doc.kind != "spend":
        raise CostingError("Use refund for a refund")
    if not isinstance(lots, list) or not lots:
        raise CostingError("Choose at least one lot")
    plan = []
    for entry in lots:
        if not isinstance(entry, dict):
            raise CostingError("Each lot is an object")
        item = _qualifying_lot(db, org_id, entry.get("inventory_item_id"))
        problem = _link_problem(db, org_id, item)
        if problem:
            raise CostingError(problem)
        flow = _created_flow(db, org_id, item.id)
        if flow is None:
            raise CostingError("This lot has no receipt to price; run the cost backfill")
        quantity = (
            _d(flow.quantity)
            if entry.get("quantity") in (None, "")
            else parse_amount(entry.get("quantity"), "Quantity", allow_zero=False)
        )
        if quantity + _flow_priced_quantity(db, org_id, flow.id) > _d(flow.quantity):
            raise CostingError(f"{item.name} received {flow.quantity} {item.unit}; a purchase can't pay for more")
        plan.append((item, flow, quantity, parse_amount(entry.get("amount"), "Amount", allow_zero=True)))
    total = sum((p[3] for p in plan), ZERO)
    if total > remaining:
        raise CostingError(f"Amounts total {total}, more than the {remaining} left on this purchase")
    for item, flow, quantity, amount in plan:
        deactivate_manual_prices(db, org_id, item.id)
        db.add(
            PurchaseAllocation(
                org_id=org_id,
                purchase_line_id=line.id,
                inventory_item_id=item.id,
                cost_flow_id=flow.id,
                amount=amount,
                quantity=quantity,
                status="active",
                created_by_user_id=user_id,
            )
        )
    db.flush()
    _apply_rest(db, line, rest)
    derive_state(db, line)
    db.flush()
    return line


def _link_problem(db: Session, org_id: UUID, item: InventoryItem) -> str | None:
    if item.inventory_type not in RECORDABLE_TYPES:
        return "Only raw materials and finished goods bought in can be linked to a purchase"
    reason = editable_reason(db, org_id, item)
    if reason:
        return reason
    if (
        db.query(PurchaseAllocation.id)
        .filter(
            PurchaseAllocation.org_id == org_id,
            PurchaseAllocation.inventory_item_id == item.id,
            PurchaseAllocation.status == "active",
            PurchaseAllocation.amount >= 0,
        )
        .first()
    ):
        return f"{item.name} is already paid for by a purchase"
    return None


def refund(db: Session, org_id: UUID, line_id, lots: list, user_id=None) -> PurchaseLine:
    line = get_line(db, org_id, line_id)
    doc, remaining = _actionable(db, line)
    if doc.kind != "refund":
        raise CostingError("Only a refund can reduce the cost of stock")
    if not isinstance(lots, list) or not lots:
        raise CostingError("Choose at least one lot")
    plan = []
    for entry in lots:
        if not isinstance(entry, dict):
            raise CostingError("Each lot is an object")
        item = _qualifying_lot(db, org_id, entry.get("inventory_item_id"))
        if item.contract_customer_id:
            raise CostingError("Customer-owned stock costs you nothing")
        try:
            amount = Decimal(str(entry.get("amount")))
        except (InvalidOperation, ValueError, TypeError):
            raise CostingError("Amount must be a number") from None
        if not amount.is_finite() or amount >= 0:
            raise CostingError("A refund amount is negative")
        plan.append((item, _q(amount)))
    total = sum((p[1] for p in plan), ZERO)
    if total < remaining:  # both negative: can't refund more than the line
        raise CostingError(f"Refunds total {total}, more than the {remaining} on this purchase")
    for item, amount in plan:
        db.add(
            PurchaseAllocation(
                org_id=org_id,
                purchase_line_id=line.id,
                inventory_item_id=item.id,
                cost_flow_id=None,
                amount=amount,
                quantity=ZERO,
                status="active",
                created_by_user_id=user_id,
            )
        )
    db.flush()
    derive_state(db, line)
    db.flush()
    return line


def not_stock(db: Session, org_id: UUID, line_id) -> PurchaseLine:
    line = get_line(db, org_id, line_id)
    _, remaining = _actionable(db, line)
    line.not_stock_amount = _d(line.not_stock_amount) + remaining
    derive_state(db, line)
    db.flush()
    return line


def skip(db: Session, org_id: UUID, line_id) -> PurchaseLine:
    line = get_line(db, org_id, line_id)
    _actionable(db, line)
    line.state = "skipped"
    db.flush()
    return line


def reopen(db: Session, org_id: UUID, line_id) -> PurchaseLine:
    line = get_line(db, org_id, line_id)
    _actionable(db, line)
    line.not_stock_amount = ZERO
    derive_state(db, line)
    db.flush()
    return line


def review(db: Session, org_id: UUID, line_id, action: str) -> PurchaseLine:
    line = get_line(db, org_id, line_id)
    if line.review_reason is None:
        raise CostingError("Nothing to review on this purchase")
    if action == "keep":
        line.review_reason = None
    elif action == "unlink":
        for alloc in line_allocations(db, line, statuses=("active", "orphaned")):
            db.delete(alloc)
        db.flush()
        line.review_reason = None
        derive_state(db, line)
    else:
        raise CostingError("action must be 'keep' or 'unlink'")
    db.flush()
    return line


def edit_allocations(db: Session, org_id: UUID, line_id, changes: list) -> PurchaseLine:
    line = get_line(db, org_id, line_id)
    if line.amount_ex_tax is None:
        raise CostingError("This purchase has no amount in your base currency yet")
    if not isinstance(changes, list) or not changes:
        raise CostingError("Send at least one allocation")
    current = {a.id: a for a in line_allocations(db, line, statuses=("active", "orphaned"))}
    for change in changes:
        if not isinstance(change, dict):
            raise CostingError("Each allocation is an object")
        alloc = current.get(_uuid(change.get("id")))
        if alloc is None:
            raise CostingNotFoundError("Allocation not found")
        if _d(alloc.amount) < 0:
            amount = Decimal(str(change.get("amount")))
            if amount >= 0:
                raise CostingError("A refund amount is negative")
            alloc.amount = _q(amount)
        else:
            alloc.amount = parse_amount(change.get("amount"), "Amount", allow_zero=True)
            if change.get("quantity") not in (None, ""):
                quantity = parse_amount(change.get("quantity"), "Quantity", allow_zero=False)
                flow = db.query(CostFlow).filter(CostFlow.org_id == org_id, CostFlow.id == alloc.cost_flow_id).one()
                others = _flow_priced_quantity(db, org_id, flow.id) - _d(alloc.quantity)
                if quantity + others > _d(flow.quantity):
                    raise CostingError("That's more than the lot received")
                alloc.quantity = quantity
        alloc.status = "active"
    db.flush()
    amount = _d(line.amount_ex_tax)
    used = allocated(db, line) + _d(line.not_stock_amount)
    if not _same_sign(used, amount) or abs(used) > abs(amount):
        raise CostingError("Allocations can't add up to more than the purchase")
    derive_state(db, line)
    db.flush()
    return line


# --- candidates ---------------------------------------------------------------------------------------


def _norm(text: str | None) -> str:
    return " ".join((text or "").casefold().split())


def candidates(db: Session, org_id: UUID, line_id) -> list[dict]:
    line = get_line(db, org_id, line_id, for_update=False)
    doc = _document(db, line)
    if doc.document_date is None:
        return []
    start, end = doc.document_date - timedelta(days=3), doc.document_date + timedelta(days=14)
    lots = (
        db.query(InventoryItem)
        .filter(InventoryItem.org_id == org_id, InventoryItem.inventory_type.in_(RECORDABLE_TYPES))
        .all()
    )
    payee = _norm(doc.payee_name)
    found = []
    for item in lots:
        when = item.purchase_date or (item.created_at.date() if item.created_at else None)
        if when is None or not (start <= when <= end):
            continue
        if _link_problem(db, org_id, item):
            continue
        if not all(f.kind in DIRECT_KINDS for f in _in_flows(db, org_id, item.id)):
            continue
        found.append(
            (
                0 if payee and _norm(item.supplier) == payee else 1,
                abs((when - doc.document_date).days),
                item.created_at,
                item,
            )
        )
    found.sort(key=lambda r: (r[0], r[1], r[2]))
    return [
        {
            "inventory_item_id": str(item.id),
            "name": item.name,
            "quantity": str(item.quantity),
            "unit": item.unit,
            "supplier": item.supplier,
            "purchase_date": item.purchase_date.isoformat() if item.purchase_date else None,
            "same_supplier": same == 0,
        }
        for same, _, _, item in found
    ]


def _in_flows(db: Session, org_id: UUID, item_id: UUID) -> list[CostFlow]:
    return (
        db.query(CostFlow)
        .filter(CostFlow.org_id == org_id, CostFlow.inventory_item_id == item_id, CostFlow.direction == "in")
        .all()
    )


# --- the list and its tabs ----------------------------------------------------------------------------


def tab_of(line: PurchaseLine, doc: PurchaseDocument, start_date: date | None) -> str | None:
    """Spec "Tabs": one rule, first match wins."""
    if line.review_reason:
        return "to_record"
    if line.superseded_at is not None or doc.status != "active" or line.treatment != "stock":
        return None
    if line.amount_ex_tax is None:
        return None
    if line.state in ("open", "partly_recorded"):
        if start_date is not None and doc.document_date is not None and doc.document_date < start_date:
            return None
        return "to_record"
    return {"recorded": "recorded", "skipped": "skipped", "not_stock": "not_stock"}.get(line.state)


def list_purchases(db: Session, org_id: UUID, tab: str, date_from: date | None, date_to: date | None) -> dict:
    if tab not in TABS:
        raise CostingError(f"tab must be one of {', '.join(TABS)}")
    settings = db.query(CostingSettings).filter(CostingSettings.org_id == org_id).one_or_none()
    start_date = settings.start_date if settings else None
    rows = (
        db.query(PurchaseLine, PurchaseDocument)
        .join(
            PurchaseDocument,
            (PurchaseDocument.org_id == PurchaseLine.org_id) & (PurchaseDocument.id == PurchaseLine.document_id),
        )
        .filter(PurchaseLine.org_id == org_id, PurchaseDocument.org_id == org_id)
        .order_by(PurchaseDocument.document_date.desc(), PurchaseLine.position)
        .all()
    )
    counts = {t: 0 for t in TABS}
    cards = []
    for line, doc in rows:
        if date_from and (doc.document_date is None or doc.document_date < date_from):
            continue
        if date_to and (doc.document_date is None or doc.document_date > date_to):
            continue
        which = tab_of(line, doc, start_date)
        if which is None:
            continue
        counts[which] += 1
        if which == tab:
            cards.append(card(db, line, doc))
    return {"tab": tab, "counts": counts, "cards": cards}


def card(db: Session, line: PurchaseLine, doc: PurchaseDocument) -> dict:
    remaining = open_amount(db, line)
    return {
        "line_id": str(line.id),
        "document": {
            "payee": doc.payee_name,
            "date": doc.document_date.isoformat() if doc.document_date else None,
            "reference": doc.reference,
            "kind": doc.kind,
            "status": doc.status,
        },
        "description": line.description,
        "account": {"code": line.account_code, "name": line.account_name},
        "amount": None if line.amount_ex_tax is None else str(_q(_d(line.amount_ex_tax))),
        "open": None if remaining is None else str(_q(remaining)),
        "not_stock_amount": str(_q(_d(line.not_stock_amount))),
        "state": line.state,
        "review_reason": line.review_reason,
        "allocations": [
            {
                "id": str(a.id),
                "inventory_item_id": str(a.inventory_item_id),
                "amount": str(_q(_d(a.amount))),
                "quantity": str(_d(a.quantity)),
                "status": a.status,
            }
            for a in line_allocations(db, line, statuses=("active", "orphaned"))
        ],
    }


# --- when Xero changes a line later --------------------------------------------------------------------


def _has_allocations(db: Session, line: PurchaseLine) -> bool:
    return bool(line_allocations(db, line, statuses=("active", "orphaned")))


def _orphan(db: Session, line: PurchaseLine, reason: str) -> None:
    allocs = line_allocations(db, line, statuses=("active",))
    for alloc in allocs:
        alloc.status = "orphaned"
    if allocs or _has_allocations(db, line):
        line.review_reason = reason


def on_line_amount_changed(db: Session, line: PurchaseLine, old_amount: Decimal | None) -> None:
    """Rescale what was recorded against a line whose Xero amount changed (spec table)."""
    new_amount = _d(line.amount_ex_tax) if line.amount_ex_tax is not None else None
    if old_amount is None or new_amount is None or old_amount == new_amount:
        return
    allocs = line_allocations(db, line, statuses=("active",))
    if new_amount == 0 or not _same_sign(new_amount, old_amount) or old_amount == 0:
        if allocs:
            _orphan(db, line, "amount_changed")
        line.not_stock_amount = ZERO
        derive_state(db, line, keep_skipped=True)
        return
    factor = new_amount / old_amount
    line.not_stock_amount = _q(_d(line.not_stock_amount) * factor)
    if allocs:
        before_total = sum((_d(a.amount) for a in allocs), ZERO)
        scaled = {a.id: _q(_d(a.amount) * factor) for a in allocs}
        expected = _q(before_total * factor)
        remainder = expected - sum(scaled.values(), ZERO)
        if remainder:
            biggest = max(allocs, key=lambda a: (abs(_d(a.amount)), -a.created_at.timestamp()))
            scaled[biggest.id] += remainder
        for alloc in allocs:
            alloc.amount = scaled[alloc.id]
        line.review_reason = "amount_changed"
    derive_state(db, line, keep_skipped=True)


def on_line_treatment_changed(db: Session, line: PurchaseLine, old: str | None, new: str | None) -> None:
    if old == new:
        return
    if new != "stock" and _has_allocations(db, line):
        line.review_reason = "recoded"


def on_line_gone(db: Session, line: PurchaseLine) -> None:
    """Voided in Xero, superseded, or retired: what was recorded goes to review."""
    _orphan(db, line, "deleted_in_xero")
