"""Pure material availability checks on explicit tenant-scoped planning snapshots.

Each physical batch consumes its recipe inputs at its start date. Results are
forecasts, not stock reservations or permission to start an execution.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, localcontext
from enum import Enum

from app.features.planning.engine import PlannedBatch, StockKey, Supply, _quantity

MAX_BATCHES = 10_000


class MaterialSource(Enum):
    ON_HAND = "on_hand"
    INCOMING = "incoming"
    SCHEDULED_PRODUCTION = "scheduled_production"


@dataclass(frozen=True)
class MaterialSupply:
    org_id: str
    supply: Supply
    source: MaterialSource


@dataclass(frozen=True)
class MaterialRequirement:
    key: StockKey
    quantity: Decimal  # Required for ONE physical batch, in the key's unit.


@dataclass(frozen=True)
class MaterialRecipe:
    org_id: str
    workflow_id: str
    output_key: StockKey
    inputs: tuple[MaterialRequirement, ...]


@dataclass(frozen=True)
class MaterialAllocation:
    supply_id: str
    key: StockKey
    quantity: Decimal
    source: MaterialSource


@dataclass(frozen=True)
class MaterialShortage:
    key: StockKey
    quantity: Decimal
    reason: str


class MaterialStatus(Enum):
    ON_TIME = "on_time"
    DELAYED = "delayed"
    BLOCKED = "blocked"


@dataclass(frozen=True)
class MaterialBatchResult:
    demand_id: str
    workflow_id: str
    output_key: StockKey
    batch_number: int  # One-based within the original PlannedBatch group.
    planned_start_date: date
    checked_start_date: date
    earliest_start_date: date | None
    forecast_ready_date: date | None
    status: MaterialStatus
    allocations: tuple[MaterialAllocation, ...]
    shortages_at_start: tuple[MaterialShortage, ...]
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class MaterialBalance:
    supply: MaterialSupply
    quantity: Decimal


@dataclass(frozen=True)
class MaterialAssessment:
    org_id: str
    batches: tuple[MaterialBatchResult, ...]
    balances: tuple[MaterialBalance, ...]


def _identity(value: str) -> None:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise ValueError("Snapshot identities must be nonempty normalized strings")


def _key(key: StockKey) -> None:
    if not isinstance(key, StockKey):
        raise ValueError("Material identities must be StockKey values")
    _identity(key.product_id)
    _identity(key.unit)
    for value in (key.site_id, key.owner_id):
        if value is not None:
            _identity(value)


def _date(value: date) -> None:
    if not isinstance(value, date) or isinstance(value, datetime):
        raise ValueError("Material planning requires day-level dates")


def _validate(org_id, batches, recipes, supplies, today):
    _identity(org_id)
    _date(today)
    if len({row.demand_id for row in batches}) != len(batches):
        raise ValueError("Duplicate planned demand identity")
    if sum(row.batch_count for row in batches if isinstance(row.batch_count, int)) > MAX_BATCHES:
        raise ValueError("Too many physical batches for one material planning snapshot")
    for batch in batches:
        _identity(batch.demand_id)
        _identity(batch.workflow_id)
        _key(batch.key)
        _quantity(batch.quantity, positive=True)
        if isinstance(batch.batch_count, bool) or not isinstance(batch.batch_count, int) or batch.batch_count <= 0:
            raise ValueError("Batch counts must be positive whole numbers")
        _date(batch.start_date)
        _date(batch.ready_date)
        if batch.ready_date < batch.start_date:
            raise ValueError("A batch cannot finish before it starts")
    recipe_keys = set()
    for recipe in recipes:
        if recipe.org_id != org_id:
            raise ValueError("Recipe belongs to another organisation")
        _identity(recipe.workflow_id)
        _key(recipe.output_key)
        key = (recipe.workflow_id, recipe.output_key)
        if key in recipe_keys:
            raise ValueError("Ambiguous material recipe for workflow and output")
        recipe_keys.add(key)
        for requirement in recipe.inputs:
            _key(requirement.key)
            _quantity(requirement.quantity, positive=True)
    if len({row.supply.supply_id for row in supplies}) != len(supplies):
        raise ValueError("Duplicate material supply identity")
    for row in supplies:
        if row.org_id != org_id:
            raise ValueError("Supply belongs to another organisation")
        if not isinstance(row.source, MaterialSource):
            raise ValueError("Material supply must declare an explicit source type")
        supply = row.supply
        _identity(supply.supply_id)
        _key(supply.key)
        _quantity(supply.quantity)
        _date(supply.ready_date)
        if supply.expiry_date is not None:
            _date(supply.expiry_date)
            if supply.expiry_date < supply.ready_date:
                raise ValueError("Material supply expires before it is ready")


def _precision(recipes, supplies):
    quantities = [row.supply.quantity for row in supplies]
    quantities.extend(requirement.quantity for recipe in recipes for requirement in recipe.inputs)
    nonzero = [value for value in quantities if value]
    integer_places = max((max(0, value.adjusted() + 1) for value in nonzero), default=1)
    decimal_places = max((max(0, -value.as_tuple().exponent) for value in nonzero), default=0)
    # All operations are sums/subtractions/min; this covers the full input scale
    # and aggregation carry, independent of a caller's Decimal context precision.
    return max(28, integer_places + decimal_places + len(str(len(quantities) + 1)) + 2)


def _requirements(recipe):
    requirements: dict[StockKey, Decimal] = {}
    for row in recipe.inputs:
        requirements[row.key] = requirements.get(row.key, Decimal(0)) + row.quantity
    return requirements


def _trial(requirements, supplies, balances, start_date):
    trial = list(balances)
    allocations = []
    shortages = []
    indices = sorted(
        range(len(supplies)),
        key=lambda index: (
            supplies[index].supply.expiry_date or date.max,
            supplies[index].supply.ready_date,
            supplies[index].supply.supply_id,
        ),
    )
    for key, quantity in requirements.items():
        needed = quantity
        for index in indices:
            supply = supplies[index].supply
            if supply.key != key or supply.ready_date > start_date or not trial[index]:
                continue
            if supply.expiry_date is not None and supply.expiry_date < start_date:
                continue
            used = min(needed, trial[index])
            allocations.append(MaterialAllocation(supply.supply_id, key, used, supplies[index].source))
            trial[index] -= used
            needed -= used
            if not needed:
                break
        if needed:
            shortages.append(
                MaterialShortage(
                    key,
                    needed,
                    f"{key.product_id} is short by {needed} {key.unit} at {start_date.isoformat()}",
                )
            )
    return trial, tuple(allocations), tuple(shortages)


def assess_materials(
    batches: tuple[PlannedBatch, ...],
    recipes: tuple[MaterialRecipe, ...],
    supplies: tuple[MaterialSupply, ...],
    *,
    org_id: str,
    today: date,
) -> MaterialAssessment:
    """Find the earliest common material-ready start for each physical batch.

    Preserve caller batch order, including its demand priority. Readiness events
    are the only candidate future dates: a missing or infeasible replenishment
    never becomes a guessed date. FEFO applies at each trial date. An infeasible
    trial or blocked batch consumes nothing. Known incoming/scheduled production
    must be explicitly supplied by a trusted adapter after checking commitments,
    quarantine, transit, ownership and tenant access. No supply is inferred from
    these output batches, so there is no self-supply or dependency-cycle guess.
    """
    _validate(org_id, batches, recipes, supplies, today)
    with localcontext() as context:
        context.prec = _precision(recipes, supplies)
        by_recipe = {(row.workflow_id, row.output_key): row for row in recipes}
        balances = [row.supply.quantity for row in supplies]
        results = []
        for batch in batches:
            checked = max(today, batch.start_date)
            duration = batch.ready_date - batch.start_date
            recipe = by_recipe.get((batch.workflow_id, batch.key))
            requirements = _requirements(recipe) if recipe is not None else {}
            candidates = {checked}
            candidates.update(
                row.supply.ready_date
                for row in supplies
                if row.supply.key in requirements and row.supply.ready_date > checked
            )
            for number in range(1, batch.batch_count + 1):
                common = dict(
                    demand_id=batch.demand_id,
                    workflow_id=batch.workflow_id,
                    output_key=batch.key,
                    batch_number=number,
                    planned_start_date=batch.start_date,
                    checked_start_date=checked,
                )
                if recipe is None:
                    results.append(
                        MaterialBatchResult(
                            **common,
                            earliest_start_date=None,
                            forecast_ready_date=None,
                            status=MaterialStatus.BLOCKED,
                            allocations=(),
                            shortages_at_start=(),
                            reasons=(f"Material recipe is unknown for workflow {batch.workflow_id}",),
                        )
                    )
                    continue
                _, _, initial_shortages = _trial(requirements, supplies, balances, checked)
                reasons = [row.reason for row in initial_shortages]
                if checked > batch.start_date:
                    reasons.append("Requested start has passed; material eligibility is checked from today")
                feasible = None
                calendar_overflow = False
                for candidate in sorted(candidates):
                    trial, allocations, shortages = _trial(requirements, supplies, balances, candidate)
                    if shortages:
                        continue
                    try:
                        ready = candidate + duration
                    except OverflowError:
                        calendar_overflow = True
                        continue
                    feasible = (candidate, ready, trial, allocations)
                    break
                if feasible is None:
                    reasons.append(
                        "Material-ready date exceeds the supported calendar"
                        if calendar_overflow
                        else "No common start date is covered by the explicit material supply"
                    )
                    results.append(
                        MaterialBatchResult(
                            **common,
                            earliest_start_date=None,
                            forecast_ready_date=None,
                            status=MaterialStatus.BLOCKED,
                            allocations=(),
                            shortages_at_start=initial_shortages,
                            reasons=tuple(reasons),
                        )
                    )
                    continue
                start, ready, balances, allocations = feasible
                for allocation in allocations:
                    source = next(row for row in supplies if row.supply.supply_id == allocation.supply_id)
                    if source.supply.ready_date > checked:
                        reasons.append(
                            f"{allocation.key.product_id} uses {source.source.value} supply "
                            f"{allocation.supply_id}, ready {source.supply.ready_date.isoformat()}"
                        )
                results.append(
                    MaterialBatchResult(
                        **common,
                        earliest_start_date=start,
                        forecast_ready_date=ready,
                        status=MaterialStatus.DELAYED if start > batch.start_date else MaterialStatus.ON_TIME,
                        allocations=allocations,
                        shortages_at_start=initial_shortages,
                        reasons=tuple(reasons) or ("All material inputs are available at the planned start",),
                    )
                )
        return MaterialAssessment(
            org_id,
            tuple(results),
            tuple(MaterialBalance(row, balance) for row, balance in zip(supplies, balances, strict=True)),
        )
