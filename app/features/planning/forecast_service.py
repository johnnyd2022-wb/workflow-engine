"""Stock cover: how fast each product sells, when it runs out, and what to make (GL-P07 B3).

Per workflow output:
- **Rate**: units sold per week over a window (default 12 weeks, 4 to 52), from every
  connected sales source. A sale counts for an output only through its product mapping's
  workflow output, never by name.
- **Seasonality**: with at least 12 months of sales, the coming weeks are scaled by how those
  same weeks last year compared with last year's average week (clamped to x0.25..x4).
  With less history there's no adjustment, and the row says so.
- **Available**: stock on hand (stock.on_hand) + output of live batches, less open demand
  that isn't itself a forecast (a planned order takes its stock first).
- **Runs out on**: today + available / daily rate.
- **Suggestion** (only with a stock target): enough to keep `weeks_of_cover` after the batch
  is made, rounded up to whole batches, planned by runs-out minus the workflow's elapsed days.

Anything unknown stays unknown, with the reason (no sales source, product not mapped, no batch
size set), never a guess.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import ROUND_CEILING, Decimal, InvalidOperation
from uuid import UUID

from app.core.utils.unit_conversion import is_count_unit
from app.features.planning.batch_models import PlanningWorkflowSetting
from app.features.planning.demand_service import output_catalog
from app.features.planning.models import PlanningDemand, PlanningStockTarget
from app.features.planning.stock import on_hand, planned_output

DEFAULT_WINDOW_WEEKS = 12
MIN_WINDOW_WEEKS, MAX_WINDOW_WEEKS = 4, 52
YEAR = timedelta(days=364)  # 52 weeks: the same weekdays a year ago
SEASON_MIN, SEASON_MAX = Decimal("0.25"), Decimal("4")
MAX_TARGET_WEEKS = Decimal("104")


@dataclass
class SalesHistory:
    connected: bool
    has_year: bool
    # output id -> [(sold_on, units)]
    by_output: dict[str, list[tuple[date, Decimal]]] = field(default_factory=dict)
    unmapped_products: dict[str, str] = field(default_factory=dict)
    # outputs some active product mapping sells, whether or not they sold in the year
    mapped_outputs: set[str] = field(default_factory=set)


def window_weeks(value) -> int:
    if value in (None, ""):
        return DEFAULT_WINDOW_WEEKS
    try:
        weeks = int(str(value))
    except ValueError as exc:
        raise ValueError(f"Choose a sales window of {MIN_WINDOW_WEEKS} to {MAX_WINDOW_WEEKS} weeks") from exc
    if not MIN_WINDOW_WEEKS <= weeks <= MAX_WINDOW_WEEKS:
        raise ValueError(f"Choose a sales window of {MIN_WINDOW_WEEKS} to {MAX_WINDOW_WEEKS} weeks")
    return weeks


def sales_history(db, org_id: UUID, *, today: date) -> SalesHistory:
    """The last 52 weeks of sales, by workflow output."""
    from app.features.crm.models.product_mapping import ProductMapping
    from app.features.crm.services.sales_sources import connected_sources, first_sale, sale_lines

    if not connected_sources(db, org_id):
        return SalesHistory(connected=False, has_year=False)
    first = first_sale(db, org_id)
    history = SalesHistory(connected=True, has_year=first is not None and first <= today - YEAR)
    history.mapped_outputs = _mapped_outputs(db, org_id)
    outputs: dict[str, set[str]] = {}
    for name, output_id in (
        db.query(ProductMapping.biz_e_product_name, ProductMapping.biz_e_source_output_id)
        .filter(ProductMapping.org_id == org_id, ProductMapping.is_active.is_(True))
        .all()
    ):
        outputs.setdefault(name, set())
        if output_id is not None:
            outputs[name].add(str(output_id))
    lines, _ = sale_lines(db, org_id, today - YEAR, today)
    for line in lines:
        targets = outputs.get(line.product_name, set())
        if len(targets) != 1:
            history.unmapped_products[line.product_name] = (
                "Sold, but its product mapping has no workflow output"
                if not targets
                else "Sold, but its product mappings point at different workflow outputs"
            )
            continue
        history.by_output.setdefault(next(iter(targets)), []).append((line.sold_on, Decimal(line.units)))
    return history


def _units(sales, start: date, end: date) -> Decimal:
    return sum((units for sold_on, units in sales if start <= sold_on < end), Decimal(0))


def weekly_rate(sales, *, today: date, weeks: int, has_year: bool):
    """(rate per week, seasonality factor or None, note)."""
    base = _units(sales, today - timedelta(weeks=weeks), today) / weeks
    if not has_year:
        return base, None, "Less than 12 months of sales, so no seasonal adjustment"
    year_average = _units(sales, today - YEAR, today) / 52
    if year_average <= 0:
        return base, None, "No sales in the last year to compare seasons with"
    ahead = _units(sales, today - YEAR, today - YEAR + timedelta(weeks=weeks)) / weeks
    factor = min(max(ahead / year_average, SEASON_MIN), SEASON_MAX)
    percent = int((factor * 100).to_integral_value())
    note = f"Last year the next {weeks} weeks sold {percent}% of an average week"
    return base * factor, factor, note


def _setting(db, org_id, output_id):
    return (
        db.query(PlanningWorkflowSetting)
        .filter(PlanningWorkflowSetting.org_id == org_id, PlanningWorkflowSetting.source_output_id == output_id)
        .order_by(PlanningWorkflowSetting.created_at, PlanningWorkflowSetting.id)
        .first()
    )


def _day(value: date, today: date) -> str:
    return f"{value.day} {value:%b}" + (f" {value.year}" if value.year != today.year else "")


def _amount(value: Decimal, unit: str) -> str:
    if is_count_unit(unit) or value >= 10:
        shown = str(int(value.to_integral_value()))
    else:
        shown = f"{value.quantize(Decimal('0.1')).normalize():f}"
    return f"{shown} {unit}"


def _num(value: Decimal | None):
    return None if value is None else format(value.normalize(), "f")


def cover_row(db, org_id, output, site, history: SalesHistory, *, today: date, weeks: int, target=None) -> dict:
    output_id = UUID(output["id"])
    unit = output["unit"]
    unknowns = []
    stock, stock_reasons = on_hand(db, org_id, output_id, unit, site, None, today=today)
    unknowns.extend(stock_reasons)
    on_hand_qty = sum((row.quantity for row in stock), Decimal(0))
    planned_qty = sum(
        (row.quantity for row in planned_output(db, org_id, output_id, unit, site, None, today=today)), Decimal(0)
    )
    open_demand = (
        db.query(PlanningDemand)
        .filter(
            PlanningDemand.org_id == org_id,
            PlanningDemand.source_output_id == output_id,
            PlanningDemand.unit == unit,
            PlanningDemand.status == "open",
            PlanningDemand.source == "manual",
        )
        .all()
    )
    ordered = sum((row.quantity for row in open_demand), Decimal(0))
    available = on_hand_qty + planned_qty - ordered

    rate = factor = None
    season_note = None
    if not history.connected:
        unknowns.append("No sales source is connected, so there is no sales rate")
    elif output["id"] not in history.by_output and output["id"] not in history.mapped_outputs:
        unknowns.append("No product mapping sells this output, so there is no sales rate")
    else:
        rate, factor, season_note = weekly_rate(
            history.by_output.get(output["id"], []), today=today, weeks=weeks, has_year=history.has_year
        )

    runs_out = None
    if rate is not None:
        if available <= 0:
            runs_out = today
        elif rate > 0:
            runs_out = today + timedelta(days=math.floor(available * 7 / rate))

    setting = _setting(db, org_id, output_id)
    elapsed_days = None
    batch_quantity = None
    if setting is None:
        unknowns.append("Set the batch size on the production board to get a suggestion")
    else:
        batch_quantity = setting.batch_quantity
        elapsed_days = math.ceil(int(setting.snapshot.get("elapsed_seconds") or 0) / 86400)

    target_weeks = target.weeks_of_cover if target is not None else None
    suggestion = None
    if target_weeks is not None and rate is not None and batch_quantity is not None:
        need = rate * (target_weeks * 7 + elapsed_days) / 7 - available
        if need > 0:
            count = int((need / batch_quantity).to_integral_value(rounding=ROUND_CEILING))
            due = runs_out or today
            suggestion = {
                "batches": count,
                "quantity": _num(count * batch_quantity),
                "plan_by": max(today, due - timedelta(days=elapsed_days)).isoformat(),
                "due_date": max(today, due).isoformat(),
            }

    summary = _summary(unit, rate, runs_out, available, target_weeks, suggestion, today, weeks)
    return {
        "source_output_id": output["id"],
        "name": output["name"],
        "unit": unit,
        "window_weeks": weeks,
        "weekly_rate": _num(rate.quantize(Decimal("0.01"))) if rate is not None else None,
        "seasonality_factor": _num(factor.quantize(Decimal("0.01"))) if factor is not None else None,
        "seasonality": season_note,
        "on_hand": _num(on_hand_qty),
        "planned": _num(planned_qty),
        "ordered": _num(ordered),
        "available": _num(available),
        "runs_out_on": runs_out.isoformat() if runs_out else None,
        "target_weeks": _num(target_weeks),
        "batch_quantity": _num(batch_quantity),
        "elapsed_days": elapsed_days,
        "suggestion": suggestion,
        "summary": summary,
        "sentence": _sentence(output["name"], summary),
        "unknowns": list(dict.fromkeys(unknowns)),
    }


def _summary(unit, rate, runs_out, available, target_weeks, suggestion, today, weeks):
    """What the stock cover says, without the product's name: the page shows that beside it."""
    if rate is None:
        return "No sales rate yet."
    if rate == 0:
        return f"No sales in the last {weeks} weeks."
    pace = f"{_amount(rate, unit)} a week"
    head = f"Has run out, selling {pace}" if available <= 0 else f"Runs out {_day(runs_out, today)} at {pace}"
    if suggestion:
        count = suggestion["batches"]
        when = date.fromisoformat(suggestion["plan_by"])
        by = "now" if when <= today else f"by {_day(when, today)}"
        return f"{head}; plan {count} batch{'es' if count != 1 else ''} {by}."
    if target_weeks is not None:
        return f"{head}; that covers your {_num(target_weeks)}-week target."
    return f"{head}."


