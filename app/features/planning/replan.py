"""Keep live plans right as things change (GL-P07 B4).

Run after a planner change (a batch moved, cancelled or re-prioritised, capacity saved, contract
demand synced) and whenever the board or Planner loads, which is when changes made elsewhere
(stock used or received, sales) are picked up. Idempotent: with nothing changed it changes
nothing. Under the org planning lock.

Only demand someone has already planned is re-planned, and only its unstarted batches:
1. **Size**: stock and other batches may now cover more or less of it. Batches it no longer needs
   are cancelled (latest first, never pinned ones); batches it now needs are added and placed.
2. **Passed dates**: an unstarted, unpinned batch whose start day has gone is moved to the
   first day that fits from today.
3. **Capacity**: while a resource group is over capacity on a day, the lowest-priority batch
   on it that may move (not pinned, not placed there by a person) makes the smallest move that
   fits: the nearest earlier day from today, else the nearest later day.
Every change is recorded with its reason, for the board's "What the planner changed".
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import ROUND_CEILING

from app.core.db.models.site import Site
from app.features.planning import placement
from app.features.planning.batch_models import PlanningBatch, PlanningReplanEvent, PlanningWorkflowSetting
from app.features.planning.engine import Demand, build_plan
from app.features.planning.models import PlanningDemand
from app.features.planning.stock import stock_key

UNSTARTED = ("blocked", "planned")
MAX_MOVES = 200


def _day(value: date) -> str:
    return f"{value.day} {value:%b}"


def _event(db, org_id, batch, kind, reason, trigger, before=None, after=None):
    row = PlanningReplanEvent(
        org_id=org_id,
        batch_id=batch.id,
        demand_id=batch.demand_id,
        kind=kind,
        from_date=before,
        to_date=after,
        reason=reason[:300],
        trigger=trigger[:40],
    )
    db.add(row)
    return row


def _move(batch, start: date, reason: str):
    elapsed = timedelta(days=int(batch.snapshot.get("elapsed_days") or 0))
    before = batch.proposed_start_date
    batch.proposed_start_date = start
    if batch.theoretical_ready_date is not None or not batch.snapshot.get("readiness_reasons"):
        batch.theoretical_ready_date = start + elapsed
    batch.forecast_ready_date = None
    batch.snapshot = {**batch.snapshot, "timing_reason": reason}
    batch.revision += 1
    return before


def _preferred(batch, today: date) -> date:
    """When the batch would start to be ready on its due day."""
    due = date.fromisoformat(batch.snapshot["due_date"])
    return max(today, due - timedelta(days=int(batch.snapshot.get("elapsed_days") or 0)))


def _site(db, org_id, site_id):
    if site_id is None:
        return None
    return db.query(Site).filter(Site.org_id == org_id, Site.id == site_id).one_or_none()


def _resize(db, org_id, demand, batches, *, today, trigger, events):
    from app.features.planning.batch_service import _netting_inputs, new_batches
    from app.features.planning.material_adapter import UNCHECKED, close_commitments

    setting = (
        db.query(PlanningWorkflowSetting)
        .filter(PlanningWorkflowSetting.org_id == org_id, PlanningWorkflowSetting.id == batches[0].setting_id)
        .one_or_none()
    )
    if setting is None:
        return
    site = _site(db, org_id, batches[0].site_id)
    unit = batches[0].unit
    if demand.source == "forecast":
        shortfall = demand.quantity
    else:
        demands, supplies, owner = _netting_inputs(db, org_id, demand, unit, site, today=today)
        key = stock_key(demand.source_output_id, unit, site, owner)
        # Stock on hand is shared out earliest-due first; each demand's own batches cover the
        # rest of it. Another demand's batches are that demand's, not spare supply.
        stock = [row for row in supplies if row.supply_id.startswith("lot:")]
        plan = build_plan(
            tuple(Demand(str(row.id), key, row.quantity, row.due_date, row.priority) for row in demands),
            tuple(stock),
            (),
            today=today,
        )
        shortfall = next(row.shortfall for row in plan.positions if row.demand_id == str(demand.id))
    started = sum((row.quantity for row in batches if row.status == "started"), 0)
    need = max(shortfall - started, 0)
    required = int((need / setting.batch_quantity).to_integral_value(rounding=ROUND_CEILING)) if need else 0
    unstarted = [row for row in batches if row.status in UNSTARTED]
    if len(unstarted) > required:
        movable = sorted(
            (row for row in unstarted if not row.pinned),
            key=lambda row: (row.proposed_start_date, row.batch_number),
            reverse=True,
        )
        for row in movable[: len(unstarted) - required]:
            row.status = "cancelled"
            row.revision += 1
            close_commitments(db, org_id, row.id, "released")
            events.append(
                _event(
                    db,
                    org_id,
                    row,
                    "cancelled",
                    "Stock on hand and other batches now cover it",
                    trigger,
                    row.proposed_start_date,
                )
            )
    elif len(unstarted) < required:
        from sqlalchemy import func

        template = max(batches, key=lambda row: (row.generation, row.batch_number))
        snapshot = {key: value for key, value in template.snapshot.items() if key != "placed_by"}
        # Numbered after every batch of this generation, cancelled ones included.
        last = (
            db.query(func.max(PlanningBatch.batch_number))
            .filter(
                PlanningBatch.org_id == org_id,
                PlanningBatch.demand_id == demand.id,
                PlanningBatch.generation == template.generation,
            )
            .scalar()
        )
        numbers = range(last + 1, last + 1 + required - len(unstarted))
        added = new_batches(
            db,
            org_id,
            demand,
            setting,
            template.process_id,
            site,
            unit,
            snapshot,
            [*snapshot.get("readiness_reasons", []), UNCHECKED],
            template.generation,
            numbers,
            _preferred(template, today),
            today=today,
        )
        for row in added:
            events.append(
                _event(
                    db,
                    org_id,
                    row,
                    "added",
                    "Less stock covers it than when it was planned",
                    trigger,
                    after=row.proposed_start_date,
                )
            )


def replan(db, org_id, *, today: date, trigger: str) -> list[PlanningReplanEvent]:
    from app.features.planning.batch_service import _lock_org

    _lock_org(db, org_id)
    events: list[PlanningReplanEvent] = []
    rows = (
        db.query(PlanningBatch, PlanningDemand)
        .join(
            PlanningDemand,
            (PlanningDemand.org_id == PlanningBatch.org_id) & (PlanningDemand.id == PlanningBatch.demand_id),
        )
        .filter(
            PlanningBatch.org_id == org_id,
            PlanningDemand.status == "open",
            PlanningBatch.status != "cancelled",
        )
        .order_by(
            PlanningDemand.due_date, PlanningDemand.priority.desc(), PlanningDemand.id, PlanningBatch.batch_number
        )
        .with_for_update(of=PlanningBatch)
        .populate_existing()
        .all()
    )
    by_demand: dict = {}
    for batch, demand in rows:
        by_demand.setdefault(demand.id, (demand, []))[1].append(batch)
    for demand, batches in by_demand.values():
        _resize(db, org_id, demand, batches, today=today, trigger=trigger, events=events)
    db.flush()

    live = (
        db.query(PlanningBatch)
        .join(
            PlanningDemand,
            (PlanningDemand.org_id == PlanningBatch.org_id) & (PlanningDemand.id == PlanningBatch.demand_id),
        )
        .filter(
            PlanningBatch.org_id == org_id,
            PlanningDemand.status == "open",
            PlanningBatch.status.in_(UNSTARTED),
        )
        .order_by(PlanningBatch.proposed_start_date, PlanningBatch.priority.desc(), PlanningBatch.id)
        .all()
    )
    for site_id in sorted({row.site_id for row in live}, key=str):
        here = [row for row in live if row.site_id == site_id]
        capacity = placement.site_capacity(db, org_id, site_id)
        # Passed dates first: a batch that didn't start on its day needs a day from today.
        for row in here:
            if row.pinned or row.proposed_start_date >= today:
                continue
            if capacity is not None:
                placement.remove(capacity, row.snapshot, row.proposed_start_date)
                start, _ = placement.place(capacity, row.snapshot, today, today=today)
                start = start or today
                placement.add(capacity, row.snapshot, start)
            else:
                start = today
            before = _move(row, start, f"Its start day ({_day(row.proposed_start_date)}) passed")
            events.append(
                _event(db, org_id, row, "moved", f"Its start day ({_day(before)}) passed", trigger, before, start)
            )
        if capacity is not None:
            _relieve(db, org_id, capacity, here, today=today, trigger=trigger, events=events)
    db.flush()
    return events


def _relieve(db, org_id, capacity, batches, *, today, trigger, events):
    for _ in range(MAX_MOVES):
        worst = None
        for row in batches:
            if row.status not in UNSTARTED:
                continue
            placement.remove(capacity, row.snapshot, row.proposed_start_date)
            problems = placement.overloads(capacity, row.snapshot, row.proposed_start_date, today=today)
            placement.add(capacity, row.snapshot, row.proposed_start_date)
            if problems and not row.pinned and row.snapshot.get("placed_by") != "person":
                rank = (row.priority, -date.fromisoformat(row.snapshot["due_date"]).toordinal(), str(row.id))
                if worst is None or rank < worst[0]:
                    worst = (rank, row, problems)
        if worst is None:
            return
        _, row, problems = worst
        placement.remove(capacity, row.snapshot, row.proposed_start_date)
        # The smallest move that fits: the nearest earlier day (never before today), else the
        # nearest later one.
        start, note = placement.place(capacity, row.snapshot, row.proposed_start_date, today=today)
        if start is None or start == row.proposed_start_date:
            placement.add(capacity, row.snapshot, row.proposed_start_date)
            batches = [other for other in batches if other.id != row.id]
            continue
        name, day, needed, limit = problems[0]
        reason = f"{name} was full on {_day(day)} ({needed} of {limit} minutes)"
        before = _move(row, start, reason + (f"; {note.lower()}" if note else ""))
        placement.add(capacity, row.snapshot, start)
        events.append(_event(db, org_id, row, "moved", reason, trigger, before, start))
