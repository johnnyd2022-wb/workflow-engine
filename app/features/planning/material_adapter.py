"""Raw recipes, material assessments and the commitments they make (GL-P07 B2).

A raw workflow input is met from the business's own raw lots of that material, first-expiring
first, or from the exact lot an owner bound to it. Checking materials allocates every live
planned batch in start order and records each allocation as an active commitment: other
batches see the lot as committed, and using it elsewhere warns but isn't blocked. HTTP clients
choose bindings, never availability or title.
"""

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation

from sqlalchemy import func

from app.core.db.models.execution_step import ExecutionStep, ExecutionStepStatus
from app.core.db.models.inventory_item import InventoryItem
from app.core.db.models.process import Process
from app.core.db.models.process_version import ProcessVersion
from app.core.db.models.step import Step
from app.core.utils.time import utc_now
from app.core.utils.unit_conversion import are_units_compatible, convert_quantity_decimal, normalize_unit
from app.features.planning import batch_service as service
from app.features.planning.batch_models import PlanningBatch
from app.features.planning.engine import PlannedBatch, StockKey, Supply
from app.features.planning.forecast_models import (
    PlanningMaterialAssessment,
    PlanningMaterialBatchAssessment,
    PlanningMaterialCommitment,
)
from app.features.planning.materials import (
    MaterialRecipe,
    MaterialRequirement,
    MaterialSource,
    MaterialSupply,
    assess_materials,
)
from app.features.planning.models import PlanningDemand

MAX_BATCHES = 1000


@dataclass(frozen=True)
class LotAvailability:
    """Trusted current available balance and day-level readiness; None is unknown."""

    quantity: Decimal | None = None
    ready_date: date | None = None
    reasons: tuple[str, ...] = ("Stock commitments, holds and readiness have not been confirmed",)


def resolve_availability(db, org_id, item) -> LotAvailability:
    """A raw lot on hand is available to planning from today.
    Planning's own commitments are re-made by each assessment, which allocates every live batch
    together, so they aren't subtracted here; inputs recorded on an unfinished execution step
    are, by the caller, as are holds, transit and ownership."""
    return LotAvailability(quantity=item.quantity, ready_date=date.today(), reasons=())


def _pending_inputs(db, org_id, lot_ids):
    """Stock recorded as an input on an execution step that hasn't completed: it's spoken for,
    though it only leaves inventory when the step completes."""
    held = {}
    if not lot_ids:
        return held
    wanted = {str(identity) for identity in lot_ids}
    steps = (
        db.query(ExecutionStep.actual_inputs)
        .filter(
            ExecutionStep.org_id == org_id,
            ExecutionStep.actual_inputs.isnot(None),
            ExecutionStep.status.notin_(
                (ExecutionStepStatus.COMPLETED, ExecutionStepStatus.SKIPPED, ExecutionStepStatus.FAILED)
            ),
        )
        .all()
    )
    for (inputs,) in steps:
        for entry in inputs if isinstance(inputs, list) else []:
            if not isinstance(entry, dict) or str(entry.get("inventory_item_id")) not in wanted:
                continue
            try:
                quantity = Decimal(str(entry.get("quantity")))
            except (InvalidOperation, ValueError):
                quantity = None
            held.setdefault(str(entry["inventory_item_id"]), []).append((quantity, entry.get("unit")))
    return held


def material_name(name):
    """How a raw input finds its stock: the material's name, ignoring case and spacing."""
    return " ".join(str(name or "").split()).casefold()


def base_unit(unit):
    """One unit per kind of quantity, so lots held in kg meet an input written in g."""
    unit = normalize_unit(unit)
    for base in ("g", "ml"):
        if unit != base and are_units_compatible(unit, base):
            return base
    return unit


def resolve_owner(item):
    """The persisted owner column is the authority, never legacy JSON hints.

    A lot that still carries a legacy ``contract_customer_id`` hint in its JSON has unresolved
    ownership, the same rule the contract material services apply, so it is never cleared.
    """
    if not hasattr(item, "contract_customer_id") or "contract_customer_id" in (item.extra_data or {}):
        return False, None
    return True, item.contract_customer_id


