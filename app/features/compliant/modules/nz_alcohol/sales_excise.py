"""Excise estimate per month from sales (Sales -> Excise).

One row per product and strength ("Wildflower - 44%"):

    supplementary quantity (L) = units sold x pack volume       50 x 700 mL = 35 L
    litres of alcohol (LAL)    = litres x ABV                   35 x 0.44   = 15.4
    excise duty                = LAL (or litres) x rate         15.4 x $71.034
    alcohol levy               = litres x levy cents / 100
    GST on duty and levy       = 15% of the two

ABV comes from the batch each sale was matched to, else the product's fallback ABV, so a
month with two batches at different strengths shows two rows. Rates are the ones in force
on the first of the month (they change on 1 July, never mid-month): the org's own rate
for a tariff item if it typed one, else the built-in Customs guide (``excise_tariff``).

This estimates duty on what was *sold*. Customs charges duty on what was *removed* from the
licensed area; the lodgement draft on Compliance -> Customs is the figure to lodge.
"""

from __future__ import annotations

from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.utils.unit_conversion import is_count_unit, normalize_unit
from app.features.compliant.models.alcohol_product_profile import AlcoholProductProfile
from app.features.compliant.models.excise import ExciseRate
from app.features.compliant.modules.nz_alcohol import excise_tariff
from app.features.compliant.modules.nz_alcohol.excise import (
    _Q2,
    _Q4,
    _base_name,
    _litres,
    _lot_abv,
    _s,
    duty_for,
    resolve_rate,
    tariff_item_for,
)
from app.features.crm.services import sales_sources

MAX_MONTHS = 36


def month_start(day: date) -> date:
    return day.replace(day=1)


def next_month(start: date) -> date:
    return date(start.year + (start.month == 12), start.month % 12 + 1, 1)


def parse_month(value: str) -> date:
    """'2026-09' -> date(2026, 9, 1)."""
    try:
        year, month = str(value).strip().split("-")[:2]
        return date(int(year), int(month), 1)
    except (TypeError, ValueError):
        raise ValueError("month must look like 2026-09") from None


def _display_name(product: str) -> str:
    """'Wildflower - final product' -> 'Wildflower': the suffix is how outputs are named, not the product."""
    marker = " - final product"
    return product[: -len(marker)] if product.lower().endswith(marker) else product


def _abv_label(abv: Decimal | None) -> str:
    if abv is None:
        return "ABV unknown"
    return f"{_s(abv.quantize(Decimal('0.01'), ROUND_HALF_UP))}%"


class _Context:
    """Lookups shared across every month of one request."""

    def __init__(self, session: Session, org_id: UUID):
        from app.core.backend.go_live import workflow_outputs

        self.session = session
        self.org_id = org_id
        self.profiles = {
            p.inventory_name.casefold(): p
            for p in session.query(AlcoholProductProfile).filter(AlcoholProductProfile.org_id == org_id).all()
            if p.is_active
        }
        self.rates = session.query(ExciseRate).filter(ExciseRate.org_id == org_id).all()
        self.units = {o["name"].casefold(): o["unit"] for o in workflow_outputs(session, org_id)["final_outputs"]}

    def unit_for(self, product: str, profile) -> str:
        unit = self.units.get(product.casefold())
        if unit:
            return unit
        return "bottles" if profile is not None and profile.pack_volume_ml else "units"


