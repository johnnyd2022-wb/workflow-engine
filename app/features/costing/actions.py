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

from sqlalchemy import func
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
    """With ``for_update``, locks in the one order every writer uses: document, then line
    (then lots, sorted by id). The sync's void/restore path takes the same order."""
    uid = _uuid(line_id)
    if uid is None:
        raise CostingNotFoundError("Purchase not found")
    line = db.query(PurchaseLine).filter(PurchaseLine.org_id == org_id, PurchaseLine.id == uid).one_or_none()
    if line is None:
        raise CostingNotFoundError("Purchase not found")
    if for_update:
        db.query(PurchaseDocument).filter(
            PurchaseDocument.org_id == org_id, PurchaseDocument.id == line.document_id
        ).with_for_update().one()
        line = (
            db.query(PurchaseLine)
            .filter(PurchaseLine.org_id == org_id, PurchaseLine.id == uid)
            .with_for_update()
            .populate_existing()
            .one()
        )
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
    db.flush()  # the session doesn't autoflush: allocation changes must be visible to the query below
    amount = _d(line.amount_ex_tax) if line.amount_ex_tax is not None else None
    rows = line_allocations(db, line)
    has_allocation = bool(rows)  # "something was allocated" is a row, even at $0
    alloc = sum((_d(a.amount) for a in rows), ZERO)
    not_stock = _d(line.not_stock_amount)
    if amount is None:
        line.state = "open"
        return
    remaining = amount - alloc - not_stock
    if has_allocation and remaining == 0:
        line.state = "recorded"
    elif not has_allocation and not_stock == amount and amount != 0:
        line.state = "not_stock"
    elif not has_allocation and amount == 0 and line.state == "not_stock":
        pass  # a $0 line someone marked not stock stays decided (reopen sets it open first)
    elif has_allocation:
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


def _lock_lots(db: Session, org_id: UUID, entries: list) -> dict:
    """Validate each lot appears once, then lock them sorted by id (no lock-order deadlocks)."""
    ids = []
    for entry in entries:
        if not isinstance(entry, dict):
            raise CostingError("Each lot is an object")
        uid = _uuid(entry.get("inventory_item_id"))
        if uid is None:
            raise CostingNotFoundError("Lot not found")
        if uid in ids:
            raise CostingError("Each lot can appear only once")
        ids.append(uid)
    locked = {}
    for uid in sorted(ids, key=str):
        locked[uid] = _qualifying_lot(db, org_id, uid)
    return locked


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
    locked = _lock_lots(db, org_id, lots)
    plan = []
    for entry in lots:
        item = locked[_uuid(entry.get("inventory_item_id"))]
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


def _refund_amount(raw) -> Decimal:
    if isinstance(raw, str) and raw.strip().startswith("-"):
        value = parse_amount(raw.strip()[1:], "Amount", allow_zero=False)
    elif isinstance(raw, int | float) and not isinstance(raw, bool) and raw < 0:
        value = parse_amount(str(-raw), "Amount", allow_zero=False)
    else:
        raise CostingError("A refund amount is a negative number")
    return -value


def refund(db: Session, org_id: UUID, line_id, lots: list, user_id=None) -> PurchaseLine:
    line = get_line(db, org_id, line_id)
    doc, remaining = _actionable(db, line)
    if doc.kind != "refund":
        raise CostingError("Only a refund can reduce the cost of stock")
    if not isinstance(lots, list) or not lots:
        raise CostingError("Choose at least one lot")
    locked = _lock_lots(db, org_id, lots)
    plan = []
    for entry in lots:
        item = locked[_uuid(entry.get("inventory_item_id"))]
        if item.contract_customer_id:
            raise CostingError("Customer-owned stock costs you nothing")
        plan.append((item, _refund_amount(entry.get("amount"))))
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
    if _d(line.amount_ex_tax) == 0 and not line_allocations(db, line):
        line.state = "not_stock"  # nothing to subtract: the decision itself is the state
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
    line.state = "open"
    derive_state(db, line)
    db.flush()
    return line