def raw_inputs(steps):
    if any(not isinstance(step.outputs, list) or not isinstance(step.inputs, list) for step in steps):
        raise ValueError("Workflow input/output definitions need review")
    internal = {str(output.get("id")) for step in steps for output in step.outputs if isinstance(output, dict)}
    result = []
    for step in steps:
        for index, item in enumerate(step.inputs):
            if not isinstance(item, dict):
                raise ValueError("Workflow inputs need review")
            source = item.get("source_output_id")
            if source is not None and str(source) in internal:
                continue
            result.append((step, index, item, source is not None))
    return result


def parse_bindings(steps, data):
    if not isinstance(data, list) or len(data) > 500:
        raise ValueError("Enter at most 500 material lot bindings")
    inputs = {(str(step.id), index): (item, external) for step, index, item, external in raw_inputs(steps)}
    mapped = []
    identities = set()
    for entry in data:
        service._body(entry, ("step_id", "input_index", "inventory_item_id"))
        if set(entry) != {"step_id", "input_index", "inventory_item_id"}:
            raise ValueError("A material binding needs step, input and lot IDs")
        key = (str(service._id(entry["step_id"])), service._integer(entry["input_index"], maximum=499))
        if key in identities or key not in inputs or inputs[key][1]:
            raise ValueError("Bind each raw workflow input once; intermediate inputs need their own adapter")
        identities.add(key)
        item, _ = inputs[key]
        unit = item.get("unit")
        if not isinstance(unit, str) or not unit.strip() or len(unit) > 50:
            raise ValueError("Material input unit needs review")
        quantity = service._quantity(item.get("quantity"), unit)
        mapped.append(
            {
                "step_id": key[0],
                "input_index": key[1],
                "inventory_item_id": str(service._id(entry["inventory_item_id"])),
                "unit": unit,
                "quantity": str(quantity),
            }
        )
    return mapped


def validate_bindings(db, org_id, steps, data):
    mapped = parse_bindings(steps, data)
    lot_ids = {service._id(row["inventory_item_id"]) for row in mapped}
    lots = (
        {
            item.id: item
            for item in db.query(InventoryItem)
            .filter(InventoryItem.org_id == org_id, InventoryItem.id.in_(lot_ids))
            .all()
        }
        if lot_ids
        else {}
    )
    for entry in mapped:
        lot = lots.get(service._id(entry["inventory_item_id"]))
        if lot is None or lot.inventory_type != "raw_material" or lot.unit != entry["unit"]:
            raise ValueError("Choose a same-business raw lot with the exact input unit")
    return mapped


def lot_catalog(db, org_id):
    lots = (
        db.query(InventoryItem)
        .filter(InventoryItem.org_id == org_id, InventoryItem.inventory_type == "raw_material")
        .order_by(InventoryItem.name, InventoryItem.id)
        .limit(501)
        .all()
    )
    return [
        {
            "id": str(item.id),
            "name": item.name,
            "unit": item.unit,
            "site_id": str(item.site_id) if item.site_id else None,
        }
        for item in lots[:500]
    ], len(lots) > 500


def _material_lots(db, org_id, materials):
    """The business's raw lots of these materials that have stock."""
    if not materials:
        return []
    lots = (
        db.query(InventoryItem)
        .filter(
            InventoryItem.org_id == org_id,
            InventoryItem.inventory_type == "raw_material",
            InventoryItem.quantity > 0,
            func.lower(func.trim(InventoryItem.name)).in_({" ".join(name.split()) for name in materials}),
        )
        .order_by(InventoryItem.id)
        .limit(1001)
        .populate_existing()
        .all()
    )
    if len(lots) > 1000:
        raise service.PlanningConflictError("Review the material plan before assessing more than 1,000 lots")
    return [item for item in lots if material_name(item.name) in materials]


FREE_SUFFIX = ":free"
MAX_REASSESS = 5  # each pass only shrinks the set of bindings that hold stock


def _lot_id(supply_id):
    """The lot behind a supply. A bound lot's leftover is offered as `<lot id>:free`."""
    return service._id(str(supply_id).removesuffix(FREE_SUFFIX))


