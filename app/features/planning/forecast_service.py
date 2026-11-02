"""Demand from somewhere other than typing it in (GL-P07 B3).

- **Contract orders.** Each confirmed contract order line for a product a workflow makes becomes
  planning demand once (`source='contract'`, `source_ref` = the line). A line that changes or
  stops being confirmed updates or cancels its demand, until batches are planned for it.
- **Forecast.** Per product (a workflow output), a weekly sales rate from sales history over a
  window. Once there's a year of history, it's scaled by how the coming four weeks sold last year
  against that year's average. It says when stock runs out, counting stock on hand and batches
  already planned. With a stock target (weeks of cover), it suggests how much to plan and by
  when. Accepting a suggestion makes it `source='forecast'` demand.

Sales lines name the Biz-E product (the final product's stock name). A product is the workflow
output plus the names its stock has carried, so a sale of "Navy Gin 700ml" counts for the output
whose lots are called that.
"""

from __future__ import annotations

import math
from datetime import date, timedelta
from decimal import ROUND_CEILING, Decimal
from uuid import UUID

from app.core.db.models.inventory_item import InventoryItem
from app.core.db.repositories.inventory_repo import producer_stock_predicate
from app.core.utils.time import utc_now
from app.features.planning import demand_service
from app.features.planning.batch_models import PlanningBatch, PlanningWorkflowSetting
from app.features.planning.models import PlanningDemand, PlanningStockTarget

DEFAULT_WINDOW_WEEKS = 12
MAX_WINDOW_WEEKS = 52
SEASON_CLAMP = (Decimal("0.5"), Decimal("2"))


def _num(value: Decimal) -> str:
    return format(value.normalize(), "f") if value else "0"


# ── Contract orders ─────────────────────────────────────────────────────────────────────


def sync_contract_demand(db, org_id: UUID) -> dict:
    """Confirmed contract order lines become demand once. Returns what changed."""
    from app.features.contract_manufacturing.models.orders import ContractCustomer, ContractOrder
    from app.features.contract_manufacturing.services.demand import contract_demand

    outputs = {row["id"]: row for row in demand_service.output_catalog(db, org_id)}
    lines = {row["demand_id"]: row for row in contract_demand(db, org_id) if row["product_key"] in outputs}
    existing = {
        row.source_ref: row
        for row in db.query(PlanningDemand).filter(PlanningDemand.org_id == org_id, PlanningDemand.source == "contract")
    }
    planned = {
        row.demand_id
        for row in db.query(PlanningBatch.demand_id).filter(
            PlanningBatch.org_id == org_id, PlanningBatch.status != "cancelled"
        )
    }
    orders = {
        str(order.id): order
        for order in db.query(ContractOrder).filter(
            ContractOrder.org_id == org_id,
            ContractOrder.id.in_({UUID(line["order_id"]) for line in lines.values()}),
        )
    }
    customers = {
        str(row.id): row.name
        for row in db.query(ContractCustomer).filter(
            ContractCustomer.org_id == org_id,
            ContractCustomer.id.in_({UUID(line["customer_id"]) for line in lines.values()}),
        )
    }
    changed = {"added": 0, "updated": 0, "cancelled": 0}
    for line_id, line in lines.items():
        order = orders.get(line["order_id"])
        reference = " · ".join(
            part for part in (customers.get(line["customer_id"]), order.reference if order else None) if part
        )
        quantity, due = Decimal(line["quantity"]), date.fromisoformat(line["due_date"])
        row = existing.get(line_id)
        if row is None:
            db.add(
                PlanningDemand(
                    org_id=org_id,
                    reference=(reference or "Contract order")[:200],
                    source_output_id=UUID(line["product_key"]),
                    quantity=quantity,
                    unit=outputs[line["product_key"]]["unit"],
                    due_date=due,
                    priority=50,
                    source="contract",
                    source_ref=line_id,
                )
            )
            changed["added"] += 1
        elif row.status == "open" and row.id not in planned and (row.quantity, row.due_date) != (quantity, due):
            row.quantity, row.due_date = quantity, due
            changed["updated"] += 1
    for line_id, row in existing.items():
        # No longer confirmed (completed, cancelled or back to draft): its demand goes, unless
        # batches are already planned for it, which someone has to review.
        if line_id not in lines and row.status == "open" and row.id not in planned:
            row.status = "cancelled"
            changed["cancelled"] += 1
    db.flush()
    return changed


