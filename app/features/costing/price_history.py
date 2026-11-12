"""Read-only material price history for live-cogs 8.1f-3a."""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import and_
from sqlalchemy.orm import Session

from app.core.db.models.inventory_item import InventoryItem
from app.features.costing.engine import CostEngine, money, normalise, unit_str
from app.features.costing.models import LotCostEntry, PurchaseAllocation, PurchaseDocument, PurchaseLine
from app.features.costing.purchase_sources import nz_today
from app.features.costing.service import CostingError, CostingNotFoundError

ZERO = Decimal("0")


def _month(value: str | None, label: str) -> date | None:
    if value is None:
        return None
    try:
        parsed = datetime.strptime(value, "%Y-%m").date()
    except (TypeError, ValueError):
        raise CostingError(f"{label} must be YYYY-MM") from None
    if parsed.strftime("%Y-%m") != value:
        raise CostingError(f"{label} must be YYYY-MM")
    return parsed.replace(day=1)


def _next_month(value: date) -> date:
    return date(value.year + (value.month == 12), value.month % 12 + 1, 1)


def _month_key(value: date | datetime) -> str:
    return value.strftime("%Y-%m")


def _range(date_from: str | None, date_to: str | None) -> tuple[date, date]:
    start, end = _month(date_from, "from"), _month(date_to, "to")
    if start is None and end is None:
        end = nz_today().replace(day=1)
        start = date(end.year - 1, end.month, 1)
        start = _next_month(start)  # twelve months, this one included
    elif start is None or end is None:
        raise CostingError("Send both from and to (YYYY-MM)")
    if start > end:
        raise CostingError("from must be on or before to")
    count = (end.year - start.year) * 12 + end.month - start.month + 1
    if count > 36:
        raise CostingError("History range cannot exceed 36 months")
    return start, end


def _units(lots: list[InventoryItem]) -> str:
    counts = Counter((lot.unit or "").strip() for lot in lots)
    return min(counts, key=lambda unit: (-counts[unit], unit.casefold()))


def _facts(db: Session, org_id: UUID, lots: list[InventoryItem]):
    ids = [lot.id for lot in lots]
    if not ids:
        return [], []
    allocations = (
        db.query(PurchaseAllocation, PurchaseLine, PurchaseDocument)
        .join(
            PurchaseLine,
            and_(
                PurchaseLine.org_id == PurchaseAllocation.org_id, PurchaseLine.id == PurchaseAllocation.purchase_line_id
            ),
        )
        .join(
            PurchaseDocument,
            and_(PurchaseDocument.org_id == PurchaseLine.org_id, PurchaseDocument.id == PurchaseLine.document_id),
        )
        .filter(
            PurchaseAllocation.org_id == org_id,
            PurchaseAllocation.inventory_item_id.in_(ids),
            PurchaseAllocation.status == "active",
            PurchaseLine.superseded_at.is_(None),
            PurchaseDocument.status == "active",
            PurchaseDocument.document_date.is_not(None),
        )
        .all()
    )
    entries = (
        db.query(LotCostEntry)
        .filter(
            LotCostEntry.org_id == org_id,
            LotCostEntry.inventory_item_id.in_(ids),
            LotCostEntry.is_active.is_(True),
        )
        .all()
    )
    return allocations, entries


