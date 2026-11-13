"""Read-only material price history for live-cogs 8.1f-3a."""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import UTC, date, datetime, time
from decimal import Decimal
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import and_
from sqlalchemy.orm import Session

from app.core.db.models.inventory_item import InventoryItem
from app.features.costing.engine import UNKNOWN, CostEngine, TooLargeError, money, normalise, unit_str
from app.features.costing.models import LotCostEntry, PurchaseAllocation, PurchaseDocument, PurchaseLine
from app.features.costing.purchase_sources import nz_today
from app.features.costing.service import CostingError, CostingNotFoundError

ZERO = Decimal("0")
NZ = ZoneInfo("Pacific/Auckland")


def _nz_datetime(value: datetime) -> datetime:
    """Interpret stored naive timestamps as UTC and return the local NZ instant."""
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(NZ)


def _purchase_datetime(value: date) -> datetime:
    """A date-only purchase is ordered at the end of its NZ document date."""
    return datetime.combine(value, time.max, NZ)


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
    engine, primed = _primed(db, org_id, by_id)
    entries_by_lot: dict[UUID, list[LotCostEntry]] = defaultdict(list)
    for entry in entries:
        entries_by_lot[entry.inventory_item_id].append(entry)
    months = {}
    latest = None

    def add_fact(lot, when, amount, quantity, source, purchase_id=None, fact_id=None):
        nonlocal latest
        local_when = _nz_datetime(when) if isinstance(when, datetime) else when
        fact_month = _month_key(local_when)
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
                if quantity > ZERO:
                    row["unconverted"] += 1
                    if purchase_id is not None:
                        row["purchases"].add(purchase_id)
            return  # a refund on a lot priced in another unit belongs to a price left out above
        converted_amount = amount
        converted_quantity = quantity / factor if quantity > ZERO else ZERO
        converted_price = unit_price * factor if unit_price is not None else None
        if unit_price is not None:
            if isinstance(local_when, datetime):
                when_key = local_when
            else:
                when_key = _purchase_datetime(local_when)
            key = (when_key, str(purchase_id or ""), source, str(fact_id or ""))
            if latest is None or key > latest[0]:
                latest = (
                    key,
                    {
                        "unit_price": unit_str(converted_price),
                        "date": local_when.isoformat(),
                        "source": source,
                    },
                )
        if row is not None:
            row["amount"] += converted_amount
            row["quantity"] += converted_quantity
            if converted_price is not None:
                row["prices"].append(converted_price)
            if purchase_id is not None and quantity > ZERO:
                row["purchases"].add(purchase_id)

    too_large = False
    try:
        facts = _effective_facts(engine if primed else CostEngine(db, org_id), by_id, allocations, entries_by_lot)
    except TooLargeError:  # more history than the engine's budget: say so rather than fail
        facts, too_large = [], True
        engine, primed = CostEngine(db, org_id), False  # each lot below gets its own engine
    for fact in facts:
        add_fact(*fact)

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
        try:
            cost = (engine if primed else CostEngine(db, org_id))._solve(("lot", item.id))
        except TooLargeError:  # a history too long to cost: unknown, as the lot-cost API says
            status, public_cost = UNKNOWN, None
        else:
            status = cost.status
            public_cost = cost.unit_known if cost.status in ("actual", "estimated") else None
        lot_rows.append(
            {
                "id": str(item.id),
                "name": item.name,
                "unit": item.unit,
                "unit_cost": unit_str(public_cost),
                "status": status,
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
        "too_large": too_large,
    }


def _effective_facts(engine, by_id, allocations, entries_by_lot):
    """Every price fact the engine would use for these lots, as
    (lot, when, amount, quantity, source, purchase_id, fact_id): purchases, refunds, flow
    entries capped together with flow allocations, and a whole-lot price only on the direct
    quantity nothing else priced. History and the picker both read this, so they agree."""
    facts = []

    def emit(lot, when, amount, quantity, source, purchase_id=None, fact_id=None):
        facts.append((lot, when, amount, quantity, source, purchase_id, fact_id))

    direct_flows = {}
    for item_id in by_id:
        direct_flows[item_id] = [
            flow for flow in engine._in_flows(item_id) if flow.kind not in ("produced", "reconciled_in", "transfer_in")
        ]
    direct_flow_ids = {item_id: {flow.id for flow in item_flows} for item_id, item_flows in direct_flows.items()}

    for allocation, _line, document in allocations:
        item = by_id[allocation.inventory_item_id]
        amount, quantity = Decimal(str(allocation.amount)), Decimal(str(allocation.quantity))
        if not amount.is_finite() or not quantity.is_finite():
            continue
        # Refunds carry no quantity and reduce the amount in their purchase document month.
        if amount >= ZERO and quantity > ZERO and allocation.cost_flow_id not in direct_flow_ids[item.id]:
            # Flow allocations are added below with the same proportional cap as manual entries.
            emit(item, document.document_date, amount, quantity, "purchase", str(document.id), allocation.id)
        elif amount < ZERO:
            emit(item, document.document_date, amount, ZERO, "refund", str(document.id), allocation.id)
    for item_id, item in by_id.items():
        item_entries = entries_by_lot[item_id]
        whole = next((entry for entry in item_entries if entry.cost_flow_id is None), None)
        flow_entries: dict[UUID, list[LotCostEntry]] = defaultdict(list)
        for entry in item_entries:
            if entry.cost_flow_id is not None:
                flow_entries[entry.cost_flow_id].append(entry)

        unpriced_direct = ZERO
        for flow in direct_flows[item_id]:
            flow_quantity = Decimal(str(flow.quantity))
            prices = flow_entries.get(flow.id, [])
            priced_quantity = sum((Decimal(str(entry.quantity)) for entry in prices), ZERO)
            flow_allocations = [
                (allocation, document)
                for allocation, _line, document in allocations
                if allocation.inventory_item_id == item_id
                and allocation.cost_flow_id == flow.id
                and allocation.amount >= ZERO
                and allocation.quantity > ZERO
            ]
            priced_quantity += sum(
                (Decimal(str(allocation.quantity)) for allocation, _document in flow_allocations), ZERO
            )
            effective_quantity = min(priced_quantity, flow_quantity)
            scale = effective_quantity / priced_quantity if priced_quantity > ZERO else ZERO
            for entry in prices:
                quantity = Decimal(str(entry.quantity)) * scale
                amount = Decimal(str(entry.amount)) * scale
                if quantity > ZERO:
                    emit(item, entry.created_at or datetime.now(UTC), amount, quantity, entry.kind, fact_id=entry.id)
            for allocation, document in flow_allocations:
                quantity = Decimal(str(allocation.quantity)) * scale
                amount = Decimal(str(allocation.amount)) * scale
                if quantity > ZERO:
                    emit(
                        item,
                        document.document_date,
                        amount,
                        quantity,
                        "purchase",
                        str(document.id),
                        allocation.id,
                    )
            unpriced_direct += flow_quantity - effective_quantity

        if whole is not None:
            whole_amount = Decimal(str(whole.amount))
            whole_quantity = Decimal(str(whole.quantity))
            if unpriced_direct > ZERO:
                amount = unpriced_direct * whole_amount / whole_quantity
                emit(item, whole.created_at or datetime.now(UTC), amount, unpriced_direct, whole.kind, fact_id=whole.id)
            elif not engine._in_flows(item_id):
                emit(
                    item,
                    whole.created_at or datetime.now(UTC),
                    whole_amount,
                    whole_quantity,
                    whole.kind,
                    fact_id=whole.id,
                )
    return facts


def _primed(db: Session, org_id: UUID, ids) -> tuple[CostEngine, bool]:
    """An engine with these lots bulk-loaded, and whether that fitted the engine's budget. When it
    didn't, callers cost each lot (or group) on a fresh engine of its own, so one oversized lot
    can't use up the budget for the rest."""
    engine = CostEngine(db, org_id)
    try:
        engine.prime(ids)
    except TooLargeError:
        return CostEngine(db, org_id), False
    return engine, True


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
    engine, primed = _primed(db, org_id, [item.id for item in all_lots])
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
        try:
            group_engine = engine if primed else CostEngine(db, org_id)
            facts = _history_facts_for_list(group_engine, group, unit, group_allocations, group_entries)
        except TooLargeError:  # still listed, so its history page can say why it has no figure
            engine, primed = CostEngine(db, org_id), False
            facts = {
                "name": min((item.name for item in group), key=lambda name: (normalise(name), name.casefold())),
                "unit": unit,
                "latest_unit_price": None,
                "latest_date": None,
            }
        if facts is not None:
            results.append(facts)
    return sorted(results, key=lambda row: (normalise(row["name"]), row["name"].casefold()))


def _history_facts_for_list(engine, lots, unit, allocations, entries) -> dict | None:
    """The latest price for this material group, from the same facts history uses."""
    by_id = {item.id: item for item in lots}
    entries_by_lot: dict[UUID, list[LotCostEntry]] = defaultdict(list)
    for entry in entries:
        entries_by_lot[entry.inventory_item_id].append(entry)
    latest = None
    priced = False
    for lot, when, amount, quantity, source, purchase_id, fact_id in _effective_facts(
        engine, by_id, allocations, entries_by_lot
    ):
        if quantity <= ZERO:
            continue
        priced = True
        factor = engine._unit_factor(unit, lot.unit)
        if factor is None:
            continue
        local_when = _nz_datetime(when) if isinstance(when, datetime) else _purchase_datetime(when)
        key = (local_when, str(purchase_id or ""), source, str(fact_id or ""))
        if latest is None or key > latest[0]:
            latest = (key, amount / quantity * factor)
    if not priced:
        return None
    return {
        "name": min((item.name for item in lots), key=lambda name: (normalise(name), name.casefold())),
        "unit": unit,
        "latest_unit_price": unit_str(latest[1]) if latest else None,
        "latest_date": latest[0][0].date().isoformat() if latest else None,
    }
