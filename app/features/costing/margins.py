"""Margin per product per month (live-cogs 8.1f-2; spec "Margins (Phase 2)").

Revenue from the sales sources, production cost from the cost engine, duty from the excise
module (costing never computes rates). Computed on read, like every cost here.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from uuid import UUID

from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.core.db.models.inventory_item import InventoryItem, InventoryType
from app.features.costing.engine import (
    _LIBRARY_SUFFIX,
    ACTUAL,
    ESTIMATED,
    PARTIAL,
    UNKNOWN,
    CostEngine,
    TooLargeError,
    normalise,
    worst,
)

ZERO = Decimal("0")
CENT = Decimal("0.01")
MAX_MONTHS = 24


def month_start(day: date) -> date:
    return day.replace(day=1)


def next_month(day: date) -> date:
    return date(day.year + (day.month == 12), day.month % 12 + 1, 1)


def _m(value: Decimal | None) -> str | None:
    return None if value is None else f"{value.quantize(CENT):f}"


@dataclass
class _Row:
    product: str
    month: date
    units: Decimal = ZERO
    revenue: Decimal | None = ZERO
    cost: Decimal = ZERO
    statuses: list = field(default_factory=list)
    duty: Decimal | None = ZERO
    duty_tracked: bool = True
    cost_units: Decimal = ZERO  # units whose cost is known
    lines: list = field(default_factory=list)

    def add_revenue(self, value: Decimal | None) -> None:
        self.revenue = None if value is None or self.revenue is None else self.revenue + value

    def add_duty(self, value: Decimal | None) -> None:
        self.duty = None if value is None or self.duty is None else self.duty + value


class _Costs:
    """Unit costs for lots and per-product averages, one engine per report."""

    def __init__(self, db: Session, org_id: UUID, products=(), sold_lot_ids=()):
        """Only the reported products' lots (and the lots their sales name) are primed, so a
        tenant's unrelated production history never costs this report anything."""
        self.engine = CostEngine(db, org_id)
        self.db, self.org_id = db, org_id
        self._unit: dict = {}
        self._average: dict = {}
        self._oversized: set = set()  # lots the engine ran out of budget on: never "uncosted"
        wanted = {normalise(p) for p in products}
        self._lots_by_name: dict[str, list[InventoryItem]] = defaultdict(list)
        finished = []
        if wanted:
            # Match in SQL the way normalise() does (trimmed, lower case, single spaces, Library stock
            # counted as its product), so unrelated finished lots never leave the database.
            name = func.lower(func.regexp_replace(func.trim(InventoryItem.name), r"\s+", " ", "g"))
            finished = (
                db.query(InventoryItem)
                .filter(
                    InventoryItem.org_id == org_id,
                    InventoryItem.inventory_type == InventoryType.FINAL_PRODUCT.value,
                    or_(name.in_(wanted), name.in_([w + _LIBRARY_SUFFIX for w in wanted])),
                )
                .all()
            )
        for item in finished:
            if normalise(item.name) in wanted:
                self._lots_by_name[normalise(item.name)].append(item)
        try:
            self.engine.prime({*sold_lot_ids, *(item.id for items in self._lots_by_name.values() for item in items)})
        except TooLargeError:
            # Lineage too big to load up front: cost lot by lot instead, and any lot over budget reads
            # unknown (lot() catches it) rather than the report failing.
            self.engine = CostEngine(db, org_id)

    def lot(self, item: InventoryItem) -> tuple[Decimal | None, str]:
        if item.id not in self._unit:
            try:
                cost = self.engine._solve(("lot", item.id))
            except TooLargeError:
                self._unit[item.id] = (None, UNKNOWN)
                self._oversized.add(item.id)
            else:
                unit = cost.unit_known if cost.status in (ACTUAL, ESTIMATED) else None
                self._unit[item.id] = (unit, cost.status if cost.status in (ACTUAL, ESTIMATED, PARTIAL) else UNKNOWN)
        return self._unit[item.id]

    def average(self, product: str) -> Decimal | None:
        """The product's average unit cost over its costed lots, weighted by their quantity."""
        key = normalise(product)
        if key not in self._average:
            lots = self._lots_by_name.get(key, [])
            total, units = ZERO, ZERO
            for item in lots:
                unit, status = self.lot(item)
                if item.id in self._oversized:
                    # A lot we couldn't cost might be the dear one: no average beats a wrong one.
                    total, units = ZERO, ZERO
                    break
                if unit is None or status not in (ACTUAL, ESTIMATED):
                    continue
                qty = Decimal(str(item.quantity or 0))
                if not qty.is_finite() or qty <= 0:
                    continue
                weight = qty
                total += unit * weight
                units += weight
            self._average[key] = (total / units) if units else None
        return self._average[key]

    def any_lot(self, product: str) -> InventoryItem | None:
        key = normalise(product)
        return next(iter(self._lots_by_name.get(key, [])), None)


