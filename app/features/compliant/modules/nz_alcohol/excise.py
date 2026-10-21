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
itself (mL, L). Duty uses the rate in force at the start of the period: the org's own rate
for the product's tariff item, else the built-in Customs guide for its product type
(``excise_tariff``). Most bands are LAL x rate; some (beer under 2.5%, wine, drinks of
6-14%) are litres of drink x rate.

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
from app.features.compliant.modules.nz_alcohol import excise_tariff

FREQUENCIES = ("monthly", "six_monthly", "twelve_monthly")
ABV_PROMPT_LABEL = "ABV (%)"
_Q4 = Decimal("0.0001")
_Q2 = Decimal("0.01")
_Q3 = Decimal("0.001")  # Customs entry quantities are to three decimal places


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


def tariff_item_for(profile: AlcoholProductProfile | None, abv: Decimal | None) -> str | None:
    """The tariff item a product is entered under: the one typed on the profile, else its product type's band."""
    if profile is None:
        return None
    if profile.customs_product_code:
        return profile.customs_product_code
    band = excise_tariff.classify(getattr(profile, "excise_category", None), abv)
    return band.item if band else None


def resolve_rate(rates: list[ExciseRate], tariff_item: str | None, on: date) -> tuple[Decimal, str] | None:
    """(rate, basis) for a tariff item on a date: the org's own rate first, then the built-in guide."""
    own = _rate_for(rates, tariff_item, on)
    if own is not None:
        return Decimal(str(own.rate_per_lal)), excise_tariff.PER_LAL
    return excise_tariff.rate_for_item(tariff_item, on)


def duty_for(rate: tuple[Decimal, str] | None, litres: Decimal, lal: Decimal) -> Decimal | None:
    if rate is None:
        return None
    base = lal if rate[1] == excise_tariff.PER_LAL else litres
    return (base * rate[0]).quantize(_Q2, ROUND_HALF_UP)


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
        tariff = tariff_item_for(profile, abv) or "—"
        line = lines.setdefault(
            (tariff, product),
            {
                "tariff_item": tariff,
                "product": product,
                "units": Decimal("0"),
                "unit": "L" if normalize_unit(r.item.unit) in ("l", "ml") else r.item.unit,
                "litres": Decimal("0"),
                "lal": Decimal("0"),
                "levy_cents": Decimal("0"),
                "removals": [],
            },
        )
        line["units"] += r.quantity if is_count_unit(r.item.unit) else litres
        line["litres"] += litres
        line["lal"] += lal
        levy = excise_tariff.levy_rate(abv, rate_date)
        line["levy_cents"] += litres * levy[1] if levy else 0
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
        rate = resolve_rate(rates, None if tariff == "—" else tariff, rate_date)
        lal = line["lal"].quantize(_Q4, ROUND_HALF_UP)
        duty = duty_for(rate, line["litres"].quantize(_Q4, ROUND_HALF_UP), lal)
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
                "rate_per_lal": _s(rate[0]) if rate and rate[1] == excise_tariff.PER_LAL else None,
                "rate": _s(rate[0]) if rate else None,
                "basis": rate[1] if rate else None,
                "duty": _s(duty) if duty is not None else None,
            }
        )
    for line in out_lines:
        line.pop("levy_cents", None)
    return {
        "lines": out_lines,
        "entry": entry_lines(lines, rates, rate_date),
        "total_lal": _s(total_lal),
        "total_duty": _s(total_duty.quantize(_Q2)),
        "problems": list(problems.values())
        + [
            {"product": t, "reason": "No duty rate for this tariff item at the period start", "removals": 0}
            for t in sorted(missing_rates)
        ],
        "returns": returns,
    }