def _observe(db, org_id, lot_ids, today, materials=frozenset()):
    lots = (
        db.query(InventoryItem)
        .filter(InventoryItem.org_id == org_id, InventoryItem.id.in_(lot_ids))
        .order_by(InventoryItem.id)
        .populate_existing()
        .all()
        if lot_ids
        else []
    )
    # Every other lot of a bound or automatic material is offered to any input of that material,
    # first-expiring first; `_supplies` decides how a bound lot is split.
    lots += [item for item in _material_lots(db, org_id, materials) if item.id not in set(lot_ids)]
    pending = _pending_inputs(db, org_id, [item.id for item in lots])
    observations = {}
    pool = []
    for item in lots:
        reasons = []
        owner_known, owner = resolve_owner(item)
        if not owner_known:
            reasons.append("Material ownership has not been confirmed")
        elif owner is not None:
            reasons.append("This demand requires producer-owned materials")
        extra = item.extra_data
        if extra is not None and (not isinstance(extra, dict) or extra.get("contract_customer_id")):
            reasons.append("Material ownership needs review")
        if isinstance(extra, dict) and any(
            key in extra for key in ("in_transit", "quarantined", "on_hold", "reserved_quantity", "committed_quantity")
        ):
            reasons.append("Material holds and commitments need authoritative confirmation")
        if item.inventory_type != "raw_material" or any(
            (item.source_execution_id, item.source_execution_step_id, item.source_output_id)
        ):
            reasons.append("Production material readiness has not been confirmed")
        quantity = item.quantity
        if not isinstance(item.unit, str) or not item.unit.strip() or len(item.unit) > 50:
            reasons.append("Material unit needs review")
        if not isinstance(quantity, Decimal) or not quantity.is_finite() or quantity < 0:
            reasons.append("Material quantity needs review")
        check = resolve_availability(db, org_id, item)
        if not isinstance(check, LotAvailability):
            check = LotAvailability(reasons=("Material availability needs review",))
        if check.quantity is not None and str(item.id) in pending:
            remaining = check.quantity
            for quantity, unit in pending[str(item.id)]:
                try:
                    remaining -= convert_quantity_decimal(quantity, unit, item.unit)
                except (TypeError, ValueError, InvalidOperation):
                    reasons.append("An unfinished batch has recorded this lot in a unit that can't be read")
            check = LotAvailability(max(remaining, Decimal(0)), check.ready_date, check.reasons)
        reasons.extend(check.reasons)
        if check.quantity is None or check.ready_date is None:
            reasons.append("Material availability is unresolved")
        elif (
            not isinstance(check.quantity, Decimal)
            or not check.quantity.is_finite()
            or check.quantity < 0
            or not isinstance(quantity, Decimal)
            or not quantity.is_finite()
            or check.quantity > quantity
            or type(check.ready_date) is not date
        ):
            reasons.append("Material availability needs review")
        observations[str(item.id)] = {
            "id": str(item.id),
            "name": item.name,
            "unit": item.unit,
            "site_id": str(item.site_id) if item.site_id else None,
            "owner_known": owner_known,
            "owner_id": str(owner) if owner else None,
            "on_hand_quantity": str(quantity),
            "available_quantity": str(check.quantity) if not reasons else None,
            "ready_date": check.ready_date.isoformat() if not reasons else None,
            "expiry_date": item.expiry_date.isoformat() if item.expiry_date else None,
            "reasons": list(dict.fromkeys(reasons)),
        }
        if (
            item.expiry_date is not None
            and check.ready_date is not None
            and type(check.ready_date) is date
            and item.expiry_date < check.ready_date
        ):
            observations[str(item.id)]["reasons"].append("Material expires before it can be used")
            observations[str(item.id)]["available_quantity"] = None
            observations[str(item.id)]["ready_date"] = None
        if not observations[str(item.id)]["reasons"]:
            observations[str(item.id)]["material"] = material_name(item.name)
            pool.append((item, check))
    return observations, pool


def _supplies(org_id, pool, bound, materials, observations, bound_demand):
    """Offer each usable lot. A bound lot goes to its bindings first, up to what `bound_demand`
    asks of it; the rest joins the material's shared pool as `<lot id>:free`, so nothing is
    counted twice and nothing is withheld for a binding no batch can use."""
    supplies = {}
    for item, check in pool:
        site = str(item.site_id) if item.site_id else None
        free = check.quantity
        if str(item.id) in bound:
            asked = Decimal(0)
            for amount, unit in bound_demand.get(str(item.id), ()):
                try:
                    asked += convert_quantity_decimal(amount, unit, item.unit)
                except (TypeError, ValueError, InvalidOperation):
                    pass  # the binding is flagged for its unit in assess()
            held = min(free, asked)
            free -= held
            supplies[str(item.id)] = MaterialSupply(
                str(org_id),
                Supply(
                    str(item.id),
                    StockKey("lot:" + str(item.id), item.unit, site),
                    held,
                    check.ready_date,
                    item.expiry_date,
                ),
                MaterialSource.ON_HAND,
            )
        if free <= 0 or material_name(item.name) not in materials:
            continue
        try:
            unit = base_unit(item.unit)
            key = StockKey("material:" + material_name(item.name), unit, site)
            quantity = convert_quantity_decimal(free, item.unit, unit)
        except ValueError:
            reasons = observations[str(item.id)]["reasons"]
            if str(item.id) not in bound and "Material unit can't be converted" not in reasons:
                reasons.append("Material unit can't be converted")
            continue
        identity = str(item.id) + FREE_SUFFIX if str(item.id) in bound else str(item.id)
        supplies[identity] = MaterialSupply(
            str(org_id), Supply(identity, key, quantity, check.ready_date, item.expiry_date), MaterialSource.ON_HAND
        )
    return supplies