def report(db: Session, org_id: UUID, start: date, end: date) -> dict:
    """Months in [start, end] (each a first-of-month). Rows newest month first."""
    from app.features.compliant.modules.nz_alcohol import excise
    from app.features.compliant.service import nz_alcohol_active
    from app.features.costing.models import CostingSettings
    from app.features.crm.services.sales_sources import sale_lines

    duty_on = nz_alcohol_active(db, org_id)
    settings = db.query(CostingSettings).filter(CostingSettings.org_id == org_id).one_or_none()
    base_currency = (settings.base_currency if settings and settings.base_currency else "NZD").upper()
    lines, _unmapped = sale_lines(db, org_id, start, next_month(end))
    credits = _credits(db, org_id, start, next_month(end))
    costs = _Costs(
        db,
        org_id,
        products={sale.product_name for sale in lines} | {credit["product"] for credit in credits},
        sold_lot_ids={item.id for sale in lines for item, _units in sale.batches},
    )
    rows: dict[tuple[str, date], _Row] = {}

    def row_for(product: str, day: date) -> _Row:
        key = (product, month_start(day))
        if key not in rows:
            rows[key] = _Row(product=product, month=month_start(day), duty_tracked=duty_on)
        return rows[key]

    duty_pairs: dict[date, list[tuple[_Row, InventoryItem, Decimal]]] = defaultdict(list)
    for sale in lines:
        row = row_for(sale.product_name, sale.sold_on)
        foreign = sale.currency and sale.currency.upper() != base_currency
        revenue = None if foreign else sale.revenue
        row.units += sale.units
        row.add_revenue(revenue)
        batches = []
        covered = ZERO
        for item, units in sale.batches:
            unit, status = costs.lot(item)
            covered += units
            row.statuses.append(status)
            if unit is not None:
                row.cost += units * unit
                row.cost_units += units
            if duty_on:
                duty_pairs[sale.sold_on].append((row, item, units))
            batches.append(
                {
                    "inventory_item_id": str(item.id),
                    "name": item.name,
                    "batch": item.supplier_batch_number,
                    "units": f"{units:f}",
                    "unit_cost": _m(unit),
                    "status": status,
                }
            )
        loose = sale.units - covered
        if loose > 0:
            average = costs.average(sale.product_name)
            if average is None:
                row.statuses.append(UNKNOWN)
            else:
                row.cost += loose * average
                row.cost_units += loose
                row.statuses.append(ESTIMATED)
            any_lot = costs.any_lot(sale.product_name)
            if duty_on and any_lot is not None:
                duty_pairs[sale.sold_on].append((row, any_lot, loose))
            elif duty_on:
                row.add_duty(None)
        row.lines.append(
            {
                "reference": sale.reference,
                "sold_on": sale.sold_on.isoformat(),
                "units": f"{sale.units:f}",
                "revenue": _m(revenue),
                "unbatched_units": f"{max(loose, ZERO):f}",
                "batches": batches,
            }
        )

    for on, pairs in duty_pairs.items():
        measured = excise.measure(db, org_id, [(item, units) for _, item, units in pairs], on)
        for (row, _, _), result in zip(pairs, measured, strict=True):
            value = result["duty"]
            row.add_duty(None if value is None else Decimal(value))

    sales_costs: dict[tuple[str, date], tuple[Decimal, Decimal]] = {}
    for (product, month), row in rows.items():
        sales_costs[(normalise(product), month)] = (row.cost, row.cost_units)

    for credit in credits:
        row = row_for(credit["product"], credit["date"])
        row.units -= credit["units"]
        foreign = credit["currency"] and credit["currency"].upper() != base_currency
        amount = None if foreign else credit["amount"]
        row.add_revenue(None if amount is None else -amount)
        if credit["returned"]:
            month_cost, month_units = sales_costs.get(
                (normalise(credit["product"]), month_start(credit["date"])), (ZERO, ZERO)
            )
            average = month_cost / month_units if month_units > 0 else costs.average(credit["product"])
            if average is None:
                row.statuses.append(UNKNOWN)
            else:
                row.cost -= credit["units"] * average
                row.cost_units -= credit["units"]
                row.statuses.append(ESTIMATED)
        row.lines.append(
            {
                "reference": credit["reference"],
                "sold_on": credit["date"].isoformat(),
                "units": f"{-credit['units']:f}",
                "revenue": _m(None if amount is None else -amount),
                "unbatched_units": "0",
                "batches": [],
                "credit_note": True,
            }
        )

    out = []
    for (product, month), row in sorted(rows.items(), key=lambda kv: (-kv[0][1].toordinal(), kv[0][0].casefold())):
        status = worst(*row.statuses) if row.statuses else ACTUAL
        known_cost = status not in (PARTIAL, UNKNOWN)
        cost = row.cost if known_cost else None
        tracked_duty = row.duty if row.duty_tracked else None
        margin = None
        duty_known = not row.duty_tracked or row.duty is not None  # tracked but unmeasured: no margin
        if row.revenue is not None and cost is not None and duty_known:
            margin = row.revenue - cost - (tracked_duty or ZERO)
        out.append(
            {
                "product": product,
                "month": month.strftime("%Y-%m"),
                "units": f"{row.units:f}",
                "revenue": _m(row.revenue),
                "cost": _m(cost),
                "cost_status": status,
                "duty": _m(tracked_duty),
                "duty_tracked": row.duty_tracked,
                "margin": _m(margin),
                "margin_percent": (
                    _m(margin / row.revenue * 100) if margin is not None and row.revenue not in (None, ZERO) else None
                ),
                "average_cost_per_unit": _m(cost / row.units) if cost is not None and row.units > 0 else None,
                "lines": row.lines,
            }
        )
    return {"from": start.strftime("%Y-%m"), "to": end.strftime("%Y-%m"), "rows": out}


def _credits(db: Session, org_id: UUID, start: date, end: date) -> list[dict]:
    """Authorised/paid sales credit notes on mapped lines, dated in [start, end)."""
    from app.features.crm.models.product_mapping import ProductMapping
    from app.features.crm.models.xero_credit_note import XeroCreditNote
    from app.features.crm.models.xero_credit_note_line import XeroCreditNoteLine

    rows = (
        db.query(XeroCreditNoteLine, XeroCreditNote, ProductMapping)
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
            XeroCreditNoteLine.is_current.is_(True),
            XeroCreditNote.status.in_(("AUTHORISED", "PAID")),
            XeroCreditNote.date >= start,
            XeroCreditNote.date < end,
        )
        .all()
    )
    out = []
    for line, note, mapping in rows:
        quantity = Decimal(str(line.quantity or 0))
        if not quantity.is_finite() or quantity <= 0:
            continue
        out.append(
            {
                "product": mapping.biz_e_product_name,
                "date": note.date,
                "reference": note.number or note.xero_credit_note_id,
                "units": quantity * int(mapping.units_per_line or 1),
                "amount": None if line.line_amount is None else Decimal(str(line.line_amount)),
                "returned": not line.no_return_note,
                "currency": note.currency,
            }
        )
    return out