def _history(db: Session, org_id: UUID, material: str, date_from: str | None, date_to: str | None) -> dict:
    start, end = _range(date_from, date_to)
    norm = normalise(material)
    lots = db.query(InventoryItem).filter(InventoryItem.org_id == org_id).order_by(InventoryItem.id).all()
    lots = [lot for lot in lots if normalise(lot.name) == norm and not lot.contract_customer_id]
    if not lots:
        raise CostingNotFoundError("Material not found")

    unit = _units(lots)
    by_id = {lot.id: lot for lot in lots}
    allocations, entries = _facts(db, org_id, lots)
    engine = CostEngine(db, org_id)
    engine.prime(by_id)
    months = {}
    latest = None

    def add_fact(lot, when, amount, quantity, source, purchase_id=None):
        nonlocal latest
        fact_month = _month_key(when)
        in_range = start.strftime("%Y-%m") <= fact_month <= end.strftime("%Y-%m")
        unit_price = amount / quantity if quantity > ZERO else None
        factor = engine._unit_factor(unit, lot.unit)
        row = (
            months.setdefault(
                fact_month,
                {"amount": ZERO, "quantity": ZERO, "prices": [], "purchases": set(), "unconverted": 0},
            )
            if in_range
            else None
        )
        if factor is None:
            if row is not None:
                row["unconverted"] += 1
            return
        converted_amount = amount
        converted_quantity = quantity / factor if quantity > ZERO else ZERO
        converted_price = unit_price * factor if unit_price is not None else None
        if unit_price is not None:
            when_key = when.date() if isinstance(when, datetime) else when
            key = (when_key, str(purchase_id or ""), source)
            if latest is None or key > latest[0]:
                latest = (key, {"unit_price": unit_str(converted_price), "date": when.isoformat(), "source": source})
        if row is not None:
            row["amount"] += converted_amount
            row["quantity"] += converted_quantity
            if converted_price is not None:
                row["prices"].append(converted_price)
            if purchase_id is not None and amount > ZERO:
                row["purchases"].add(purchase_id)

    for allocation, _line, document in allocations:
        item = by_id[allocation.inventory_item_id]
        amount, quantity = Decimal(str(allocation.amount)), Decimal(str(allocation.quantity))
        if not amount.is_finite() or not quantity.is_finite():
            continue
        # Refunds carry no quantity and reduce the amount in their purchase document month.
        if amount > ZERO and quantity > ZERO:
            add_fact(item, document.document_date, amount, quantity, "purchase", str(document.id))
        elif amount < ZERO:
            add_fact(item, document.document_date, amount, ZERO, "refund", str(document.id))
    for entry in entries:
        item = by_id[entry.inventory_item_id]
        when = entry.created_at or datetime.combine(date.today(), datetime.min.time(), UTC)
        add_fact(item, when, Decimal(str(entry.amount)), Decimal(str(entry.quantity)), entry.kind)

    month_rows = []
    cursor = start
    while cursor <= end:
        key = cursor.strftime("%Y-%m")
        row = months.get(key)
        if row:
            average = row["amount"] / row["quantity"] if row["quantity"] > ZERO else None
            prices = row["prices"]
            month_rows.append(
                {
                    "month": key,
                    "unit": unit,
                    "amount": money(row["amount"]),
                    "priced_quantity": str(row["quantity"]),
                    "average_unit_cost": unit_str(average),
                    "purchases": len(row["purchases"]),
                    "min_unit_price": unit_str(min(prices)) if prices else None,
                    "max_unit_price": unit_str(max(prices)) if prices else None,
                    "unconverted": row["unconverted"],
                }
            )
        cursor = _next_month(cursor)

    lot_rows = []
    for item in lots:
        cost = engine._solve(("lot", item.id))
        public_cost = cost.unit_known if cost.status in ("actual", "estimated") else None
        lot_rows.append(
            {
                "id": str(item.id),
                "name": item.name,
                "unit": item.unit,
                "unit_cost": unit_str(public_cost),
                "status": cost.status,
            }
        )
    return {
        "name": lots[0].name,
        "unit": unit,
        "from": start.strftime("%Y-%m"),
        "to": end.strftime("%Y-%m"),
        "months": month_rows,
        "latest": latest[1] if latest else None,
        "lots": lot_rows,
    }


def material_history(db: Session, org_id: UUID, material: str, date_from: str | None, date_to: str | None) -> dict:
    return _history(db, org_id, material, date_from, date_to)


def list_materials(db: Session, org_id: UUID) -> list[dict]:
    lots = db.query(InventoryItem).filter(InventoryItem.org_id == org_id).order_by(InventoryItem.name).all()
    groups: dict[str, list[InventoryItem]] = defaultdict(list)
    for item in lots:
        if not item.contract_customer_id:
            groups[normalise(item.name)].append(item)
    all_lots = [item for group in groups.values() for item in group]
    allocations, entries = _facts(db, org_id, all_lots)
    engine = CostEngine(db, org_id)
    allocations_by_item: dict[UUID, list] = defaultdict(list)
    entries_by_item: dict[UUID, list] = defaultdict(list)
    for allocation_row in allocations:
        allocations_by_item[allocation_row[0].inventory_item_id].append(allocation_row)
    for entry in entries:
        entries_by_item[entry.inventory_item_id].append(entry)
    results = []
    for group in groups.values():
        unit = _units(group)
        group_allocations = [row for item in group for row in allocations_by_item[item.id]]
        group_entries = [entry for item in group for entry in entries_by_item[item.id]]
        facts = _history_facts_for_list(engine, group, unit, group_allocations, group_entries)
        if facts is not None:
            results.append(facts)
    return sorted(results, key=lambda row: (normalise(row["name"]), row["name"].casefold()))


def _history_facts_for_list(engine, lots, unit, allocations, entries) -> dict | None:
    """Latest direct price fact, bulk-loaded for this material group."""
    by_id = {item.id: item for item in lots}
    latest = None
    for allocation, _line, document in allocations:
        if allocation.amount <= ZERO or allocation.quantity <= ZERO or document.document_date is None:
            continue
        lot = by_id[allocation.inventory_item_id]
        factor = engine._unit_factor(unit, lot.unit)
        if factor is None:
            continue
        key = (document.document_date, str(document.id), "purchase")
        candidate = (key, Decimal(str(allocation.amount)) / Decimal(str(allocation.quantity)) * factor)
        if latest is None or candidate[0] > latest[0]:
            latest = candidate
    for entry in entries:
        if not entry.quantity or entry.quantity <= ZERO:
            continue
        lot = by_id[entry.inventory_item_id]
        factor = engine._unit_factor(unit, lot.unit)
        if factor is None:
            continue
        key = (entry.created_at.date() if entry.created_at else date.min, str(entry.id), entry.kind)
        candidate = (key, Decimal(str(entry.amount)) / Decimal(str(entry.quantity)) * factor)
        if latest is None or candidate[0] > latest[0]:
            latest = candidate
    if latest is None:
        return None
    return {
        "name": min((item.name for item in lots), key=lambda name: (normalise(name), name.casefold())),
        "unit": unit,
        "latest_unit_price": unit_str(latest[1]),
        "latest_date": latest[0][0].isoformat(),
    }