def _recipe(db, org_id, batch, cache, versions):
    process, steps, output, unit, fingerprint = service._workflow(
        db, org_id, batch.process_id, batch.source_output_id, cache=cache
    )
    version = versions.get(batch.process_id)
    if (
        version is None
        or str(version.id) != batch.snapshot.get("process_version_id")
        or service.version_fingerprint(version.snapshot) != batch.snapshot.get("process_version_fingerprint")
        or service.version_fingerprint(version.snapshot)
        != service.version_fingerprint(service._process_snapshot(process, steps))
    ):
        raise ValueError("Workflow version changed; review and replan before checking materials")
    if service._quantity(output.get("quantity") or output.get("quantity_produced"), unit) != batch.quantity:
        raise ValueError("Planned quantity differs from the workflow batch size")
    if fingerprint != batch.snapshot["workflow_fingerprint"] or unit != batch.unit:
        raise ValueError("Workflow changed; review and replan before checking materials")
    bindings = batch.snapshot.get("material_bindings", [])
    checked = parse_bindings(
        steps, [{key: entry[key] for key in ("step_id", "input_index", "inventory_item_id")} for entry in bindings]
    )
    by_input = {(entry["step_id"], entry["input_index"]): entry for entry in checked}
    auto = []
    for step, index, item, external in raw_inputs(steps):
        if external:
            raise ValueError("An input made by another workflow can't be planned yet: its supply is unresolved")
        if (str(step.id), index) in by_input:
            continue
        unit = item.get("unit")
        if not isinstance(unit, str) or not unit.strip() or len(unit) > 50 or not material_name(item.get("name")):
            raise ValueError("Material input needs a name and unit")
        auto.append(
            {
                "step_id": str(step.id),
                "input_index": index,
                "material": material_name(item.get("name")),
                "name": str(item.get("name")).strip(),
                "unit": unit,
                "quantity": str(service._quantity(item.get("quantity"), unit)),
            }
        )
    if checked != bindings:
        raise ValueError("Frozen material binding changed; review and replan")
    return checked, auto


