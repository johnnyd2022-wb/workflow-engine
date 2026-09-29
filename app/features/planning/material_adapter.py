"""Exact-lot raw recipes and observational material assessments.

HTTP clients choose bindings, never availability or title. Physical on-hand is not
uncommitted supply: the production availability boundary remains unresolved until
an authoritative commitments/holds/readiness adapter exists.
"""

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import func

from app.core.db.models.inventory_item import InventoryItem
from app.core.db.models.process import Process
from app.core.db.models.process_version import ProcessVersion
from app.core.db.models.step import Step
from app.core.utils.time import utc_now
from app.features.planning import batch_service as service
from app.features.planning.batch_models import PlanningBatch
from app.features.planning.engine import PlannedBatch, StockKey, Supply
from app.features.planning.forecast_models import PlanningMaterialAssessment, PlanningMaterialBatchAssessment
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
    # No reservation/hold ledger exists. An empty query or another planning request
    # cannot establish that a lot is uncommitted. Never use extra_data as clearance.
    return LotAvailability()


def resolve_owner(item):
    """The new persisted owner column is the authority, never legacy JSON hints."""
    return hasattr(item, "contract_customer_id"), getattr(item, "contract_customer_id", None)


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


def _observe(db, org_id, lot_ids, today):
    lots = (
        db.query(InventoryItem)
        .filter(InventoryItem.org_id == org_id, InventoryItem.id.in_(lot_ids))
        .order_by(InventoryItem.id)
        .populate_existing()
        .all()
        if lot_ids
        else []
    )
    observations = {}
    supplies = {}
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
            supplies[str(item.id)] = MaterialSupply(
                str(org_id),
                Supply(
                    str(item.id),
                    StockKey("lot:" + str(item.id), item.unit, str(item.site_id) if item.site_id else None),
                    check.quantity,
                    check.ready_date,
                    item.expiry_date,
                ),
                MaterialSource.ON_HAND,
            )
    return observations, supplies


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
    for step, index, _, external in raw_inputs(steps):
        if external or (str(step.id), index) not in by_input:
            raise ValueError("Select an exact raw lot for each material input; intermediate supply is unresolved")
    if checked != bindings:
        raise ValueError("Frozen material binding changed; review and replan")
    return checked


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
    lot_ids = {service._id(entry["inventory_item_id"]) for bindings in definitions.values() for entry in bindings}
    if len(lot_ids) > 1000:
        raise service.PlanningConflictError("Review the material plan before assessing more than 1,000 lots")
    observations, supplies = _observe(db, org_id, lot_ids, today)
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
        bindings = definitions.get(batch.id)
        if bindings is None:
            continue
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
        if reasons:
            errors[batch.id] = "; ".join(dict.fromkeys(reasons))
            continue
        recipes.append(
            MaterialRecipe(
                str(org_id),
                str(batch.id),
                key,
                tuple(
                    MaterialRequirement(
                        StockKey("lot:" + entry["inventory_item_id"], entry["unit"], key.site_id),
                        Decimal(entry["quantity"]),
                    )
                    for entry in bindings
                ),
            )
        )
    result = assess_materials(
        tuple(engine_batches), tuple(recipes), tuple(supplies.values()), org_id=str(org_id), today=today
    )
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
    for order, (batch, assessed) in enumerate(zip(batches, result.batches, strict=True)):
        value = {
            "assessment_order": order,
            "batch_id": str(batch.id),
            "batch_revision": batch.revision,
            "process_version_id": batch.snapshot.get("process_version_id"),
            "workflow_fingerprint": batch.snapshot["workflow_fingerprint"],
            "bindings": definitions.get(batch.id, []),
            "material_status": assessed.status.value,
            "material_start_date": assessed.earliest_start_date.isoformat() if assessed.earliest_start_date else None,
            "material_timing_estimate": assessed.forecast_ready_date.isoformat()
            if assessed.forecast_ready_date and not batch.snapshot["readiness_reasons"]
            else None,
            "forecast_ready_date": None,
            "reasons": [errors[batch.id]] if batch.id in errors else list(assessed.reasons),
            "allocations": [
                {"lot_id": row.supply_id, "quantity": str(row.quantity), "unit": row.key.unit}
                for row in assessed.allocations
            ],
            "shortages": [
                {"lot_id": row.key.product_id.removeprefix("lot:"), "quantity": str(row.quantity), "unit": row.key.unit}
                for row in assessed.shortages_at_start
            ],
        }
        db.add(
            PlanningMaterialBatchAssessment(
                org_id=org_id, assessment_id=run.id, batch_id=batch.id, batch_revision=batch.revision, result=value
            )
        )
    db.flush()
    return run


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