def review(db: Session, org_id: UUID, line_id, action: str) -> PurchaseLine:
    line = get_line(db, org_id, line_id)
    if line.amount_ex_tax is None:
        raise CostingError("This purchase has no amount in your base currency yet")
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
    doc = _document(db, line)
    purchase_live = doc.status == "active" and line.superseded_at is None
    for item_id in sorted({a.inventory_item_id for a in current.values()}, key=str):
        _qualifying_lot(db, org_id, item_id)  # lock, in id order
    seen = set()
    for change in changes:
        if not isinstance(change, dict):
            raise CostingError("Each allocation is an object")
        alloc = current.get(_uuid(change.get("id")))
        if alloc is None:
            raise CostingNotFoundError("Allocation not found")
        if alloc.id in seen:
            raise CostingError("Each allocation can appear only once")
        seen.add(alloc.id)
        if _d(alloc.amount) < 0:
            alloc.amount = _refund_amount(change.get("amount"))
        else:
            alloc.amount = parse_amount(change.get("amount"), "Amount", allow_zero=True)
            if change.get("quantity") not in (None, ""):
                quantity = parse_amount(change.get("quantity"), "Quantity", allow_zero=False)
                flow = db.query(CostFlow).filter(CostFlow.org_id == org_id, CostFlow.id == alloc.cost_flow_id).one()
                others = _flow_priced_quantity(db, org_id, flow.id) - _d(alloc.quantity)
                if quantity + others > _d(flow.quantity):
                    raise CostingError("That's more than the lot received")
                alloc.quantity = quantity
        if purchase_live:  # an edit never revives a purchase Xero no longer has
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


def tab_of(line: PurchaseLine, doc: PurchaseDocument, start_date: date | None, historical: bool = False) -> str | None:
    """Spec "Tabs": one rule, first match wins. Historical mode (8.1c-2) ignores the start date
    and lists skipped lines as actionable."""
    if line.review_reason:
        return "to_record"
    if line.superseded_at is not None or doc.status != "active" or line.treatment != "stock":
        return None
    if line.amount_ex_tax is None:
        return None
    if historical and line.state == "skipped":
        return "to_record"
    if line.state in ("open", "partly_recorded"):
        if (
            not historical
            and start_date is not None
            and doc.document_date is not None
            and doc.document_date < start_date
        ):
            return None
        return "to_record"
    return {"recorded": "recorded", "skipped": "skipped", "not_stock": "not_stock"}.get(line.state)


def list_purchases(
    db: Session, org_id: UUID, tab: str, date_from: date | None, date_to: date | None, historical: bool = False
) -> dict:
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
    from app.features.costing.rules import active_rules

    rules = active_rules(db, org_id)
    counts = {t: 0 for t in TABS}
    cards = []
    for line, doc in rows:
        if date_from and (doc.document_date is None or doc.document_date < date_from):
            continue
        if date_to and (doc.document_date is None or doc.document_date > date_to):
            continue
        which = tab_of(line, doc, start_date, historical)
        if which is None:
            continue
        counts[which] += 1
        if which == tab:
            entry = card(db, line, doc, rules=rules)
            if historical and which == "not_stock":
                entry["undo"] = True
            cards.append(entry)
    return {"tab": tab, "counts": counts, "cards": cards}