def entry_lines(lines: dict, rates: list[ExciseRate], rate_date: date) -> dict:
    """The period as Customs' Trade Single Window entry asks for it.

    One line per product under its excise item, in TSW column order: litres (supplementary
    quantity), LAL (statistical quantity), the rate and its basis, duty, alcohol levy and GST
    on the levy. Each line is rounded on its own, as Customs does: Whistlebird's lodged
    September 2026 entry (Wildflower, Solstice, Green Gold) came to duty 2244.10 + levy
    18.21 + GST 2.73 = 2265.04, and merging the two gins into one line gives a levy of 18.20.
    GST is charged on the levy only.
    """
    by_item = {
        key: {
            "products": [key[1]],
            "units": line["units"],
            "unit": line["unit"],
            "litres": line["litres"],
            "lal": line["lal"],
            "levy_cents": line.get("levy_cents") or 0,
        }
        for key, line in sorted(lines.items())
    }
    out = []
    totals = {"duty": Decimal("0"), "levy": Decimal("0"), "gst": Decimal("0")}
    complete = True
    for number, ((tariff, _product), item) in enumerate(by_item.items(), start=1):
        litres = item["litres"].quantize(_Q3, ROUND_HALF_UP)
        lal = item["lal"].quantize(_Q3, ROUND_HALF_UP)
        rate = resolve_rate(rates, None if tariff == "—" else tariff, rate_date)
        duty = duty_for(rate, litres, lal)
        levy = (item["levy_cents"] / 100).quantize(_Q2, ROUND_HALF_UP)
        gst = (levy * excise_tariff.GST_RATE).quantize(_Q2, ROUND_HALF_UP)
        complete = complete and duty is not None and tariff != "—"
        totals["duty"] += duty or 0
        totals["levy"] += levy
        totals["gst"] += gst
        out.append(
            {
                "line": number,
                "excise_item": tariff,
                "description": ", ".join(item["products"]),
                "units": _s(item["units"]),
                "unit": item["unit"],
                "supplementary_litres": f"{litres:f}",
                "statistical_lal": f"{lal:f}",
                "rate": _s(rate[0]) if rate else None,
                "basis": rate[1] if rate else None,
                "duty": f"{duty:f}" if duty is not None else None,
                "levy": f"{levy:f}",
                "gst_on_levy": f"{gst:f}",
                "total": f"{(duty or 0) + levy + gst:f}" if duty is not None else None,
            }
        )
    return {
        "lines": out,
        "complete": complete,
        "total_duty": f"{totals['duty']:f}",
        "total_levy": f"{totals['levy']:f}",
        "total_gst": f"{totals['gst']:f}",
        "total": f"{totals['duty'] + totals['levy'] + totals['gst']:f}",
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
        rate = resolve_rate(rates, tariff_item_for(profile, abv), on) if profile else None
        duty = duty_for(rate, litres.quantize(_Q4, ROUND_HALF_UP), lal) if lal is not None else None
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
    created = getattr(profile, "created_at", None)
    reminders_from = tracking_from or (created.date().isoformat() if created is not None else None)
    return {"frequency": frequency, "tracking_from": tracking_from, "reminders_from": reminders_from}


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
            "entry": None,
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
    snapshot = {
        k: current[k] for k in ("lines", "entry", "total_lal", "total_duty", "problems", "returns", "adjustments")
    }
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
    _record_lodgement_evidence(session, record, current, user_id)
    return record


def _record_lodgement_evidence(session: Session, lodgement: ExciseLodgement, current: dict, user_id) -> None:
    """Lodging is itself the proof for Customs' "each period lodged" control."""
    from app.features.compliant.models.compliance_record import ComplianceRecord

    entry = current.get("entry") or {}
    totals = {k: entry.get(k) for k in ("total_duty", "total_levy", "total_gst", "total")}
    session.add(
        ComplianceRecord(
            org_id=lodgement.org_id,
            framework_slug="customs-alcohol",
            control_id="period-lodgement",
            record_type="lodgement",
            status="complete",
            title=f"Excise {'nil return' if lodgement.nil_return else 'entry'} lodged for {current['label']}",
            period_start=lodgement.period_start,
            period_end=lodgement.period_end,
            evidence_reference=lodgement.entry_reference or ("Nil return" if lodgement.nil_return else None),
            source_refs=[],
            details={
                "excise_lodgement_id": str(lodgement.id),
                "lodged_on": lodgement.lodged_on.isoformat(),
                "total_lal": current.get("total_lal"),
                **totals,
            },
            created_by_user_id=user_id,
        )
    )
    session.flush()


# Customs lets a licensee lodge less often once the yearly duty is low enough, after at least
# six months of monthly entries (customs.govt.nz, "Entry lodgement timing").
SIX_MONTHLY_LIMIT = Decimal("100000")
TWELVE_MONTHLY_LIMIT = Decimal("50000")
MONTHLY_FIRST_MONTHS = 6


def position(session: Session, org_id: UUID, profile, today: date | None = None) -> dict:
    """Where the org stands with Customs right now, for the Customs pages' summary.

    The duty over the last twelve months (lodged entries plus estimates for finished periods
    not yet lodged) against Customs' thresholds for six- and twelve-monthly lodging; the
    period in progress; the stocktake; breakages to claim a remission for; and product setup.
    """
    from app.core.backend import stocktake
    from app.core.db.models.inventory_item import InventoryItem
    from app.core.db.models.stocktake import Stocktake, StocktakeLine, StocktakeResolution

    today = today or date.today()
    cfg = settings_for(profile)
    frequency = cfg["frequency"]
    year_ago = _months_before(today, 12)
    lodged_duty = estimated_duty = Decimal("0")
    lodged_count = unlodged = overdue = 0
    lodgements = {
        lg.period_start: lg
        for lg in session.query(ExciseLodgement).filter(
            ExciseLodgement.org_id == org_id, ExciseLodgement.period_start >= year_ago
        )
    }
    for lg in lodgements.values():
        snap = lg.snapshot or {}
        lodged_duty += Decimal(str((snap.get("entry") or {}).get("total_duty") or snap.get("total_duty") or 0))
        lodged_count += 1
    start = period_for(today, frequency)[0]
    current = draft(session, org_id, start, frequency, today=today)
    since = date.fromisoformat(cfg["reminders_from"]) if cfg["reminders_from"] else None
    p_start = start
    while True:
        p_start, p_end = previous_period(p_start, frequency)
        if p_start < year_ago:
            break
        if p_start in lodgements:
            continue
        d = draft(session, org_id, p_start, frequency, today=today)
        estimated_duty += Decimal(str((d.get("entry") or {}).get("total_duty") or d.get("total_duty") or 0))
        if since is None or p_end > since:
            unlodged += 1
            overdue += today > date.fromisoformat(d["due"])
    year_duty = lodged_duty + estimated_duty
    created = getattr(profile, "created_at", None)
    monthly_until = _months_after(created.date(), MONTHLY_FIRST_MONTHS) if created is not None else None

    plan = stocktake.schedule(session, org_id, (getattr(profile, "settings", None) or {}), today)
    variances = stocktake.open_variances(session, org_id, today)
    remission_rows = (
        session.query(StocktakeResolution, StocktakeLine, Stocktake, InventoryItem)
        .join(StocktakeLine, StocktakeLine.id == StocktakeResolution.line_id)
        .join(Stocktake, Stocktake.id == StocktakeLine.stocktake_id)
        .join(InventoryItem, InventoryItem.id == StocktakeLine.inventory_item_id)
        .filter(
            StocktakeResolution.org_id == org_id,
            StocktakeResolution.reason == "broken",
            StocktakeResolution.occurred_on >= year_ago,
        )
        .order_by(StocktakeResolution.occurred_on.desc())
        .all()
    )
    remission_measures = measure(session, org_id, [(row[3], row[0].quantity) for row in remission_rows], today)
    remissions = [
        {
            "product": _base_name(item.name),
            "quantity": _s(res.quantity),
            "unit": item.unit,
            "date": res.occurred_on.isoformat(),
            "lal": m["lal"],
            "duty": m["duty"],
            "stocktake_id": str(st.id),
        }
        for (res, _line, st, item), m in zip(remission_rows, remission_measures, strict=True)
    ]

    profiles = session.query(AlcoholProductProfile).filter(AlcoholProductProfile.org_id == org_id).all()
    active = [p for p in profiles if p.is_active]
    incomplete = [
        p.inventory_name for p in active if not p.pack_volume_ml or not (p.excise_category or p.customs_product_code)
    ]
    entry = current.get("entry") or {}
    return {
        "today": today.isoformat(),
        "frequency": frequency,
        "this_period": {
            "period_start": current["period_start"],
            "label": current["label"],
            "total_lal": current.get("total_lal"),
            "estimate": entry.get("total") if entry.get("complete") else None,
            "due": current["due"],
        },
        "unlodged_periods": unlodged,
        "overdue_periods": overdue,
        "year": {
            "from": year_ago.isoformat(),
            "duty": _money(year_duty),
            "lodged_duty": _money(lodged_duty),
            "estimated_duty": _money(estimated_duty),
            "lodged_periods": lodged_count,
            "six_monthly_allowed": year_duty <= SIX_MONTHLY_LIMIT,
            "twelve_monthly_allowed": year_duty <= TWELVE_MONTHLY_LIMIT,
            "six_monthly_limit": _money(SIX_MONTHLY_LIMIT),
            "twelve_monthly_limit": _money(TWELVE_MONTHLY_LIMIT),
            "monthly_until": monthly_until.isoformat() if monthly_until else None,
        },
        "stocktake": {
            **plan,
            "open_differences": len(variances),
            # "cost" is the module's money figure for the difference: excise duty here.
            "open_duty": _money(sum((abs(Decimal(v["cost"])) for v in variances if v.get("cost")), Decimal("0"))),
        },
        "remissions": remissions,
        "setup": {"products": len(active), "incomplete": incomplete},
    }


def _money(value: Decimal) -> str:
    return f"{Decimal(value).quantize(_Q2, ROUND_HALF_UP):f}"


def _months_before(day: date, months: int) -> date:
    serial = day.year * 12 + day.month - 1 - months
    return date(serial // 12, serial % 12 + 1, 1)


def _months_after(day: date, months: int) -> date:
    serial = day.year * 12 + day.month - 1 + months
    return date(serial // 12, serial % 12 + 1, min(day.day, 28))


def reminder(session: Session, org_id: UUID, profile, today: date | None = None) -> dict | None:
    """The monthly system check: the latest finished period not yet recorded as lodged.

    On from the period the NZ Alcohol module was switched on (or from "Remind me from" when
    set), so a new org is reminded about the month it is in, not years of history. Only the
    latest finished period is ever raised. One click opens the figures: Sales -> Excise for
    that month when lodging monthly, else the Customs page on that period.
    """
    cfg = settings_for(profile)
    today = today or date.today()
    start, _end = previous_period(period_for(today, cfg["frequency"])[0], cfg["frequency"])
    if not cfg["reminders_from"]:
        return None
    since = date.fromisoformat(cfg["reminders_from"])
    if start < period_for(since, cfg["frequency"])[0]:
        return None
    current = draft(session, org_id, start, cfg["frequency"], today=today)
    if current["status"] == "lodged":
        return None
    due = date.fromisoformat(current["due"])
    customs_href = f"/compliant/nz-alcohol/customs?period={current['period_start']}"
    if current.get("legacy_unavailable"):
        return {
            "id": f"excise-lodgement-{current['period_start']}",
            "title": f"Review per-CCA excise for {current['label']}",
            "description": "Multiple-site removals need a complete entry for each source CCA. The legacy draft cannot be lodged.",
            "due_date": due.isoformat(),
            "href": customs_href,
            "action_label": "Review CCA movements",
            "overdue": today > due,
        }
    nil = not current["lines"] and not current["adjustments"]
    entry = current.get("entry") or {}
    if nil:
        what = "nil return"
    elif entry.get("complete"):
        what = f"entry: est. ${Decimal(entry['total']):,.2f} ({current['total_lal']} LAL)"
    else:
        what = f"entry: {current['total_lal']} LAL"
    from app.utils.config_loader import config

    # Sales -> Excise shows one month and lives in the Sales module; otherwise lodge from Customs.
    monthly = cfg["frequency"] == "monthly" and bool(getattr(config, "crm_enabled", False))
    return {
        "id": f"excise-lodgement-{current['period_start']}",
        "title": f"Excise {'nil return' if nil else 'entry'} for {current['label']} due {due.strftime('%-d %b %Y')}",
        "description": (
            f"{'Overdue: ' if today > due else ''}Lodge the {current['label']} {what} with Customs, then record it "
            "as lodged."
        ),
        "due_date": due.isoformat(),
        "href": f"/crm/excise?month={current['period_start'][:7]}" if monthly else customs_href,
        "action_label": "See the figures",
        "overdue": today > due,
    }
