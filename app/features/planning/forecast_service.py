"""Stock cover: how fast each product sells, when it runs out, and what to make (GL-P07 B3).

Per workflow output:
- **Rate**: units sold per week over a window (default 12 weeks, 4 to 52), from every
  connected sales source. A sale counts for an output only through its product mapping's
  workflow output, never by name. An output first sold inside the window is rated over the
  whole weeks since that first sale (at least 2), and the row says so.
- **Seasonality**: with a year of that output's own sales, the rate is scaled by how last
  year's next N weeks compared with last year's same trailing N weeks (clamped to x0.25..x4).
  The trailing rate is already at this season's level, so only the change ahead is applied.
  With less history there's no adjustment, and the row says so.
- **Available**: stock on hand (stock.on_hand) + output of live batches that aren't blocked,
  less open demand that isn't itself a forecast (a planned order takes its stock first).
  Blocked batches are listed on their own and never counted.
- **Runs out on**: open orders are netted first (engine.build_plan), then the daily rate is
  drawn from what's left, each batch only from its ready date (engine.days_until_out). The
  first day nothing is left, even if a later batch restocks it.
- **Suggestion** (only with a stock target): enough to keep `weeks_of_cover` after the batch
  is made, counting only supply ready by then, rounded up to whole batches, planned by
  runs-out minus the workflow's elapsed days.

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
from app.features.planning.engine import Demand, build_plan, days_until_out
from app.features.planning.models import PlanningDemand, PlanningStockTarget
from app.features.planning.stock import on_hand, planned_output, stock_key

DEFAULT_WINDOW_WEEKS = 12
MIN_WINDOW_WEEKS, MAX_WINDOW_WEEKS = 4, 52
YEAR = timedelta(days=364)  # 52 weeks: the same weekdays a year ago
SEASON_MIN, SEASON_MAX = Decimal("0.25"), Decimal("4")
MAX_TARGET_WEEKS = Decimal("104")
RUNOUT_HORIZON_DAYS = 5 * 365
MIN_RATE_WEEKS = 2  # a product first sold days ago isn't rated over a single sale


@dataclass
class SalesHistory:
    connected: bool
    has_year: bool  # some output has 12 months of sales: only says whether seasons can apply at all
    # output id -> [(sold_on, units)]
    by_output: dict[str, list[tuple[date, Decimal]]] = field(default_factory=dict)
    unmapped_products: dict[str, str] = field(default_factory=dict)
    # outputs some active product mapping sells, whether or not they sold in the year
    mapped_outputs: set[str] = field(default_factory=set)
    # output id -> its own first sale: seasonality needs a year of THIS output's history
    first_by_output: dict[str, date] = field(default_factory=dict)

    def output_has_year(self, output_id: str, today: date) -> bool:
        first = self.first_by_output.get(output_id)
        return first is not None and first <= today - YEAR


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
    # Back to the org's first sale (at most 3 years) so each output's own first sale is known;
    # rates and seasons read the last 52 weeks plus last year's trailing window (at most 52 more).
    start = today - YEAR
    if history.has_year:
        start = max(first, today - 3 * YEAR)
    lines, _ = sale_lines(db, org_id, start, today)
    for line in lines:
        targets = outputs.get(line.product_name, set())
        if len(targets) != 1:
            if line.sold_on < today - YEAR:
                continue  # only this year's unlinked sales are worth fixing
            history.unmapped_products[line.product_name] = (
                "Sold, but its product mapping has no workflow output"
                if not targets
                else "Sold, but its product mappings point at different workflow outputs"
            )
            continue
        output_id = next(iter(targets))
        if line.sold_on < history.first_by_output.get(output_id, date.max):
            history.first_by_output[output_id] = line.sold_on
        if line.sold_on >= today - YEAR - timedelta(weeks=MAX_WINDOW_WEEKS):
            history.by_output.setdefault(output_id, []).append((line.sold_on, Decimal(line.units)))
    return history


def _units(sales, start: date, end: date) -> Decimal:
    return sum((units for sold_on, units in sales if start <= sold_on < end), Decimal(0))


def weekly_rate(sales, *, today: date, weeks: int, has_year: bool, first_sale: date | None = None):
    """(rate per week, seasonality factor or None, season note, weeks rated over, rate note or None).

    `first_sale` is this output's own first sale: inside the window, the rate is over the whole
    weeks since then (at least MIN_RATE_WEEKS), not the full window."""
    rate_weeks = weeks
    rate_note = None
    if first_sale is not None and first_sale > today - timedelta(weeks=weeks):
        rate_weeks = min(weeks, max(MIN_RATE_WEEKS, math.ceil((today - first_sale).days / 7)))
        if rate_weeks < weeks:
            rate_note = f"First sold {rate_weeks} weeks ago, so the rate is over those {rate_weeks} weeks, not {weeks}"
    base = _units(sales, today - timedelta(weeks=weeks), today) / rate_weeks
    if not has_year:
        return base, None, "Less than 12 months of its sales, so no seasonal adjustment", rate_weeks, rate_note
    year_ago = today - YEAR
    # Its first sale must fall in (or before) the first week of last year's trailing window.
    if first_sale is not None and first_sale >= year_ago - timedelta(weeks=weeks - 1):
        note = f"Not a year and {weeks} weeks of its sales to compare seasons with, so no seasonal adjustment"
        return base, None, note, rate_weeks, rate_note
    before = _units(sales, year_ago - timedelta(weeks=weeks), year_ago) / weeks
    if before <= 0:
        return (
            base,
            None,
            f"No sales in the same {weeks} weeks last year to compare seasons with",
            rate_weeks,
            rate_note,
        )
    ahead = _units(sales, year_ago, year_ago + timedelta(weeks=weeks)) / weeks
    factor = min(max(ahead / before, SEASON_MIN), SEASON_MAX)
    percent = int((factor * 100).to_integral_value())
    note = f"Last year the next {weeks} weeks sold {percent}% of the {weeks} weeks before them"
    return base * factor, factor, note, rate_weeks, rate_note


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
    batches = planned_output(db, org_id, output_id, unit, site, None, today=today, blocked=False)
    planned_qty = sum((row.quantity for row in batches), Decimal(0))
    blocked_qty = sum(
        (row.quantity for row in planned_output(db, org_id, output_id, unit, site, None, today=today, blocked=True)),
        Decimal(0),
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
    # A planned order takes its stock first, netted the planner's way (due order, by ready date);
    # what's left, and what the orders still lack, is what sales draw on.
    key = stock_key(output_id, unit, site)
    orders = tuple(
        Demand(str(row.id), key, Decimal(row.quantity), row.due_date, row.priority or 0)
        for row in open_demand
        if Decimal(row.quantity).is_finite() and Decimal(row.quantity) > 0
    )
    netted = build_plan(orders, (*stock, *batches), (), today=today)
    left = netted.remaining
    short = sum((row.shortfall for row in netted.positions), Decimal(0))

    rate = factor = None
    rate_weeks = None
    season_note = rate_note = None
    if not history.connected:
        unknowns.append("No sales source is connected, so there is no sales rate")
    elif output["id"] not in history.by_output and output["id"] not in history.mapped_outputs:
        unknowns.append("No product mapping sells this output, so there is no sales rate")
    else:
        rate, factor, season_note, rate_weeks, rate_note = weekly_rate(
            history.by_output.get(output["id"], []),
            today=today,
            weeks=weeks,
            has_year=history.output_has_year(output["id"], today),
            first_sale=history.first_by_output.get(output["id"]),
        )

    runs_out = None
    lasts_beyond = False
    if rate is not None:
        if short > 0 or not any(row.ready_date <= today for row in left):
            runs_out = today
        elif rate > 0:
            days = math.floor(days_until_out(left, rate, today=today))
            # Past the horizon there's no date worth showing (and far enough out, no date at all).
            runs_out = today + timedelta(days=days) if days <= RUNOUT_HORIZON_DAYS else None
            lasts_beyond = days > RUNOUT_HORIZON_DAYS

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
        horizon = target_weeks * 7 + elapsed_days
        # Only supply ready by the end of the cover it has to give counts against it.
        ready = sum((row.quantity for row in left if (row.ready_date - today).days <= horizon), Decimal(0))
        need = rate * horizon / 7 - ready + short
        if need > 0:
            count = int((need / batch_quantity).to_integral_value(rounding=ROUND_CEILING))
            due = runs_out or today
            suggestion = {
                "batches": count,
                "quantity": _num(count * batch_quantity),
                "plan_by": max(today, due - timedelta(days=elapsed_days)).isoformat(),
                "due_date": max(today, due).isoformat(),
            }

    summary = _summary(unit, rate, runs_out, target_weeks, suggestion, today, weeks, lasts_beyond)
    blocked_note = None
    if blocked_qty > 0:
        blocked_note = f"{_amount(blocked_qty, unit)} in blocked batches aren't counted until they can start"
    return {
        "source_output_id": output["id"],
        "name": output["name"],
        "unit": unit,
        "window_weeks": weeks,
        "weekly_rate": _num(rate.quantize(Decimal("0.01"))) if rate is not None else None,
        "seasonality_factor": _num(factor.quantize(Decimal("0.01"))) if factor is not None else None,
        "seasonality": season_note,
        "rate_weeks": rate_weeks,
        "rate_note": rate_note,
        "on_hand": _num(on_hand_qty),
        "planned": _num(planned_qty),
        "blocked": _num(blocked_qty),
        "blocked_note": blocked_note,
        "ordered": _num(ordered),
        "available": _num(available),
        "runs_out_on": runs_out.isoformat() if runs_out else None,
        "target_weeks": _num(target_weeks),
        "batch_quantity": _num(batch_quantity),
        "elapsed_days": elapsed_days,
        "suggestion": suggestion,
        "summary": summary,
        "sentence": _sentence(output["name"], summary) + (f" {blocked_note}." if blocked_note else ""),
        "unknowns": list(dict.fromkeys(unknowns)),
    }


def _summary(unit, rate, runs_out, target_weeks, suggestion, today, weeks, lasts_beyond=False):
    """What the stock cover says, without the product's name: the page shows that beside it."""
    if rate is None:
        return "No sales rate yet."
    if rate == 0:
        return f"No sales in the last {weeks} weeks."
    pace = f"{_amount(rate, unit)} a week"
    if runs_out == today:
        head = f"Has run out, selling {pace}"
    elif lasts_beyond:
        head = f"Lasts more than {RUNOUT_HORIZON_DAYS // 365} years at {pace}"
    else:
        head = f"Runs out {_day(runs_out, today)} at {pace}"
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