def assess(db, org_id, data, *, today):
    service._body(data, ())
    service._lock_org(db, org_id)
    batches = (
        db.query(PlanningBatch)
        .join(
            PlanningDemand,
            (PlanningDemand.org_id == PlanningBatch.org_id) & (PlanningDemand.id == PlanningBatch.demand_id),
        )
        .filter(
            PlanningBatch.org_id == org_id,
            PlanningDemand.org_id == org_id,
            PlanningDemand.status == "open",
            PlanningBatch.status.notin_(("started", "cancelled")),
        )
        .order_by(
            PlanningBatch.proposed_start_date,
            PlanningBatch.priority.desc(),
            PlanningBatch.demand_id,
            PlanningBatch.batch_number,
        )
        .limit(MAX_BATCHES + 1)
        .all()
    )
    if len(batches) > MAX_BATCHES:
        raise service.PlanningConflictError("Review the plan before assessing more than 1,000 live batches")
    processes = db.query(Process).filter(Process.org_id == org_id).limit(5001).populate_existing().all()
    steps = (
        db.query(Step)
        .filter(Step.org_id == org_id)
        .order_by(Step.position, Step.id)
        .limit(20001)
        .populate_existing()
        .all()
    )
    if len(processes) > 5000 or len(steps) > 20000:
        raise service.PlanningConflictError("Workflow catalogue is too large for one material assessment")
    by_process, by_output = service._definition_cache(steps)
    cache = ({row.id: row for row in processes}, by_process, by_output)
    process_ids = {batch.process_id for batch in batches}
    versions = (
        {
            row.process_id: row
            for row in db.query(ProcessVersion)
            .filter(ProcessVersion.org_id == org_id, ProcessVersion.process_id.in_(process_ids))
            .distinct(ProcessVersion.process_id)
            .order_by(ProcessVersion.process_id, ProcessVersion.version_number.desc())
            .limit(MAX_BATCHES)
            .populate_existing()
            .all()
        }
        if process_ids
        else {}
    )
    definitions = {}
    errors = {}
    for batch in batches:
        try:
            definitions[batch.id] = _recipe(db, org_id, batch, cache, versions)
        except ValueError as exc:
            errors[batch.id] = str(exc)
    lot_ids = {service._id(entry["inventory_item_id"]) for bindings, _ in definitions.values() for entry in bindings}
    if len(lot_ids) > 1000:
        raise service.PlanningConflictError("Review the material plan before assessing more than 1,000 lots")
    materials = frozenset(entry["material"] for _, auto in definitions.values() for entry in auto)
    observations, pool = _observe(db, org_id, lot_ids, today, materials)
    bound = {str(identity) for identity in lot_ids}
    engine_batches, recipes = [], []
    for batch in batches:
        key = StockKey(str(batch.source_output_id), batch.unit, str(batch.site_id) if batch.site_id else None)
        # Engine recipe slot is this physical batch: different frozen generations
        # can bind different lots for the same workflow/output without ambiguity.
        engine_batches.append(
            PlannedBatch(
                str(batch.id),
                key,
                str(batch.id),
                1,
                batch.quantity,
                batch.proposed_start_date,
                batch.proposed_start_date + timedelta(days=batch.snapshot["elapsed_days"]),
                False,
                "",
            )
        )
        if batch.id not in definitions:
            continue
        bindings, auto = definitions[batch.id]
        reasons = [
            reason
            for entry in bindings
            for reason in observations.get(
                entry["inventory_item_id"], {"reasons": ["Material lot is no longer available"]}
            )["reasons"]
        ]
        for entry in bindings:
            fact = observations.get(entry["inventory_item_id"])
            if fact and fact["site_id"] != key.site_id:
                reasons.append("Material belongs to another site")
            if fact and fact["unit"] != entry["unit"]:
                reasons.append("Material unit changed; review the frozen binding")
        requirements = [
            MaterialRequirement(
                StockKey("lot:" + entry["inventory_item_id"], entry["unit"], key.site_id), Decimal(entry["quantity"])
            )
            for entry in bindings
        ]
        for entry in auto:
            unit = base_unit(entry["unit"])
            try:
                quantity = convert_quantity_decimal(Decimal(entry["quantity"]), entry["unit"], unit)
            except ValueError:
                reasons.append(f"{entry['name']} is in a unit that can't be converted")
                continue
            requirements.append(
                MaterialRequirement(StockKey("material:" + entry["material"], unit, key.site_id), quantity)
            )
        if reasons:
            errors[batch.id] = "; ".join(dict.fromkeys(reasons))
            continue
        recipes.append(MaterialRecipe(str(org_id), str(batch.id), key, tuple(requirements)))
    # A binding holds its lot only for a batch that can use it. Assess, drop the bindings of
    # batches that came out blocked, and assess again until that set stops changing, so a blocked
    # batch's share of a lot flows back to the shared pool (Breaker review of !611, round 2).
    holders = {str(b.id): bool(definitions[b.id][0]) for b in batches if b.id in definitions}
    usable = {recipe.workflow_id for recipe in recipes}  # the batches with no errors
    for _ in range(MAX_REASSESS):
        bound_demand = {}
        for batch in batches:
            if str(batch.id) in usable:
                for entry in definitions[batch.id][0]:
                    bound_demand.setdefault(entry["inventory_item_id"], []).append(
                        (Decimal(entry["quantity"]), entry["unit"])
                    )
        supplies = _supplies(org_id, pool, bound, materials, observations, bound_demand)
        result = assess_materials(
            tuple(engine_batches), tuple(recipes), tuple(supplies.values()), org_id=str(org_id), today=today
        )
        blocked = {
            row.workflow_id
            for row in result.batches
            if row.earliest_start_date is None and row.workflow_id in usable and holders.get(row.workflow_id)
        }
        if not blocked:
            break
        usable -= blocked
    sequence = (
        db.query(func.max(PlanningMaterialAssessment.sequence))
        .filter(PlanningMaterialAssessment.org_id == org_id)
        .scalar()
        or 0
    ) + 1
    run = PlanningMaterialAssessment(
        org_id=org_id, sequence=sequence, observed_at=utc_now(), observations=list(observations.values())
    )
    db.add(run)
    db.flush()
    # The allocated lots, read once: for each allocation's own unit, and for its commitment.
    allocated = {
        item.id: item
        for item in db.query(InventoryItem).filter(
            InventoryItem.org_id == org_id,
            InventoryItem.id.in_({_lot_id(row.supply_id) for batch in result.batches for row in batch.allocations}),
        )
    }
    lot_units = {identity: item.unit for identity, item in allocated.items()}
    names = {entry["material"]: entry["name"] for _, auto in definitions.values() for entry in auto}

    def in_lot_unit(row):
        unit = lot_units.get(_lot_id(row.supply_id), row.key.unit)
        return format(convert_quantity_decimal(row.quantity, row.key.unit, unit).normalize(), "f"), unit

    for order, (batch, assessed) in enumerate(zip(batches, result.batches, strict=True)):
        value = {
            "assessment_order": order,
            "batch_id": str(batch.id),
            "batch_revision": batch.revision,
            "process_version_id": batch.snapshot.get("process_version_id"),
            "workflow_fingerprint": batch.snapshot["workflow_fingerprint"],
            "bindings": definitions.get(batch.id, ([], []))[0],
            "materials": definitions.get(batch.id, ([], []))[1],
            "material_status": assessed.status.value,
            "material_start_date": assessed.earliest_start_date.isoformat() if assessed.earliest_start_date else None,
            "material_timing_estimate": assessed.forecast_ready_date.isoformat()
            if assessed.forecast_ready_date and not batch.snapshot["readiness_reasons"]
            else None,
            "forecast_ready_date": None,
            # The shortages say what's short in words; the engine's own line for it is dropped.
            "reasons": [errors[batch.id]]
            if batch.id in errors
            else [
                "There isn't enough in stock for this batch yet"
                if reason == "No common start date is covered by the explicit material supply"
                else reason
                for reason in assessed.reasons
                if " is short by " not in reason
            ],
            "allocations": [
                {
                    "lot_id": str(_lot_id(row.supply_id)),
                    "quantity": str(row.quantity),
                    "unit": row.key.unit,
                    "lot_quantity": in_lot_unit(row)[0],
                    "lot_unit": in_lot_unit(row)[1],
                }
                for row in assessed.allocations
            ],
            "shortages": [
                {
                    **(
                        {
                            "material": names.get(
                                row.key.product_id.removeprefix("material:"),
                                row.key.product_id.removeprefix("material:"),
                            )
                        }
                        if row.key.product_id.startswith("material:")
                        else {"lot_id": row.key.product_id.removeprefix("lot:")}
                    ),
                    "quantity": str(row.quantity),
                    "unit": row.key.unit,
                }
                for row in assessed.shortages_at_start
            ],
        }
        db.add(
            PlanningMaterialBatchAssessment(
                org_id=org_id, assessment_id=run.id, batch_id=batch.id, batch_revision=batch.revision, result=value
            )
        )
    _commit(db, org_id, run, batches, result.batches, allocated)
    _material_blockers(batches, result.batches, errors)
    db.flush()
    return run