def _sentence(name, summary):
    if summary.startswith("No "):
        return f"{name}: {summary[0].lower()}{summary[1:]}"
    return f"{name} {summary[0].lower()}{summary[1:]}"


def _site_target_filter(query, site):
    # Same site rule as stock: a NULL site is the default site's.
    from app.features.planning.stock import _at_site

    return query.filter(_at_site(PlanningStockTarget.site_id, site))


def cover(db, org_id: UUID, site, *, today: date, weeks: int) -> dict:
    """Every output that sells or has a target, soonest to run out first."""
    history = sales_history(db, org_id, today=today)
    targets = {
        str(row.source_output_id): row
        for row in _site_target_filter(
            db.query(PlanningStockTarget).filter(PlanningStockTarget.org_id == org_id), site
        ).all()
    }
    rows = []
    for output in output_catalog(db, org_id):
        if (
            output["id"] not in history.by_output
            and output["id"] not in targets
            and output["id"] not in history.mapped_outputs
        ):
            continue
        rows.append(
            cover_row(db, org_id, output, site, history, today=today, weeks=weeks, target=targets.get(output["id"]))
        )
    rows.sort(key=lambda row: (row["runs_out_on"] or "9999-12-31", row["name"].casefold()))
    return {
        "window_weeks": weeks,
        "sales_connected": history.connected,
        "seasonal": history.has_year,
        "products": rows,
        "unmapped_products": [
            {"product_name": name, "reason": reason} for name, reason in sorted(history.unmapped_products.items())
        ],
    }