# ── Forecast ────────────────────────────────────────────────────────────────────────────


def finished_products(db, org_id):
    """Outputs that are sold, not used up: made by a workflow's last step, and taken as an input
    by no step."""
    from app.core.db.models.step import Step

    steps = db.query(Step).filter(Step.org_id == org_id).all()
    used = {
        str(item.get("source_output_id"))
        for step in steps
        for item in (step.inputs if isinstance(step.inputs, list) else [])
        if isinstance(item, dict) and item.get("source_output_id")
    }
    last = {}
    for step in steps:
        if step.process_id not in last or step.position > last[step.process_id].position:
            last[step.process_id] = step
    final = {
        str(output.get("id"))
        for step in last.values()
        for output in (step.outputs if isinstance(step.outputs, list) else [])
        if isinstance(output, dict)
    }
    return {
        row["id"]: row
        for row in demand_service.output_catalog(db, org_id)
        if row["id"] in final and row["id"] not in used
    }


def _product_names(db, org_id, outputs):
    """Each output's sales names: its own name and the names its stock has carried."""
    names = {output_id: {row["name"].strip().casefold()} for output_id, row in outputs.items()}
    for name, output_id in (
        db.query(InventoryItem.name, InventoryItem.source_output_id)
        .filter(
            InventoryItem.org_id == org_id,
            InventoryItem.inventory_type == "final_product",
            InventoryItem.source_output_id.in_([UUID(key) for key in outputs]),
        )
        .distinct()
    ):
        names[str(output_id)].add(name.strip().casefold())
    return names


def _weekly(lines, names, start, weeks):
    """Units sold in each of `weeks` weeks from `start`, for these product names."""
    totals = [Decimal(0)] * weeks
    for line in lines:
        if line.product_name.strip().casefold() not in names:
            continue
        index = (line.sold_on - start).days // 7
        if 0 <= index < weeks:
            totals[index] += line.units
    return totals


def _on_hand(db, org_id, names, output_ids):
    rows = (
        db.query(InventoryItem.name, InventoryItem.source_output_id, InventoryItem.quantity)
        .filter(
            InventoryItem.org_id == org_id,
            InventoryItem.inventory_type == "final_product",
            InventoryItem.quantity > 0,
            producer_stock_predicate(),
        )
        .all()
    )
    totals = {output_id: Decimal(0) for output_id in output_ids}
    for name, source_output_id, quantity in rows:
        key = str(source_output_id) if source_output_id else None
        if key not in totals:
            key = next((oid for oid in output_ids if name.strip().casefold() in names[oid]), None)
        if key is not None:
            totals[key] += quantity
    return totals


