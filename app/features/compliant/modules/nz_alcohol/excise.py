"""Excise per lodgement period, built from recorded removals (plan item 2.1).

NZ Customs taxes alcohol **removed from the Customs-controlled (licensed) area**, not
alcohol invoiced (checked 25 Sep 2026: customs.govt.nz "Entry lodgement timing"). So a
period's lines come from removals:

- a sale matched to a batch that was in the licensed area (no location, or a location
  marked inside it): removed on the invoice date;
- stock moved from the licensed area to an outside location (a sales rep, an event):
  removed on the move date. A later sale of that stock isn't counted again.

Stock moved back into the licensed area is listed separately as a possible credit to
raise with Customs; it's never claimed automatically.

Each removal's litres of alcohol (LAL) = litres x ABV. ABV comes from the batch (its
final-step "ABV (%)" field, or the ABV counted at go-live), falling back to the product
profile. Litres come from the pack volume for counted goods (700 mL bottles) or the unit
itself (mL, L). Duty = LAL x the rate in force at the start of the period.

A lodged period is locked as a snapshot. A removal recorded after that (a late invoice,
a correction) is carried into the next open period as an adjustment naming the period it
belongs to, so a lodged entry is never silently rewritten.

This is a draft to check before lodging, not tax advice.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.db.models.execution_step import ExecutionStep
from app.core.db.models.inventory_item import InventoryItem
from app.core.db.models.organisation import Organisation
from app.core.db.models.stock_location import StockLocation, StockTransfer
from app.core.utils.unit_conversion import is_count_unit, normalize_unit
from app.features.compliant.models.alcohol_product_profile import AlcoholProductProfile
from app.features.compliant.models.excise import ExciseLodgement, ExciseRate

FREQUENCIES = ("monthly", "six_monthly", "twelve_monthly")
ABV_PROMPT_LABEL = "ABV (%)"
_Q4 = Decimal("0.0001")
_Q2 = Decimal("0.01")


# --- periods ------------------------------------------------------------------------------


def period_for(day: date, frequency: str) -> tuple[date, date]:
    """The lodgement period containing ``day``, as [start, end) dates."""
    if frequency == "six_monthly":
        start = date(day.year, 1 if day.month <= 6 else 7, 1)
        end = date(day.year, 7, 1) if day.month <= 6 else date(day.year + 1, 1, 1)
        return start, end
    if frequency == "twelve_monthly":
        # Twelve-monthly entries are due in July following the year of removal: Jul-Jun.
        start = date(day.year if day.month >= 7 else day.year - 1, 7, 1)
        return start, date(start.year + 1, 7, 1)
    start = day.replace(day=1)
    end = date(start.year + (start.month == 12), start.month % 12 + 1, 1)
    return start, end


def previous_period(start: date, frequency: str) -> tuple[date, date]:
    return period_for(start - timedelta(days=1), frequency)


def working_day(month_start: date, n: int) -> date:
    """The nth working day (Mon-Fri) of the month starting at ``month_start``.

    Public holidays aren't modelled; the page says so next to the date.
    """
    day = month_start
    count = 0
    while True:
        if day.weekday() < 5:
            count += 1
            if count == n:
                return day
        day += timedelta(days=1)


def entry_due(period_end: date) -> date:
    """Entries are due by the 15th working day of the month after the period."""
    return working_day(period_end, 15)


def period_label(start: date, end: date) -> str:
    last = end - timedelta(days=1)
    if (start.year, start.month) == (last.year, last.month):
        return start.strftime("%B %Y")
    return f"{start.strftime('%b %Y')} to {last.strftime('%b %Y')}"


# --- removals -----------------------------------------------------------------------------


@dataclass
class Removal:
    kind: str  # "sale" | "moved_out" | "returned"
    occurred_on: date
    recorded_at: datetime | None
    item: InventoryItem
    quantity: Decimal
    reference: str
    customer: str | None = None


def _licensed(item: InventoryItem, locations: dict) -> bool:
    if item.location_id is None:
        return True
    loc = locations.get(item.location_id)
    return bool(loc and loc.inside_licensed_area)


def removals_between(session: Session, org_id: UUID, start: date, end: date) -> list[Removal]:
    from app.features.crm.models.sales_fifo_allocation import SalesFifoAllocation
    from app.features.crm.models.xero_contact import XeroContact
    from app.features.crm.models.xero_invoice import XeroInvoice

    locations = {loc.id: loc for loc in session.query(StockLocation).filter(StockLocation.org_id == org_id).all()}
    out: list[Removal] = []

    rows = (
        session.query(SalesFifoAllocation, XeroInvoice)
        .join(
            XeroInvoice,
            (XeroInvoice.org_id == SalesFifoAllocation.org_id)
            & (XeroInvoice.xero_invoice_id == SalesFifoAllocation.xero_invoice_id),
        )
        .filter(SalesFifoAllocation.org_id == org_id, XeroInvoice.date >= start, XeroInvoice.date < end)
        .all()
    )
    item_ids = {a.inventory_item_id for a, _ in rows}
    items = (
        {i.id: i for i in session.query(InventoryItem).filter(InventoryItem.id.in_(item_ids)).all()} if item_ids else {}
    )
    contact_ids = {inv.contact_id for _, inv in rows if inv.contact_id}
    contacts = (
        {c.id: c.name for c in session.query(XeroContact).filter(XeroContact.id.in_(contact_ids)).all()}
        if contact_ids
        else {}
    )
    for allocation, invoice in rows:
        item = items.get(allocation.inventory_item_id)
        if item is None or not _licensed(item, locations):
            continue  # sold from stock already removed (e.g. a rep's car): counted when it left
        out.append(
            Removal(
                kind="sale",
                occurred_on=invoice.date,
                recorded_at=allocation.created_at,
                item=item,
                quantity=Decimal(str(allocation.quantity)),
                reference=invoice.invoice_number or invoice.xero_invoice_id,
                customer=contacts.get(invoice.contact_id),
            )
        )

    transfers = (
        session.query(StockTransfer)
        .filter(
            StockTransfer.org_id == org_id,
            StockTransfer.occurred_on >= start,
            StockTransfer.occurred_on < end,
            StockTransfer.direction.in_(("out", "in")),
        )
        .all()
    )
    t_items = {t.from_item_id for t in transfers}
    t_map = (
        {i.id: i for i in session.query(InventoryItem).filter(InventoryItem.id.in_(t_items)).all()} if t_items else {}
    )
    for t in transfers:
        item = t_map.get(t.from_item_id)
        if item is None:
            continue
        dest = locations.get(t.to_location_id)
        out.append(
            Removal(
                kind="moved_out" if t.direction == "out" else "returned",
                occurred_on=t.occurred_on,
                recorded_at=t.created_at,
                item=item,
                quantity=Decimal(str(t.quantity)),
                reference=f"Moved to {dest.name}" if dest else "Moved to the licensed area",
            )
        )
    return out


# --- litres of alcohol ----------------------------------------------------------------------


def _lot_abv(session: Session, item: InventoryItem, profile: AlcoholProductProfile | None) -> Decimal | None:
    raw = (item.extra_data or {}).get("abv_percent")
    if raw in (None, "") and item.source_execution_step_id:
        step = session.get(ExecutionStep, item.source_execution_step_id)
        raw = (step.execution_data or {}).get(ABV_PROMPT_LABEL) if step is not None else None
    if raw in (None, "") and profile is not None and profile.abv_percent is not None:
        raw = profile.abv_percent
    try:
        return Decimal(str(raw)) if raw not in (None, "") else None
    except Exception:
        return None


def _litres(quantity: Decimal, unit: str, profile: AlcoholProductProfile | None) -> Decimal | None:
    u = normalize_unit(unit)
    if u == "l":
        return quantity
    if u == "ml":
        return quantity / 1000
    if is_count_unit(u):
        if profile is None or not profile.pack_volume_ml:
            return None
        return quantity * Decimal(str(profile.pack_volume_ml)) / 1000
    return None


def _rate_for(rates: list[ExciseRate], tariff_item: str | None, on: date) -> ExciseRate | None:
    candidates = [r for r in rates if r.tariff_item == tariff_item and r.effective_from <= on]
    return max(candidates, key=lambda r: r.effective_from) if candidates else None


def _base_name(name: str) -> str:
    """Library stock of a product is excised as that product."""
    marker = " - "
    if marker in name and name.lower().endswith("library stock"):
        return name.rsplit(marker, 1)[0]
    return name


def compute_lines(session: Session, org_id: UUID, removals: list[Removal], rate_date: date) -> dict:
    profiles = {
        p.inventory_name.casefold(): p
        for p in session.query(AlcoholProductProfile).filter(AlcoholProductProfile.org_id == org_id).all()
        if p.is_active
    }
    rates = session.query(ExciseRate).filter(ExciseRate.org_id == org_id).all()
    lines: dict = {}
    problems: dict = {}
    returns = []
    for r in removals:
        product = _base_name(r.item.name)
        profile = profiles.get(product.casefold())
        if r.kind == "returned":
            returns.append(
                {"product": product, "quantity": _s(r.quantity), "unit": r.item.unit, "date": r.occurred_on.isoformat()}
            )
            continue
        litres = _litres(r.quantity, r.item.unit, profile)
        abv = _lot_abv(session, r.item, profile)
        if profile is None or litres is None or abv is None:
            reason = (
                "Not set up as an excise product"
                if profile is None
                else ("Pack volume missing" if litres is None else "No ABV recorded for this batch or product")
            )
            key = (product, reason)
            entry = problems.setdefault(key, {"product": product, "reason": reason, "removals": 0})
            entry["removals"] += 1
            continue
        lal = litres * abv / 100
        tariff = profile.customs_product_code or "—"
        line = lines.setdefault(
            (tariff, product),
            {
                "tariff_item": tariff,
                "product": product,
                "units": Decimal("0"),
                "unit": "L" if normalize_unit(r.item.unit) in ("l", "ml") else r.item.unit,
                "litres": Decimal("0"),
                "lal": Decimal("0"),
                "removals": [],
            },
        )
        line["units"] += r.quantity if is_count_unit(r.item.unit) else litres
        line["litres"] += litres
        line["lal"] += lal
        line["removals"].append(
            {
                "kind": r.kind,
                "date": r.occurred_on.isoformat(),
                "reference": r.reference,
                "customer": r.customer,
                "batch": r.item.supplier_batch_number or (r.item.extra_data or {}).get("batch_number"),
                "quantity": _s(r.quantity),
                "abv_percent": _s(abv),
                "lal": _s(lal.quantize(_Q4)),
            }
        )
    out_lines = []
    total_lal = Decimal("0")
    total_duty = Decimal("0")
    missing_rates = set()
    for (tariff, _product), line in sorted(lines.items()):
        rate = _rate_for(rates, None if tariff == "—" else tariff, rate_date)
        lal = line["lal"].quantize(_Q4, ROUND_HALF_UP)
        duty = (lal * Decimal(str(rate.rate_per_lal))).quantize(_Q2, ROUND_HALF_UP) if rate else None
        if rate is None:
            missing_rates.add(tariff)
        total_lal += lal
        total_duty += duty or Decimal("0")
        out_lines.append(
            {
                **line,
                "units": _s(line["units"]),
                "litres": _s(line["litres"].quantize(_Q4, ROUND_HALF_UP)),
                "lal": _s(lal),
                "rate_per_lal": _s(rate.rate_per_lal) if rate else None,
                "duty": _s(duty) if duty is not None else None,
            }
        )
    return {
        "lines": out_lines,
        "total_lal": _s(total_lal),
        "total_duty": _s(total_duty.quantize(_Q2)),
        "problems": list(problems.values())
        + [
            {"product": t, "reason": "No duty rate for this tariff item at the period start", "removals": 0}
            for t in sorted(missing_rates)
        ],
        "returns": returns,
    }


def _s(value) -> str:
    return f"{Decimal(str(value)).normalize():f}"


def _legacy_draft_unavailable(session: Session, org_id: UUID) -> bool:
    """The location flag cannot assign a removal to a CCA after multi-site opt-in."""
    return bool(session.query(Organisation.multiple_sites_enabled).filter(Organisation.id == org_id).scalar())


def measure(session: Session, org_id: UUID, pairs: list, on: date) -> list[dict]:
    """Litres, ABV, LAL and duty at ``on`` for (item, quantity) pairs: stocktake lines, stock position.

    Fields are None where they can't be worked out (not an excise product, no pack volume,
    no ABV, or no rate), so callers show a gap instead of a wrong number.
    """
    profiles = {
        p.inventory_name.casefold(): p
        for p in session.query(AlcoholProductProfile).filter(AlcoholProductProfile.org_id == org_id).all()
        if p.is_active
    }
    rates = session.query(ExciseRate).filter(ExciseRate.org_id == org_id).all()
    out = []
    for item, quantity in pairs:
        profile = profiles.get(_base_name(item.name).casefold())
        qty = Decimal(str(quantity))
        if not qty.is_finite():
            out.append({"litres": None, "abv_percent": None, "lal": None, "duty": None})
            continue
        litres = _litres(abs(qty), item.unit, profile)
        abv = _lot_abv(session, item, profile)
        lal = (litres * abv / 100).quantize(_Q4, ROUND_HALF_UP) if litres is not None and abv is not None else None
        rate = _rate_for(rates, profile.customs_product_code if profile else None, on) if profile else None
        duty = (
            (lal * Decimal(str(rate.rate_per_lal))).quantize(_Q2, ROUND_HALF_UP) if lal is not None and rate else None
        )
        sign = -1 if qty < 0 else 1
        out.append(
            {
                "litres": _s(sign * litres.quantize(_Q4, ROUND_HALF_UP)) if litres is not None else None,
                "abv_percent": _s(abv) if abv is not None else None,
                "lal": _s(sign * lal) if lal is not None else None,
                "duty": f"{sign * duty:f}" if duty is not None else None,  # keeps cents: 138.20
            }
        )
    return out


def lodged_between(session: Session, org_id: UUID, start: date | None, end: date) -> dict:
    """LAL per product in lodged entries whose period starts in [start, end), incl. carried adjustments."""
    query = session.query(ExciseLodgement).filter(ExciseLodgement.org_id == org_id, ExciseLodgement.period_start < end)
    if start is not None:
        query = query.filter(ExciseLodgement.period_start >= start)
    out: dict = {}
    for lodgement in query.all():
        snap = lodgement.snapshot or {}
        for line in snap.get("lines", []):
            out[line["product"]] = out.get(line["product"], Decimal("0")) + Decimal(str(line["lal"]))
        for adj in snap.get("adjustments", []):
            out[adj["product"]] = out.get(adj["product"], Decimal("0")) + Decimal(str(adj["lal"]))
    return {k: _s(v) for k, v in out.items()}


# --- drafts, lodging, reminders ---------------------------------------------------------------


def settings_for(profile) -> dict:
    settings = (getattr(profile, "settings", None) or {}) if profile is not None else {}
    frequency = settings.get("excise_frequency") if settings.get("excise_frequency") in FREQUENCIES else "monthly"
    tracking_from = settings.get("excise_tracking_from")
    return {"frequency": frequency, "tracking_from": tracking_from}


def draft(session: Session, org_id: UUID, start: date, frequency: str, today: date | None = None) -> dict:
    start, end = period_for(start, frequency)
    lodged = (
        session.query(ExciseLodgement)
        .filter(ExciseLodgement.org_id == org_id, ExciseLodgement.period_start == start)
        .one_or_none()
    )
    base = {
        "period_start": start.isoformat(),
        "period_end": (end - timedelta(days=1)).isoformat(),
        "label": period_label(start, end),
        "frequency": frequency,
        "due": entry_due(end).isoformat(),
        "open": (today or date.today()) < end,
    }
    if lodged is not None:
        return {
            **base,
            **lodged.snapshot,
            "status": "lodged",
            "lodged_on": lodged.lodged_on.isoformat(),
            "entry_reference": lodged.entry_reference,
            "nil_return": lodged.nil_return,
        }

    current = compute_lines(session, org_id, removals_between(session, org_id, start, end), start)
    adjustments = _late_adjustments(session, org_id, start)
    if _legacy_draft_unavailable(session, org_id):
        current["problems"].append(
            {
                "product": "CCA accounting",
                "reason": "The legacy location-based draft cannot assign removals to a CCA after multiple sites are enabled",
                "removals": 0,
            }
        )
        return {
            **base,
            **current,
            "status": "draft",
            "adjustments": adjustments,
            "legacy_unavailable": True,
            "complete_lodgement": False,
            "nil_return": None,
            "total_lal": None,
            "total_duty": None,
        }
    return {**base, **current, "status": "draft", "adjustments": adjustments, "legacy_unavailable": False}


def _late_adjustments(session: Session, org_id: UUID, before: date) -> list[dict]:
    """Removals recorded after their (earlier) period was lodged, not yet carried."""
    lodgements = (
        session.query(ExciseLodgement)
        .filter(ExciseLodgement.org_id == org_id, ExciseLodgement.period_start < before)
        .all()
    )
    carried = set()
    for later in session.query(ExciseLodgement).filter(ExciseLodgement.org_id == org_id).all():
        for adj in (later.snapshot or {}).get("adjustments", []):
            carried.add((adj["belongs_to"], adj["reference"], adj["date"], adj["quantity"]))
    out = []
    for lodgement in lodgements:
        cutoff = lodgement.created_at
        removals = [
            r
            for r in removals_between(session, org_id, lodgement.period_start, lodgement.period_end + timedelta(days=1))
            if r.kind != "returned" and r.recorded_at is not None and cutoff is not None and r.recorded_at > cutoff
        ]
        if not removals:
            continue
        computed = compute_lines(session, org_id, removals, lodgement.period_start)
        for line in computed["lines"]:
            for removal in line["removals"]:
                key = (lodgement.period_start.isoformat(), removal["reference"], removal["date"], removal["quantity"])
                if key in carried:
                    continue
                out.append(
                    {
                        "belongs_to": lodgement.period_start.isoformat(),
                        "belongs_to_label": period_label(
                            lodgement.period_start, lodgement.period_end + timedelta(days=1)
                        ),
                        "product": line["product"],
                        "tariff_item": line["tariff_item"],
                        **{k: removal[k] for k in ("reference", "date", "quantity", "lal", "kind")},
                    }
                )
    return out


def lodge(
    session: Session,
    org_id: UUID,
    start: date,
    frequency: str,
    lodged_on: date,
    entry_reference: str | None,
    user_id,
    today: date | None = None,
) -> ExciseLodgement:
    if _legacy_draft_unavailable(session, org_id):
        raise ValueError("Multiple-site excise must be reviewed per CCA; the legacy draft cannot be lodged")
    current = draft(session, org_id, start, frequency, today=today)
    if current["status"] == "lodged":
        raise ValueError(f"{current['label']} is already recorded as lodged.")
    if current["open"]:
        raise ValueError(f"{current['label']} hasn't finished yet.")
    snapshot = {k: current[k] for k in ("lines", "total_lal", "total_duty", "problems", "returns", "adjustments")}
    record = ExciseLodgement(
        org_id=org_id,
        period_start=date.fromisoformat(current["period_start"]),
        period_end=date.fromisoformat(current["period_end"]),
        lodged_on=lodged_on,
        entry_reference=(entry_reference or "").strip()[:100] or None,
        nil_return=not current["lines"] and not current["adjustments"],
        snapshot=snapshot,
        lodged_by_user_id=user_id,
    )
    session.add(record)
    session.flush()
    return record


def reminder(session: Session, org_id: UUID, profile, today: date | None = None) -> dict | None:
    """The lodgement alert for the latest finished period not yet recorded as lodged.

    Only once excise tracking is switched on (``excise_tracking_from``), so turning the
    module on doesn't flood an org with years of unlodged months.
    """
    cfg = settings_for(profile)
    if not cfg["tracking_from"]:
        return None
    today = today or date.today()
    start, _end = previous_period(period_for(today, cfg["frequency"])[0], cfg["frequency"])
    tracking = date.fromisoformat(cfg["tracking_from"])
    if start < period_for(tracking, cfg["frequency"])[0]:
        return None
    current = draft(session, org_id, start, cfg["frequency"], today=today)
    if current["status"] == "lodged":
        return None
    due = date.fromisoformat(current["due"])
    if current.get("legacy_unavailable"):
        return {
            "id": f"excise-lodgement-{current['period_start']}",
            "title": f"Review per-CCA excise for {current['label']}",
            "description": "Multiple-site removals need a complete entry for each source CCA. The legacy draft cannot be lodged.",
            "due_date": due.isoformat(),
            "href": "/compliant/nz-alcohol/customs",
            "action_label": "Review CCA movements",
            "overdue": today > due,
        }
    nil = not current["lines"] and not current["adjustments"]
    what = "nil return" if nil else f"entry: {current['total_lal']} LAL"
    return {
        "id": f"excise-lodgement-{current['period_start']}",
        "title": f"Excise {'nil return' if nil else 'entry'} for {current['label']} due {due.strftime('%-d %b %Y')}",
        "description": (
            f"{'Overdue: ' if today > due else ''}Lodge the {current['label']} {what} with Customs, then record it "
            "as lodged here."
        ),
        "due_date": due.isoformat(),
        "href": "/compliant/nz-alcohol/customs",
        "action_label": "Open excise",
        "overdue": today > due,
    }