def card(db: Session, line: PurchaseLine, doc: PurchaseDocument, *, rules=None) -> dict:
    remaining = open_amount(db, line)
    return {
        "prefill": prefill(db, line, doc, remaining, rules),
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


def _orphan(db: Session, line: PurchaseLine, reason: str, cause: str) -> None:
    """``cause`` (void | gone | amount) is kept on each allocation, so a later restore of the
    document only revives what the void orphaned."""
    allocs = line_allocations(db, line, statuses=("active",))
    for alloc in allocs:
        alloc.status = "orphaned"
        alloc.orphaned_by = cause
    if allocs or _has_allocations(db, line):
        line.review_reason = reason


def lock_lines(db: Session, org_id: UUID, line_ids) -> list[PurchaseLine]:
    """Lock lines in the one order every writer uses: their documents (by id), then the lines
    (by id). Account-wide paths call this before inspecting allocations."""
    ids = sorted({lid for lid in line_ids}, key=str)
    if not ids:
        return []
    doc_ids = sorted(
        {
            r[0]
            for r in db.query(PurchaseLine.document_id).filter(PurchaseLine.org_id == org_id, PurchaseLine.id.in_(ids))
        },
        key=str,
    )
    for doc_id in doc_ids:
        db.query(PurchaseDocument).filter(
            PurchaseDocument.org_id == org_id, PurchaseDocument.id == doc_id
        ).with_for_update().one()
    return (
        db.query(PurchaseLine)
        .filter(PurchaseLine.org_id == org_id, PurchaseLine.id.in_(ids))
        .order_by(PurchaseLine.id)
        .with_for_update()
        .populate_existing()
        .all()
    )


def on_line_amount_changed(db: Session, line: PurchaseLine, old_amount: Decimal | None) -> None:
    """Rescale what was recorded against a line whose Xero amount changed (spec table)."""
    new_amount = _d(line.amount_ex_tax) if line.amount_ex_tax is not None else None
    if old_amount is None or old_amount == new_amount:
        return
    allocs = line_allocations(db, line, statuses=("active",))
    if new_amount is None or new_amount == 0 or old_amount == 0 or not _same_sign(new_amount, old_amount):
        # No longer valued (needs a rate), zero, or the other sign: never rescale across that.
        if allocs:
            _orphan(db, line, "amount_changed", "amount")
        line.not_stock_amount = ZERO
        derive_state(db, line, keep_skipped=True)
        return
    factor = new_amount / old_amount
    old_not_stock = _d(line.not_stock_amount)
    if not allocs:
        line.not_stock_amount = _q(old_not_stock * factor)
        derive_state(db, line, keep_skipped=True)
        return
    # Round the line's whole used amount once, then split it: not-stock first, the rest across
    # the allocations, so used never exceeds the new amount and the remainder lands somewhere.
    old_alloc = sum((_d(a.amount) for a in allocs), ZERO)
    used_total = _q((old_alloc + old_not_stock) * factor)
    if abs(used_total) > abs(new_amount):
        used_total = new_amount
    new_not_stock = _q(old_not_stock * factor)
    if abs(new_not_stock) > abs(used_total):
        new_not_stock = used_total
    target = used_total - new_not_stock
    scaled = {a.id: _q(_d(a.amount) * factor) for a in allocs}
    remainder = target - sum(scaled.values(), ZERO)
    ordered = sorted(allocs, key=lambda a: (-abs(_d(a.amount)), a.created_at, str(a.id)))
    if remainder > 0:
        scaled[ordered[0].id] += remainder
    elif remainder < 0:  # take it from the largest first, never below zero
        for alloc in ordered:
            take = min(-remainder, scaled[alloc.id])
            scaled[alloc.id] -= take
            remainder += take
            if remainder == 0:
                break
    for alloc in allocs:
        alloc.amount = scaled[alloc.id]
    line.not_stock_amount = new_not_stock
    line.review_reason = "amount_changed"
    derive_state(db, line, keep_skipped=True)


def on_document_restored(db: Session, line: PurchaseLine) -> None:
    """A voided purchase made active again in Xero: only what the void orphaned is priced by it
    again, and only if the line still has an amount (not superseded, not needing a rate)."""
    if line.superseded_at is not None or line.amount_ex_tax is None:
        return
    orphaned = [a for a in line_allocations(db, line, statuses=("orphaned",)) if a.orphaned_by == "void"]
    for alloc in orphaned:
        alloc.status = "active"
        alloc.orphaned_by = None
    db.flush()  # no autoflush: the query below must see the reactivated rows
    still = line_allocations(db, line, statuses=("orphaned",))
    if orphaned and not still and line.review_reason == "deleted_in_xero":
        line.review_reason = None
    db.flush()
    used = allocated(db, line) + _d(line.not_stock_amount)
    amount = _d(line.amount_ex_tax)
    if orphaned and (not _same_sign(used, amount) or abs(used) > abs(amount)):
        line.review_reason = "amount_changed"  # changed while voided: a person decides
    derive_state(db, line)


def on_line_treatment_changed(db: Session, line: PurchaseLine, old: str | None, new: str | None) -> None:
    if old == new:
        return
    if new != "stock" and _has_allocations(db, line):
        line.review_reason = "recoded"


def on_line_gone(db: Session, line: PurchaseLine, cause: str = "gone") -> None:
    """Voided in Xero (cause ``void``), superseded or retired (``gone``): what was recorded
    goes to review."""
    _orphan(db, line, "deleted_in_xero", cause)


# --- pre-fill (8.1c-2) -----------------------------------------------------------------------------


def _ask_flags(row: dict) -> list[str]:
    ask = []
    if row.get("quantity_mode") == "ask":
        ask.append("quantity")
    if row.get("ask_batch_number"):
        ask.append("batch_number")
    if row.get("ask_expiry"):
        ask.append("expiry")
    return ask


def prefill(db: Session, line: PurchaseLine, doc: PurchaseDocument, remaining: Decimal | None, rules=None):
    """Spec "Pre-fill": the winning stock rule's template, else last time for this payee, else
    one empty row for the whole open amount."""
    if doc.kind != "spend" or remaining is None:
        return None
    from app.features.costing.rules import active_rules, normalise, winner

    rules = active_rules(db, line.org_id) if rules is None else rules
    rule = winner(rules, line.account_code, doc.payee_name, line.description)
    if rule is not None and rule.treatment == "stock" and rule.template:
        rows, used, rest_index = [], ZERO, None
        for i, t in enumerate(rule.template):
            if t.get("share") == "rest":
                amount = None
                rest_index = i
            else:
                amount = _q(remaining * _d(t["share"]) / 100)
                used += amount
            rows.append([t, amount])
        if rest_index is not None:
            rows[rest_index][1] = max(ZERO, remaining - used)
        out = []
        for t, amount in rows:
            amount = amount if amount is not None else ZERO
            mode = t.get("quantity_mode")
            if mode == "fixed":
                quantity = str(_d(t["quantity"]))
            elif mode == "from_price" and _d(t.get("unit_price")) > 0:
                quantity = str(_q(amount / _d(t["unit_price"])))
            else:
                quantity = None
            out.append(
                {
                    "name": t["name"],
                    "inventory_type": t.get("inventory_type", "raw_material"),
                    "unit": t["unit"],
                    "quantity": quantity,
                    "amount": str(_q(amount)),
                    "ask": _ask_flags(t),
                }
            )
        return {"source": "rule", "rule_id": str(rule.id), "rows": out}

    payee = normalise(doc.payee_name)
    if payee:
        previous = (
            db.query(PurchaseLine, PurchaseDocument)
            .join(
                PurchaseDocument,
                (PurchaseDocument.org_id == PurchaseLine.org_id) & (PurchaseDocument.id == PurchaseLine.document_id),
            )
            .filter(
                PurchaseLine.org_id == line.org_id,
                PurchaseLine.id != line.id,
                PurchaseLine.state.in_(("recorded", "partly_recorded")),
                PurchaseDocument.kind == "spend",
                # same normalised payee, in SQL, so older purchases aren't cut off by newer ones
                func.lower(func.regexp_replace(func.btrim(PurchaseDocument.payee_name), r"\s+", " ", "g")) == payee,
            )
            .order_by(PurchaseDocument.document_date.desc(), PurchaseLine.updated_at.desc())
            .limit(20)
            .all()
        )
        for prev, prev_doc in previous:
            if normalise(prev_doc.payee_name) != payee or not prev.amount_ex_tax:
                continue
            allocs = [a for a in line_allocations(db, prev) if _d(a.amount) > 0]
            if not allocs:
                continue
            out = []
            for a in allocs:
                item = (
                    db.query(InventoryItem)
                    .filter(InventoryItem.org_id == line.org_id, InventoryItem.id == a.inventory_item_id)
                    .one()
                )
                out.append(
                    {
                        "name": item.name,
                        "inventory_type": item.inventory_type,
                        "unit": item.unit,
                        "quantity": str(_d(a.quantity)),
                        "amount": str(_q(remaining * _d(a.amount) / _d(prev.amount_ex_tax))),
                        "ask": [],
                    }
                )
            return {"source": "last_time", "rule_id": None, "rows": out}

    return {
        "source": "none",
        "rule_id": None,
        "rows": [
            {
                "name": None,
                "inventory_type": InventoryType.RAW_MATERIAL.value,
                "unit": None,
                "quantity": None,
                "amount": str(_q(remaining)),
                "ask": ["name", "unit", "quantity"],
            }
        ],
    }