def _mapped_outputs(db, org_id) -> set[str]:
    from app.features.crm.models.product_mapping import ProductMapping

    return {
        str(output_id)
        for (output_id,) in db.query(ProductMapping.biz_e_source_output_id)
        .filter(
            ProductMapping.org_id == org_id,
            ProductMapping.is_active.is_(True),
            ProductMapping.biz_e_source_output_id.isnot(None),
        )
        .distinct()
        .all()
    }


def _output(db, org_id, output_id):
    try:
        wanted = str(UUID(str(output_id)))
    except (ValueError, TypeError, AttributeError) as exc:
        raise ValueError("Choose a product output belonging to this business") from exc
    output = next((row for row in output_catalog(db, org_id) if row["id"] == wanted), None)
    if output is None:
        raise ValueError("Choose a product output belonging to this business")
    return output


def save_target(db, org_id: UUID, site, data) -> PlanningStockTarget | None:
    """Set, change or clear (weeks_of_cover null) the weeks of cover to keep of an output."""
    if not isinstance(data, dict) or set(data) - {"source_output_id", "weeks_of_cover", "site_id"}:
        raise ValueError("Unexpected stock target fields")
    output = _output(db, org_id, data.get("source_output_id"))
    raw = data.get("weeks_of_cover")
    weeks = None
    if raw not in (None, ""):
        if isinstance(raw, bool):
            raise ValueError("Weeks of cover must be a number")
        try:
            weeks = Decimal(str(raw))
        except InvalidOperation as exc:
            raise ValueError("Weeks of cover must be a number") from exc
        if not weeks.is_finite() or not 0 < weeks <= MAX_TARGET_WEEKS or weeks.as_tuple().exponent < -2:
            raise ValueError("Keep more than 0 and at most 104 weeks of cover, to two decimal places")
    row = (
        _site_target_filter(
            db.query(PlanningStockTarget).filter(
                PlanningStockTarget.org_id == org_id,
                PlanningStockTarget.source_output_id == UUID(output["id"]),
            ),
            site,
        )
        .with_for_update()
        .first()
    )
    if weeks is None:
        if row is not None:
            db.delete(row)
            db.flush()
        return None
    if row is None:
        row = PlanningStockTarget(org_id=org_id, source_output_id=UUID(output["id"]), site_id=site.id if site else None)
        db.add(row)
    row.weeks_of_cover = weeks
    db.flush()
    return row