def _commit(db, org_id, run, batches, assessed, lots):
    """This assessment's allocations become the live batches' commitments. What each batch held
    before is released: every live batch was re-allocated together, so nothing is double-held.
    A batch that can't get all its materials commits nothing."""
    now = utc_now()
    (
        db.query(PlanningMaterialCommitment)
        .filter(
            PlanningMaterialCommitment.org_id == org_id,
            PlanningMaterialCommitment.batch_id.in_([batch.id for batch in batches]),
            PlanningMaterialCommitment.status == "active",
        )
        .update({"status": "released", "closed_at": now}, synchronize_session=False)
    )
    for batch, result in zip(batches, assessed, strict=True):
        if result.earliest_start_date is None:
            continue
        for row in result.allocations:
            lot = lots[_lot_id(row.supply_id)]
            # Held in the lot's own unit, which is how its stock is counted.
            quantity = convert_quantity_decimal(row.quantity, row.key.unit, lot.unit)
            if quantity <= 0:
                continue
            db.add(
                PlanningMaterialCommitment(
                    org_id=org_id,
                    batch_id=batch.id,
                    inventory_item_id=lot.id,
                    assessment_id=run.id,
                    material=lot.name,
                    quantity=quantity,
                    unit=lot.unit,
                    created_at=now,
                )
            )


