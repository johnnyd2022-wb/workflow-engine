"""Deterministic planning from trusted, tenant-scoped input snapshots.

This module does not reserve inventory or start executions. Adapters must resolve
product identities, compatible units, site and ownership before invoking it.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import ROUND_CEILING, Decimal


def _quantity(value: Decimal, *, positive: bool = False) -> None:
    if not isinstance(value, Decimal) or not value.is_finite() or value < 0 or (positive and value == 0):
        raise ValueError("Quantity must be a finite Decimal with a valid sign")


@dataclass(frozen=True)
class StockKey:
    """No substitution across products, sites, units or custodial owners."""

    product_id: str
    unit: str
    site_id: str | None = None
    owner_id: str | None = None


@dataclass(frozen=True)
class Demand:
    demand_id: str
    key: StockKey
    quantity: Decimal
    due_date: date
    priority: int = 0


@dataclass(frozen=True)
class Supply:
    """Available quantity AFTER other committed allocations have been deducted.

    A supply may represent a shelf lot or known WIP, but never both. Expiry is
    inclusive; the supplier is responsible for excluding quarantine and transit.
    """

    supply_id: str
    key: StockKey
    quantity: Decimal
    ready_date: date
    expiry_date: date | None = None


@dataclass(frozen=True)
class StepTiming:
    step_id: str
    duration: timedelta
    waiting: timedelta = timedelta()
    predecessors: tuple[str, ...] = ()


def workflow_duration(steps: tuple[StepTiming, ...]) -> timedelta:
    """Elapsed critical path, including waiting; parallel branches are not summed."""
    by_id = {step.step_id: step for step in steps}
    if len(by_id) != len(steps):
        raise ValueError("Duplicate step identity")
    for step in steps:
        if step.duration < timedelta() or step.waiting < timedelta():
            raise ValueError("Step durations cannot be negative")
        if any(parent not in by_id for parent in step.predecessors):
            raise ValueError("Unknown predecessor")
    completed: dict[str, timedelta] = {}
    pending = dict(by_id)
    while pending:
        ready = [step for step in pending.values() if all(parent in completed for parent in step.predecessors)]
        if not ready:
            raise ValueError("Workflow contains a cycle")
        for step in ready:
            start = max((completed[parent] for parent in step.predecessors), default=timedelta())
            completed[step.step_id] = start + step.duration + step.waiting
            del pending[step.step_id]
    return max(completed.values(), default=timedelta())


@dataclass(frozen=True)
class BatchRule:
    key: StockKey
    workflow_id: str
    batch_quantity: Decimal
    duration: timedelta


@dataclass(frozen=True)
class PlannedBatch:
    demand_id: str
    key: StockKey
    workflow_id: str
    batch_count: int
    quantity: Decimal
    start_date: date
    ready_date: date
    late: bool
    reason: str


@dataclass(frozen=True)
class DemandPosition:
    demand_id: str
    supplied_quantity: Decimal
    shortfall: Decimal
    planned_quantity: Decimal
    unplanned_quantity: Decimal


@dataclass(frozen=True)
class Plan:
    positions: tuple[DemandPosition, ...]
    batches: tuple[PlannedBatch, ...]


def build_plan(
    demands: tuple[Demand, ...], supplies: tuple[Supply, ...], rules: tuple[BatchRule, ...], *, today: date
) -> Plan:
    """Net demand in due-date order, consuming first-expiring eligible supply.

    Dates are day-granular. Duration rounds UP to a whole day. Backward planning
    stops at today and forecasts forward when the requested date is impossible.
    Capacity and material constraints are intentionally separate later stages.
    """
    if len({row.demand_id for row in demands}) != len(demands):
        raise ValueError("Duplicate demand identity")
    if len({row.supply_id for row in supplies}) != len(supplies):
        raise ValueError("Duplicate supply identity")
    by_key = {rule.key: rule for rule in rules}
    if len(by_key) != len(rules):
        raise ValueError("Ambiguous workflow rule for product")
    for rule in rules:
        _quantity(rule.batch_quantity, positive=True)
        if rule.duration < timedelta():
            raise ValueError("Workflow duration cannot be negative")
    for demand in demands:
        _quantity(demand.quantity, positive=True)
    for supply in supplies:
        _quantity(supply.quantity)
        if supply.expiry_date is not None and supply.expiry_date < supply.ready_date:
            raise ValueError("Supply expires before it is ready")

    # Mutable remaining balances are local: callers' input snapshots stay immutable.
    available = [(supply, supply.quantity) for supply in supplies]
    positions: list[DemandPosition] = []
    batches: list[PlannedBatch] = []
    for demand in sorted(demands, key=lambda row: (row.due_date, -row.priority, row.demand_id)):
        use_date = max(today, demand.due_date)
        needed = demand.quantity
        indices = sorted(
            range(len(available)),
            key=lambda index: (
                available[index][0].expiry_date or date.max,
                available[index][0].ready_date,
                available[index][0].supply_id,
            ),
        )
        for index in indices:
            supply, remaining = available[index]
            if supply.key != demand.key or supply.ready_date > use_date:
                continue
            if supply.expiry_date is not None and supply.expiry_date < use_date:
                continue
            used = min(needed, remaining)
            available[index] = (supply, remaining - used)
            needed -= used
            if needed == 0:
                break
        supplied = demand.quantity - needed
        rule = by_key.get(demand.key)
        planned = Decimal(0)
        if needed and rule is not None:
            count = int((needed / rule.batch_quantity).to_integral_value(rounding=ROUND_CEILING))
            planned = count * rule.batch_quantity
            # Exact integer timedelta arithmetic avoids float truncation.
            day = timedelta(days=1)
            duration_days = rule.duration // day + bool(rule.duration % day)
            elapsed = timedelta(days=duration_days)
            start = max(today, demand.due_date - elapsed)
            ready = start + elapsed
            late = ready > demand.due_date
            batches.append(
                PlannedBatch(
                    demand.demand_id,
                    demand.key,
                    rule.workflow_id,
                    count,
                    planned,
                    start,
                    ready,
                    late,
                    "Insufficient lead time; earliest start is today" if late else "Net demand exceeds eligible supply",
                )
            )
            # Only surplus is available to another order, and only after its ready date.
            surplus = planned - needed
            if surplus:
                available.append((Supply(f"planned:{demand.demand_id}", demand.key, surplus, ready), surplus))
        positions.append(
            DemandPosition(demand.demand_id, supplied, needed, planned, needed if rule is None else Decimal(0))
        )
    return Plan(tuple(positions), tuple(batches))