RETRY_KEY = re.compile(r"[A-Za-z0-9_.:-]{8,110}")


def plan_forecast(db, org_id: UUID, data, key, *, today: date):
    """'Plan it': the suggestion becomes a forecast demand and is planned, in one request.
    Returns (demand, batches, changed). A retry with the same key returns the same demand."""
    from app.features.planning.batch_service import PlanningConflictError, _lock_org, plan_demand, resolve_planning_site

    if not isinstance(data, dict) or set(data) - {"source_output_id", "site_id", "window_weeks"}:
        raise ValueError("Unexpected planning fields")
    if not isinstance(key, str) or RETRY_KEY.fullmatch(key) is None:
        raise ValueError("Send an Idempotency-Key of 8 to 110 letters, numbers or separators")
    org = _lock_org(db, org_id)
    output = _output(db, org_id, data.get("source_output_id"))
    ref = "forecast:" + key
    demand = db.query(PlanningDemand).filter(PlanningDemand.org_id == org_id, PlanningDemand.source_ref == ref).first()
    if demand is not None:
        if demand.source != "forecast" or str(demand.source_output_id) != output["id"]:
            raise PlanningConflictError("This retry key was used for a different request")
        rows, _ = (
            plan_demand(db, org_id, demand.id, {"site_id": data.get("site_id")}, today=today)
            if demand.status == "open"
            else ([], False)
        )
        return demand, rows, False
    site = resolve_planning_site(db, org, data.get("site_id"))
    weeks = window_weeks(data.get("window_weeks"))
    history = sales_history(db, org_id, today=today)
    target = _site_target_filter(
        db.query(PlanningStockTarget).filter(
            PlanningStockTarget.org_id == org_id, PlanningStockTarget.source_output_id == UUID(output["id"])
        ),
        site,
    ).first()
    if target is None:
        raise PlanningConflictError("Set how many weeks of cover to keep before planning from it")
    row = cover_row(db, org_id, output, site, history, today=today, weeks=weeks, target=target)
    suggestion = row["suggestion"]
    if suggestion is None:
        raise PlanningConflictError(
            "Nothing to plan: " + (row["unknowns"][0] if row["unknowns"] else "stock covers the target")
        )
    demand = PlanningDemand(
        org_id=org_id,
        reference=f"Stock target: {output['name']}"[:200],
        source_output_id=UUID(output["id"]),
        quantity=Decimal(suggestion["quantity"]),
        unit=output["unit"],
        due_date=date.fromisoformat(suggestion["due_date"]),
        priority=0,
        source="forecast",
        source_ref=ref,
    )
    db.add(demand)
    db.flush()
    rows, _ = plan_demand(db, org_id, demand.id, {"site_id": data.get("site_id")}, today=today)
    return demand, rows, True