def forecast(db, org_id: UUID, *, today: date, window_weeks: int = DEFAULT_WINDOW_WEEKS) -> list[dict]:
    from app.features.crm.services.sales_sources import first_sale, sale_lines

    if not isinstance(window_weeks, int) or isinstance(window_weeks, bool) or not 1 <= window_weeks <= MAX_WINDOW_WEEKS:
        raise ValueError(f"Choose a window of 1 to {MAX_WINDOW_WEEKS} weeks")
    outputs = finished_products(db, org_id)
    if not outputs:
        return []
    names = _product_names(db, org_id, outputs)
    # Two years back: the window, and last year's same weeks for the season.
    start = today - timedelta(weeks=104)
    try:
        lines, _ = sale_lines(db, org_id, start, today)
        since = first_sale(db, org_id)
    except Exception:  # noqa: BLE001 -- no sales source connected is "no history", not an error
        lines, since = [], None
    history_weeks = max(0, (today - since).days // 7) if since else 0
    on_hand = _on_hand(db, org_id, names, list(outputs))
    targets = {
        str(row.source_output_id): row.weeks_of_cover
        for row in db.query(PlanningStockTarget).filter(PlanningStockTarget.org_id == org_id)
    }
    settings = {
        str(row.source_output_id): row
        for row in db.query(PlanningWorkflowSetting).filter(PlanningWorkflowSetting.org_id == org_id)
    }
    batches = (
        db.query(PlanningBatch)
        .filter(PlanningBatch.org_id == org_id, PlanningBatch.status.notin_(("started", "cancelled")))
        .all()
    )
    unplanned = (
        db.query(PlanningDemand)
        .filter(
            PlanningDemand.org_id == org_id,
            PlanningDemand.status == "open",
            # Accepted forecast demand is stock you've decided to make. Customer orders aren't:
            # they're part of what sells, which the rate already counts.
            PlanningDemand.source == "forecast",
            PlanningDemand.id.notin_({batch.demand_id for batch in batches}),
        )
        .all()
    )
    result = []
    for output_id, output in outputs.items():
        weekly = _weekly(lines, names[output_id], start, 104)
        weeks = min(window_weeks, history_weeks) or window_weeks
        recent = sum(weekly[104 - weeks :], Decimal(0))
        rate = recent / weeks if history_weeks else Decimal(0)
        season = None
        if history_weeks >= 52 and rate:
            average = sum(weekly[52:104], Decimal(0)) / 52
            coming = sum(weekly[52:56], Decimal(0)) / 4  # the same four weeks, a year ago
            if average:
                season = min(max(coming / average, SEASON_CLAMP[0]), SEASON_CLAMP[1])
                rate *= season
        planned = sorted(
            (
                batch.theoretical_ready_date
                or batch.proposed_start_date + timedelta(days=batch.snapshot.get("elapsed_days", 0)),
                batch.quantity,
            )
            for batch in batches
            if str(batch.source_output_id) == output_id
        )
        planned_total = sum((quantity for _, quantity in planned), Decimal(0))
        accepted = [(row.due_date, row.quantity) for row in unplanned if str(row.source_output_id) == output_id]
        waiting = sum((quantity for _, quantity in accepted), Decimal(0))
        stock = on_hand[output_id]
        # Accepted forecast demand isn't a batch yet, but it's stock you've decided to make.
        planned = sorted(planned + accepted)
        runs_out = _runs_out(stock, planned, rate, today)
        projection = _projection(stock, planned, rate, today, 12)
        target = targets.get(output_id)
        setting = settings.get(output_id)
        suggestion = None
        cover = Decimal((runs_out - today).days) / 7 if runs_out else None
        if target and rate and cover is not None and cover < target:
            # Stock runs out before the target: make enough to push that date out to it.
            short = rate * (target - cover)
            if short > 0:
                batch_size = setting.batch_quantity if setting else None
                count = int((short / batch_size).to_integral_value(rounding=ROUND_CEILING)) if batch_size else None
                quantity = batch_size * count if batch_size else short.to_integral_value(rounding=ROUND_CEILING)
                elapsed = timedelta(seconds=setting.snapshot.get("elapsed_seconds", 0)) if setting else timedelta()
                need_by = runs_out
                plan_by = need_by - timedelta(days=math.ceil(elapsed.total_seconds() / 86400))
                suggestion = {
                    "quantity": _num(quantity),
                    "batches": count,
                    "need_by": max(need_by, today).isoformat(),
                    "plan_by": max(plan_by, today).isoformat(),
                    "late": plan_by < today,
                }
        result.append(
            {
                "output_id": output_id,
                "name": output["name"],
                "unit": output["unit"],
                "process_id": output["process_id"],
                "weekly_rate": _num(rate.quantize(Decimal("0.1")) if rate else Decimal(0)),
                "window_weeks": weeks if history_weeks else window_weeks,
                "seasonal_factor": _num(season.quantize(Decimal("0.01"))) if season else None,
                "history_weeks": history_weeks,
                "on_hand": _num(stock),
                "planned": _num(planned_total),
                "waiting": _num(waiting),
                "runs_out": runs_out.isoformat() if runs_out else None,
                "projection": projection,
                "weeks_of_cover": _num(cover.quantize(Decimal("0.1"))) if cover is not None else None,
                "target_weeks": _num(target) if target else None,
                "suggestion": suggestion,
                "sentence": _sentence(output, rate, runs_out, target, suggestion, history_weeks),
            }
        )
    result.sort(key=lambda row: (row["runs_out"] is None, row["runs_out"] or "", row["name"]))
    return result


def _runs_out(stock, planned, rate, today):
    """The day stock reaches zero at this rate, with planned batches arriving as they're ready."""
    if not rate:
        return None
    per_day = rate / 7
    day, left = today, stock
    for ready, quantity in planned:
        empty = day + timedelta(days=int(left / per_day))
        if empty < ready:
            return empty
        left -= per_day * (ready - day).days
        left += quantity
        day = ready
    return day + timedelta(days=int(left / per_day))


def _projection(stock, planned, rate, today, weeks):
    """Stock expected at the end of each of the next `weeks` weeks: what's on hand, plus batches
    ready by then, less sales at the current rate. Below zero means short."""
    rows = []
    for week in range(1, weeks + 1):
        end = today + timedelta(weeks=week)
        arriving = sum((quantity for ready, quantity in planned if ready <= end), Decimal(0))
        level = stock + arriving - rate * week
        rows.append({"week_ending": end.isoformat(), "stock": _num(level.quantize(Decimal("1")))})
    return rows


def _day(value):
    return f"{value.day} {value.strftime('%b')}"


def _sentence(output, rate, runs_out, target, suggestion, history_weeks):
    name, unit = output["name"], output["unit"]
    if not history_weeks:
        return f"No sales of {name} yet, so there's no forecast."
    if not rate:
        return f"{name} hasn't sold recently."
    pace = f"{_num(rate.quantize(Decimal('1')))} {unit} a week"
    if suggestion:
        what = (
            f"plan {suggestion['batches']} batch{'es' if suggestion['batches'] != 1 else ''}"
            if suggestion["batches"]
            else f"plan {suggestion['quantity']} {unit}"
        )
        when = "now" if suggestion["late"] else f"by {_day(date.fromisoformat(suggestion['plan_by']))}"
        lead = f"{name} runs out {_day(runs_out)} at {pace}" if runs_out else f"{name} sells {pace}"
        return f"{lead}; {what} {when} to keep {_num(target)} weeks' cover."
    if runs_out:
        return f"{name} runs out {_day(runs_out)} at {pace}."
    return f"{name} sells {pace}."


def set_target(db, org_id: UUID, output_id: UUID, weeks) -> PlanningStockTarget | None:
    """Weeks of cover to keep of a product; blank clears it."""
    if str(output_id) not in {row["id"] for row in demand_service.output_catalog(db, org_id)}:
        raise ValueError("Choose a product this business makes")
    row = (
        db.query(PlanningStockTarget)
        .filter(PlanningStockTarget.org_id == org_id, PlanningStockTarget.source_output_id == output_id)
        .first()
    )
    if weeks in (None, ""):
        if row is not None:
            db.delete(row)
            db.flush()
        return None
    try:
        weeks = Decimal(str(weeks))
    except Exception as exc:  # noqa: BLE001
        raise ValueError("Weeks of cover must be a number from 0.5 to 104") from exc
    if not weeks.is_finite() or not Decimal("0.5") <= weeks <= 104:
        raise ValueError("Weeks of cover must be a number from 0.5 to 104")
    if row is None:
        row = PlanningStockTarget(org_id=org_id, source_output_id=output_id, weeks_of_cover=weeks)
        db.add(row)
    else:
        row.weeks_of_cover = weeks
        row.updated_at = utc_now()
    db.flush()
    return row


def accept_suggestion(db, org_id: UUID, output_id: UUID, *, today: date) -> PlanningDemand:
    """The forecast's suggestion for a product becomes demand to plan."""
    row = next((row for row in forecast(db, org_id, today=today) if row["output_id"] == str(output_id)), None)
    if row is None or row["suggestion"] is None:
        raise ValueError("There's nothing to plan for this product right now")
    demand = demand_service.create_demand(
        db,
        org_id,
        {
            "reference": f"Forecast · {row['target_weeks']} weeks' cover of {row['name']}"[:200],
            "source_output_id": str(output_id),
            "quantity": row["suggestion"]["quantity"],
            "due_date": row["suggestion"]["need_by"],
            "priority": 20,
        },
    )
    demand.source = "forecast"
    db.flush()
    return demand