UNCHECKED = "Materials have not been checked"
SHORT = "Not enough materials to start"


def _material_blockers(batches, assessed, errors):
    """A batch's checks list says what the latest check found: nothing for materials when they
    are held for it, that they're short when they aren't. The start check stays closed (B4)."""
    for batch, result in zip(batches, assessed, strict=True):
        rest = [reason for reason in batch.blockers if reason not in (UNCHECKED, SHORT)]
        held = batch.id not in errors and result.earliest_start_date is not None
        batch.blockers = rest if held else [SHORT, *rest]


def close_commitments(db, org_id, batch_id, status):
    """A batch's held materials: `consumed` when it starts, `released` when it is cancelled."""
    return (
        db.query(PlanningMaterialCommitment)
        .filter(
            PlanningMaterialCommitment.org_id == org_id,
            PlanningMaterialCommitment.batch_id == batch_id,
            PlanningMaterialCommitment.status == "active",
        )
        .update({"status": status, "closed_at": utc_now()}, synchronize_session=False)
    )


def commitments_for_items(db, org_id, item_ids):
    """What planning holds on these lots, with the batch each is held for, soonest start first."""
    if not item_ids:
        return {}
    rows = (
        db.query(PlanningMaterialCommitment, PlanningBatch)
        .join(
            PlanningBatch,
            (PlanningBatch.org_id == PlanningMaterialCommitment.org_id)
            & (PlanningBatch.id == PlanningMaterialCommitment.batch_id),
        )
        .filter(
            PlanningMaterialCommitment.org_id == org_id,
            PlanningBatch.org_id == org_id,
            PlanningMaterialCommitment.status == "active",
            PlanningMaterialCommitment.inventory_item_id.in_(list(item_ids)),
        )
        .order_by(PlanningBatch.proposed_start_date, PlanningBatch.batch_number)
        .all()
    )
    held = {}
    for commitment, batch in rows:
        held.setdefault(str(commitment.inventory_item_id), []).append(
            {
                "batch_id": str(batch.id),
                "batch": batch.snapshot.get("demand_reference", "Planned batch") + f" · batch {batch.batch_number}",
                "starts": batch.proposed_start_date.isoformat(),
                "quantity": format(commitment.quantity.normalize(), "f"),
                "unit": commitment.unit,
            }
        )
    return held


def latest(db, org_id, *, assessment_id=None):
    query = db.query(PlanningMaterialAssessment).filter(PlanningMaterialAssessment.org_id == org_id)
    run = (
        query.filter(PlanningMaterialAssessment.id == assessment_id).first()
        if assessment_id is not None
        else query.order_by(PlanningMaterialAssessment.sequence.desc()).first()
    )
    if run is None:
        return None
    rows = (
        db.query(PlanningMaterialBatchAssessment, PlanningBatch)
        .join(
            PlanningBatch,
            (PlanningBatch.org_id == PlanningMaterialBatchAssessment.org_id)
            & (PlanningBatch.id == PlanningMaterialBatchAssessment.batch_id),
        )
        .filter(
            PlanningMaterialBatchAssessment.org_id == org_id,
            PlanningBatch.org_id == org_id,
            PlanningMaterialBatchAssessment.assessment_id == run.id,
        )
        .all()
    )
    process_ids = {batch.process_id for _, batch in rows}
    versions = (
        {
            row.process_id: str(row.id)
            for row in db.query(ProcessVersion)
            .filter(ProcessVersion.org_id == org_id, ProcessVersion.process_id.in_(process_ids))
            .distinct(ProcessVersion.process_id)
            .order_by(ProcessVersion.process_id, ProcessVersion.version_number.desc())
            .limit(MAX_BATCHES)
            .all()
        }
        if process_ids
        else {}
    )
    return {
        "id": str(run.id),
        "sequence": run.sequence,
        "observed_at": run.observed_at.isoformat(),
        "observations": run.observations,
        "batches": sorted(
            [
                {
                    **row.result,
                    "stale": row.batch_revision != batch.revision
                    or batch.status in ("started", "cancelled")
                    or versions.get(batch.process_id) != batch.snapshot.get("process_version_id"),
                }
                for row, batch in rows
            ],
            key=lambda value: value["assessment_order"],
        ),
    }
