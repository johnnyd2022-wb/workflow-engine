"""Promise dates (GL-P07 B5): when an order can be ready, stated with what was checked.

Two questions:

- **An order already planned:** its lines' batches carry a ready date from the workflow's
  timing, placed on capacity by replan (B4). The *planned* ready date is the latest of them.
  The *forecast* is the same date only when no batch is blocked (materials short, timing
  unknown, a site requirement): a forecast is a date we expect to keep, so a blocked batch
  leaves it empty and says why. Contract orders and the customer portal show both.
- **A new order ("when can we deliver n?"):** from stock on hand first, then the workflow's own
  timing placed on the site's capacity from today. Materials are checked when the order is
  actually planned; the board then moves the date if something is short. The reason says so.

Nothing here writes to the database.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from uuid import UUID

from app.features.planning.batch_models import PlanningBatch
from app.features.planning.models import PlanningDemand

LIVE = ("blocked", "planned", "started")


def _fmt(day: date | None) -> str:
    return f"{day.day} {day:%b}" if day else ""


def line_dates(db, org_id: UUID, line_ids: list) -> dict[str, dict]:
    """{line_id: {planned, forecast, reason}} for contract lines that feed the planner."""
    refs = [str(line_id) for line_id in line_ids]
    if not refs:
        return {}
    demands = (
        db.query(PlanningDemand)
        .filter(
            PlanningDemand.org_id == org_id,
            PlanningDemand.source == "contract",
            PlanningDemand.source_ref.in_(refs),
        )
        .all()
    )
    by_demand = {row.id: row for row in demands}
    batches: dict[UUID, list[PlanningBatch]] = {}
    if by_demand:
        for batch in (
            db.query(PlanningBatch)
            .filter(
                PlanningBatch.org_id == org_id,
                PlanningBatch.demand_id.in_(list(by_demand)),
                PlanningBatch.status.in_(LIVE),
            )
            .all()
        ):
            batches.setdefault(batch.demand_id, []).append(batch)
    out: dict[str, dict] = {}
    for demand in demands:
        rows = batches.get(demand.id, [])
        if demand.status == "fulfilled":
            out[demand.source_ref] = {
                "planned": None,
                "forecast": None,
                "reason": "Made and finished",
                "done": "fulfilled",
            }
            continue
        if demand.status != "open":
            out[demand.source_ref] = {
                "planned": None,
                "forecast": None,
                "reason": "Not being planned",
                "done": "cancelled",
            }
            continue
        if not rows:
            out[demand.source_ref] = {"planned": None, "forecast": None, "reason": "Not planned yet"}
            continue
        readies = [b.theoretical_ready_date for b in rows]
        planned = max(readies) if all(readies) else None
        blocked = [b for b in rows if b.status == "blocked" or (b.blockers or [])]
        if planned is None:
            reason = "A batch's step timings aren't set yet"
            forecast = None
        elif blocked:
            first = next((str(x) for b in blocked for x in (b.blockers or []) if x), "a batch is blocked")
            reason = f"Planned for {_fmt(planned)}, not yet promised: {first}"
            forecast = None
        else:
            reason = f"Can be ready {_fmt(planned)}: materials checked and capacity placed"
            forecast = planned
        out[demand.source_ref] = {"planned": planned, "forecast": forecast, "reason": reason}
    return out


def order_dates(order, lines: dict[str, dict]) -> dict:
    """One order's dates from its lines. Lines already made, or no longer planned, don't hold
    the order back: the latest of the rest wins, and any of those without a date leaves it open."""
    rows = [lines.get(str(line.id)) for line in order.lines]
    active = [r for r in rows if not (r and r.get("done"))]
    if rows and not active:
        done = {r["done"] for r in rows}
        return {
            "planned_ready_date": None,
            "forecast_ready_date": None,
            "ready_reason": "Made and finished" if done == {"fulfilled"} else "Not being planned",
        }
    if not active or any(r is None for r in active):
        missing = sum(1 for r in active if r is None)
        return {
            "planned_ready_date": None,
            "forecast_ready_date": None,
            "ready_reason": "Not planned yet"
            if not active or missing == len(active)
            else f"{missing} line(s) not planned yet",
        }
    planned = [r["planned"] for r in active]
    forecast = [r["forecast"] for r in active]
    p = max(planned) if all(planned) else None
    f = max(forecast) if all(forecast) else None
    reason = next((r["reason"] for r in active if r["forecast"] is None), None) or active[0]["reason"]
    if f and len(active) > 1:
        reason = f"Can be ready {_fmt(f)}: every line's batches are checked and placed"
    return {
        "planned_ready_date": p.isoformat() if p else None,
        "forecast_ready_date": f.isoformat() if f else None,
        "ready_reason": reason,
    }


def dates_for_orders(db, org_id: UUID, orders) -> dict[str, dict]:
    lines = line_dates(db, org_id, [line.id for order in orders for line in order.lines])
    return {str(order.id): order_dates(order, lines) for order in orders}


def _quantity(value) -> Decimal:
    try:
        number = Decimal(str(value).strip())
    except (InvalidOperation, ValueError, TypeError, AttributeError):
        raise ValueError("Quantity must be a number") from None
    if not number.is_finite() or number <= 0 or number > Decimal(10_000_000):
        raise ValueError("Quantity must be more than 0")
    return number


def promise(db, org_id: UUID, data: dict, *, today: date) -> dict:
    """When could a new order for `quantity` of this output be ready?"""
    from app.core.db.models.organisation import Organisation
    from app.features.planning import placement
    from app.features.planning.batch_models import PlanningWorkflowSetting
    from app.features.planning.batch_service import resolve_planning_site
    from app.features.planning.stock import on_hand

    try:
        output_id = UUID(str((data or {}).get("source_output_id")))
    except ValueError:
        raise ValueError("Choose what the order is for") from None
    quantity = _quantity((data or {}).get("quantity"))
    setting = (
        db.query(PlanningWorkflowSetting)
        .filter(PlanningWorkflowSetting.org_id == org_id, PlanningWorkflowSetting.source_output_id == output_id)
        .first()
    )
    if setting is None:
        raise ValueError("Set the workflow batch size and step timings for this product first")
    unit = setting.unit
    org = db.query(Organisation).filter(Organisation.id == org_id).one()  # nosemgrep: filter-by-missing-org-id
    site = resolve_planning_site(db, org, (data or {}).get("site_id"))

    supplies, _ = on_hand(db, org_id, output_id, unit, site, None, today=today)
    in_stock = sum((s.quantity for s in supplies), Decimal(0))
    if in_stock >= quantity:
        return {
            "ready_date": today.isoformat(),
            "from": "stock",
            "unit": unit,
            "in_stock": float(in_stock),
            "reason": f"In stock now: {in_stock.normalize():f} {unit} on hand",
        }

    snapshot = setting.snapshot or {}
    readiness = list(snapshot.get("readiness_reasons") or [])
    if readiness or not snapshot.get("elapsed_seconds"):
        return {
            "ready_date": None,
            "from": "unknown",
            "unit": unit,
            "in_stock": float(in_stock),
            "reason": readiness[0] if readiness else "This product's step timings aren't set yet",
        }
    elapsed = timedelta(seconds=int(snapshot["elapsed_seconds"]))
    shortfall = quantity - in_stock
    batch_size = setting.batch_quantity
    batches = int((shortfall / batch_size).to_integral_value(rounding="ROUND_CEILING")) if batch_size else 1
    from app.features.planning.material_adapter import MAX_BATCHES

    if batches > MAX_BATCHES:
        return {
            "ready_date": None,
            "from": "too_large",
            "unit": unit,
            "in_stock": float(in_stock),
            "batches": batches,
            "reason": f"That's {batches} batches, more than can be promised at once: plan it instead",
        }
    capacity = placement.site_capacity(db, org_id, site.id if site else None)
    # Place every batch the order needs, one after another, on what the site already has
    # booked: the promise is when the *last* one is ready (!681 review).
    first_start, last_start, problem = None, None, None
    for _ in range(max(1, batches)):
        if capacity is None:
            start, note = today, None
        else:
            start, note = placement.place(capacity, snapshot, today, today=today)
            if start is None:
                return {
                    "ready_date": None,
                    "from": "capacity",
                    "unit": unit,
                    "in_stock": float(in_stock),
                    "reason": note or "No capacity found",
                }
            placement.add(capacity, snapshot, start)
        problem = problem or note
        first_start = start if first_start is None else min(first_start, start)
        last_start = start if last_start is None else max(last_start, start)
    start = first_start
    # Day-level dates round a part day up, as the planner does.
    ready = last_start + timedelta(days=-(-int(elapsed.total_seconds()) // 86400))
    held = f"{in_stock.normalize():f} {unit} in stock, " if in_stock else ""
    capacity_note = f" ({problem.lower()})" if problem else ""
    return {
        "ready_date": ready.isoformat(),
        "from": "plan",
        "unit": unit,
        "in_stock": float(in_stock),
        "batches": batches,
        "start_date": start.isoformat(),
        "reason": (
            f"Can be ready {_fmt(ready)}: {held}{batches} batch{'es' if batches != 1 else ''} starting "
            f"{_fmt(start)}{capacity_note}. Materials are checked when you plan it; the board moves the date if one is short."
        ),
    }