def _report(ctx: _Context, start: date, lines, unmapped, today: date) -> dict:
    rows: dict[tuple[str, str | None], dict] = {}
    for line in lines:
        product = _base_name(line.product_name)
        profile = ctx.profiles.get(product.casefold())
        parts = []
        covered = Decimal("0")
        for item, qty in line.batches:
            parts.append((qty, item.unit, _lot_abv(ctx.session, item, profile)))
            covered += qty
        rest = line.units - covered
        if rest > 0:
            fallback = (
                Decimal(str(profile.abv_percent)) if profile is not None and profile.abv_percent is not None else None
            )
            parts.append((rest, ctx.unit_for(product, profile), fallback))
        for qty, unit, abv in parts:
            key = (product.casefold(), _s(abv) if abv is not None else None)
            row = rows.setdefault(
                key,
                {
                    "product": product,
                    "abv": abv,
                    "profile": profile,
                    "unit": unit,
                    "units": Decimal("0"),
                    "litres": Decimal("0"),
                    "litres_known": True,
                    "sales": 0,
                },
            )
            row["units"] += qty
            row["sales"] += 1
            litres = _litres(qty, unit, profile)
            if litres is None:
                row["litres_known"] = False
            else:
                row["litres"] += litres

    out_rows = []
    problems: dict[tuple[str, str], dict] = {}
    totals = {k: Decimal("0") for k in ("litres", "lal", "duty", "levy", "gst")}

    def problem(product: str, reason: str, fix: str) -> None:
        problems.setdefault((product, reason), {"product": product, "reason": reason, "fix": fix})

    for row in sorted(rows.values(), key=lambda r: (r["product"].casefold(), -(r["abv"] or 0))):
        product, abv, profile = row["product"], row["abv"], row["profile"]
        litres = row["litres"].quantize(_Q4, ROUND_HALF_UP) if row["litres_known"] else None
        lal = (litres * abv / 100).quantize(_Q4, ROUND_HALF_UP) if litres is not None and abv is not None else None
        tariff = tariff_item_for(profile, abv)
        rate = resolve_rate(ctx.rates, tariff, start) if tariff else None
        duty = duty_for(rate, litres, lal) if litres is not None and lal is not None else None
        levy_class = excise_tariff.levy_rate(abv, start)
        levy = (
            (litres * levy_class[1] / 100).quantize(_Q2, ROUND_HALF_UP) if levy_class and litres is not None else None
        )
        gst = ((duty or 0) + (levy or 0)) * excise_tariff.GST_RATE if duty is not None or levy is not None else None
        gst = gst.quantize(_Q2, ROUND_HALF_UP) if gst is not None else None

        if profile is None:
            problem(product, "Not set up as an excise product", "customs")
        else:
            if litres is None:
                problem(product, "Pack volume missing", "customs")
            if abv is None:
                problem(product, "No ABV on the batch or the product", "customs")
            if abv is not None and tariff is None:
                problem(product, "Choose a product type so a duty rate applies", "customs")
            if tariff and rate is None and lal is not None:
                problem(product, f"No duty rate for {tariff} in {start.strftime('%B %Y')}", "customs")

        for key, value in (("litres", litres), ("lal", lal), ("duty", duty), ("levy", levy), ("gst", gst)):
            if value is not None:
                totals[key] += value
        out_rows.append(
            {
                "label": f"{_display_name(product)} - {_abv_label(abv)}",
                "product": product,
                "abv_percent": _s(abv) if abv is not None else None,
                "units": _s(row["units"]),
                "unit": row["unit"] if is_count_unit(row["unit"]) else normalize_unit(row["unit"]),
                "supplementary_litres": _s(litres) if litres is not None else None,
                "lal": _s(lal) if lal is not None else None,
                "tariff_item": tariff,
                "rate": _s(rate[0]) if rate else None,
                "basis": rate[1] if rate else None,
                "duty": f"{duty:f}" if duty is not None else None,
                "levy_class": levy_class[0] if levy_class else None,
                "levy_cents_per_litre": _s(levy_class[1]) if levy_class else None,
                "levy": f"{levy:f}" if levy is not None else None,
                "gst": f"{gst:f}" if gst is not None else None,
                "sales": row["sales"],
            }
        )

    end = next_month(start)
    customs_total = totals["duty"] + totals["levy"]
    return {
        "month": start.strftime("%Y-%m"),
        "label": start.strftime("%B %Y"),
        "complete": today >= end,
        "rows": out_rows,
        "totals": {
            "litres": _s(totals["litres"]),
            "lal": _s(totals["lal"]),
            "duty": f"{totals['duty'].quantize(_Q2):f}",
            "levy": f"{totals['levy'].quantize(_Q2):f}",
            "customs": f"{customs_total.quantize(_Q2):f}",
            "gst": f"{totals['gst'].quantize(_Q2):f}",
        },
        "problems": list(problems.values()),
        "unmapped": {
            "count": len(unmapped),
            "lines": [
                {
                    "date": u.sold_on.isoformat(),
                    "reference": u.reference,
                    "description": u.description,
                    "quantity": _s(u.quantity) if u.quantity is not None else None,
                }
                for u in unmapped[:50]
            ],
        },
    }


def _sources(session: Session, org_id: UUID) -> list[str]:
    return [s.label for s in sales_sources.connected_sources(session, org_id)]


def month_report(session: Session, org_id: UUID, start: date, today: date | None = None) -> dict:
    start = month_start(start)
    lines, unmapped = sales_sources.sale_lines(session, org_id, start, next_month(start))
    report = _report(_Context(session, org_id), start, lines, unmapped, today or date.today())
    return {**report, "sources": _sources(session, org_id), "rates_source": rates_source()}


def months(session: Session, org_id: UUID, today: date | None = None) -> list[dict]:
    """Every month from the first sale to now (at most ``MAX_MONTHS``), newest first, with its totals."""
    today = today or date.today()
    first = sales_sources.first_sale(session, org_id)
    if first is None:
        return []
    current = month_start(today)
    earliest = month_start(first)
    starts = [current]
    while len(starts) < MAX_MONTHS and starts[-1] > earliest:
        prev = starts[-1]
        starts.append(date(prev.year - (prev.month == 1), (prev.month - 2) % 12 + 1, 1))
    lines, unmapped = sales_sources.sale_lines(session, org_id, starts[-1], next_month(current))
    by_month: dict[date, tuple[list, list]] = {s: ([], []) for s in starts}
    for line in lines:
        by_month[month_start(line.sold_on)][0].append(line)
    for u in unmapped:
        by_month[month_start(u.sold_on)][1].append(u)
    ctx = _Context(session, org_id)
    out = []
    for s in starts:
        report = _report(ctx, s, *by_month[s], today)
        out.append(
            {
                "month": report["month"],
                "label": report["label"],
                "complete": report["complete"],
                "lal": report["totals"]["lal"],
                "customs": report["totals"]["customs"],
                "needs_attention": bool(report["problems"] or report["unmapped"]["count"]),
            }
        )
    return out


def rates_source() -> dict:
    return {"excise": excise_tariff.SOURCE, "levy": excise_tariff.LEVY_SOURCE, "gst_rate": _s(excise_tariff.GST_RATE)}
