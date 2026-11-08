"""Atomic, idempotent start seam; unresolved planning checks stay closed."""

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import date
from importlib import import_module

from app.core.db.models.api_idempotency_key import ApiIdempotencyKey
from app.core.db.models.execution_step import ExecutionStep
from app.core.db.models.process import Process
from app.core.db.repositories.execution_repo import ExecutionRepository
from app.features.planning import batch_service as service
from app.features.planning.models import PlanningDemand


@dataclass(frozen=True)
class StartCheck:
    """Trusted server-side check result, recalculated immediately before starting."""

    blockers: tuple[str, ...]


def evaluate_start(db, org_id, batch) -> StartCheck:
    """What stops this batch starting now, recalculated from the records each time (B4).

    Persisted flags or HTTP payloads never grant clearance: materials are read from the batch's
    live commitments and the lots they hold, capacity from every other live batch at the site,
    and the site's compliance from the installed module. Each blocker is a plain sentence.
    """
    today = date.today()
    blockers = [
        *_material_blockers(db, org_id, batch, today),
        *_capacity_blockers(db, org_id, batch, today),
        *_compliance_blockers(db, org_id, batch, today),
    ]
    return StartCheck(tuple(dict.fromkeys(blockers)))


def _material_blockers(db, org_id, batch, today):
    from decimal import Decimal, InvalidOperation

    from app.core.db.models.inventory_item import InventoryItem
    from app.core.services.lot_holds import open_holds
    from app.core.utils.unit_conversion import convert_quantity_decimal
    from app.features.planning.forecast_models import (
        PlanningMaterialAssessment,
        PlanningMaterialBatchAssessment,
        PlanningMaterialCommitment,
    )
    from app.features.planning.material_adapter import SHORT, UNCHECKED, _pending_inputs, readable

    # The batch's latest material check is the evidence, never a flag on the batch.
    latest = (
        db.query(PlanningMaterialBatchAssessment)
        .join(
            PlanningMaterialAssessment,
            (PlanningMaterialAssessment.org_id == PlanningMaterialBatchAssessment.org_id)
            & (PlanningMaterialAssessment.id == PlanningMaterialBatchAssessment.assessment_id),
        )
        .filter(PlanningMaterialBatchAssessment.org_id == org_id, PlanningMaterialBatchAssessment.batch_id == batch.id)
        .order_by(PlanningMaterialAssessment.sequence.desc())
        .first()
    )
    if latest is None or UNCHECKED in (batch.blockers or []):
        return [UNCHECKED]
    if SHORT in (batch.blockers or []) or not (latest.result or {}).get("material_start_date"):
        return [SHORT]
    held = (
        db.query(PlanningMaterialCommitment)
        .filter(
            PlanningMaterialCommitment.org_id == org_id,
            PlanningMaterialCommitment.batch_id == batch.id,
            PlanningMaterialCommitment.status == "active",
        )
        .all()
    )
    if not held:
        # Only a recipe with no bought-in materials may hold nothing. Read the recipe itself:
        # a cleared flag on the batch is not evidence its materials were checked.
        from app.features.planning.material_adapter import raw_inputs

        steps = (
            db.query(service.Step)
            .filter(service.Step.org_id == org_id, service.Step.process_id == batch.process_id)
            .all()
        )
        try:
            needs = raw_inputs(steps)
        except ValueError:
            return ["The workflow's inputs need review before this batch can start"]
        return [UNCHECKED] if needs else []
    lots = {
        item.id: item
        for item in db.query(InventoryItem)
        .filter(InventoryItem.org_id == org_id, InventoryItem.id.in_({row.inventory_item_id for row in held}))
        .all()
    }
    holds = open_holds(db, org_id, lots.keys())
    pending = _pending_inputs(db, org_id, list(lots))
    claimed = _claimed_elsewhere(db, org_id, batch, lots)
    reasons = []
    needed = {}
    for row in held:
        needed.setdefault(row.inventory_item_id, []).append(row)
    for lot_id, rows in needed.items():
        lot = lots.get(lot_id)
        name = rows[0].material
        if lot is None:
            reasons.append(f"The {name} lot held for this batch is gone; check materials again")
            continue
        if lot_id in holds:
            reasons.append(f"The {name} lot is on quality hold: {holds[lot_id].reason}")
        if lot.expiry_date is not None and lot.expiry_date < today:
            reasons.append(f"The {name} lot went out of date on {lot.expiry_date.day} {lot.expiry_date:%b}")
        try:
            want = sum((convert_quantity_decimal(row.quantity, row.unit, lot.unit) for row in rows), Decimal(0))
            have = Decimal(lot.quantity)
            for used, used_unit in pending.get(str(lot_id), ()):
                have -= convert_quantity_decimal(Decimal(str(used)), used_unit, lot.unit)
            have -= claimed.get(lot_id, Decimal(0))
        except (TypeError, ValueError, InvalidOperation):
            reasons.append(f"The {name} lot's quantity can't be read; check materials again")
            continue
        if have < want:
            left, unit = readable(max(have, Decimal(0)), lot.unit)
            need, need_unit = readable(want, lot.unit)
            reasons.append(
                f"Only {left} {unit} of {name} is left on hand once other batches' share is counted; "
                f"this batch holds {need} {need_unit}. Check materials again"
                if lot_id in claimed
                else f"Only {left} {unit} of {name} is left on hand; this batch holds {need} {need_unit}"
            )
    return reasons


def _claimed_elsewhere(db, org_id, batch, lots):
    """What other batches still have a claim on each lot, in the lot's unit (B4 review): every
    other batch's active commitment, and the part of a started batch's consumed commitment its
    execution hasn't recorded using yet (recorded use on an unfinished step is already in
    pending inputs; on a finished step it has already left the lot's quantity)."""
    from decimal import Decimal, InvalidOperation

    from app.core.db.models.execution import Execution, ExecutionStatus
    from app.core.utils.unit_conversion import convert_quantity_decimal
    from app.features.planning.batch_models import PlanningBatch
    from app.features.planning.forecast_models import PlanningMaterialCommitment

    if not lots:
        return {}
    claimed = {}

    def add(lot_id, quantity, unit):
        try:
            amount = convert_quantity_decimal(Decimal(quantity), unit, lots[lot_id].unit)
        except (TypeError, ValueError, InvalidOperation):
            return
        if amount > 0:
            claimed[lot_id] = claimed.get(lot_id, Decimal(0)) + amount

    for row in (
        db.query(PlanningMaterialCommitment)
        .filter(
            PlanningMaterialCommitment.org_id == org_id,
            PlanningMaterialCommitment.inventory_item_id.in_(list(lots)),
            PlanningMaterialCommitment.status == "active",
            PlanningMaterialCommitment.batch_id != batch.id,
        )
        .all()
    ):
        add(row.inventory_item_id, row.quantity, row.unit)
    started = (
        db.query(PlanningMaterialCommitment, PlanningBatch.execution_id)
        .join(
            PlanningBatch,
            (PlanningBatch.org_id == PlanningMaterialCommitment.org_id)
            & (PlanningBatch.id == PlanningMaterialCommitment.batch_id),
        )
        .join(Execution, (Execution.org_id == PlanningBatch.org_id) & (Execution.id == PlanningBatch.execution_id))
        .filter(
            PlanningMaterialCommitment.org_id == org_id,
            PlanningMaterialCommitment.inventory_item_id.in_(list(lots)),
            PlanningMaterialCommitment.status == "consumed",
            PlanningBatch.status == "started",
            PlanningBatch.id != batch.id,
            Execution.status.in_((ExecutionStatus.PENDING, ExecutionStatus.IN_PROGRESS)),
        )
        .all()
    )
    if not started:
        return claimed
    recorded = {}
    for execution_id, inputs in (
        db.query(ExecutionStep.execution_id, ExecutionStep.actual_inputs)
        .filter(
            ExecutionStep.org_id == org_id,
            ExecutionStep.execution_id.in_({execution_id for _, execution_id in started}),
            ExecutionStep.actual_inputs.isnot(None),
        )
        .all()
    ):
        for entry in inputs if isinstance(inputs, list) else []:
            if not isinstance(entry, dict):
                continue
            key = (execution_id, str(entry.get("inventory_item_id")))
            recorded.setdefault(key, []).append((entry.get("quantity"), entry.get("unit")))
    for commitment, execution_id in started:
        lot = lots[commitment.inventory_item_id]
        try:
            outstanding = convert_quantity_decimal(commitment.quantity, commitment.unit, lot.unit)
            for quantity, unit in recorded.get((execution_id, str(lot.id)), ()):
                outstanding -= convert_quantity_decimal(Decimal(str(quantity)), unit, lot.unit)
        except (TypeError, ValueError, InvalidOperation):
            continue
        if outstanding > 0:
            add(lot.id, outstanding, lot.unit)
    return claimed


def _capacity_blockers(db, org_id, batch, today):
    from app.features.planning import placement

    capacity = placement.site_capacity(db, org_id, batch.site_id, exclude_ids=[batch.id])
    if capacity is None:
        return []
    return placement.describe(placement.overloads(capacity, batch.snapshot, batch.proposed_start_date, today=today))


def _compliance_blockers(db, org_id, batch, today):
    from app.core.db.models.site import Site
    from app.features.compliant.platform.production_checks import start_blockers

    query = db.query(Site).filter(Site.org_id == org_id)
    site = (
        query.filter(Site.id == batch.site_id).one_or_none()
        if batch.site_id
        else query.filter(Site.is_default.is_(True)).one_or_none()
    )
    return start_blockers(db, org_id, site, max(batch.proposed_start_date, today))


def _operational_site(db, org, planned_site_id):
    try:
        operations = import_module("app.core.db.site_operations")
    except ModuleNotFoundError as exc:
        if exc.name != "app.core.db.site_operations":
            raise
        operations = None
    if operations is not None:
        # Sites' resolver returns a UUID, and owns its internal release gate.
        resolved_id = operations.resolve_site(db, org.id, planned_site_id if org.multiple_sites_enabled else None)
        if org.multiple_sites_enabled:
            expected_id = resolved_id
        else:
            default = service.resolve_planning_site(db, org, None)
            expected_id = default.id if default else None
        if expected_id != planned_site_id:
            raise service.PlanningConflictError("The planned site is no longer available")
        return resolved_id, True
    default = service.resolve_planning_site(db, org, None)
    default_id = default.id if default else None
    if planned_site_id != default_id:
        raise service.PlanningConflictError("Operations at this site are not available yet")
    return default_id, False


def can_start_batch(db, org_id, row):
    if (
        row.status in ("cancelled", "started")
        or row.proposed_start_date > date.today()
        or row.snapshot.get("start_reasons", row.snapshot["readiness_reasons"])
    ):
        return False
    check = evaluate_start(db, org_id, row)
    if not isinstance(check, StartCheck) or check.blockers:
        return False
    demand = (
        db.query(PlanningDemand).filter(PlanningDemand.org_id == org_id, PlanningDemand.id == row.demand_id).first()
    )
    if demand is None or demand.status != "open":
        return False
    try:
        process, steps, output, unit, fingerprint = service._workflow(db, org_id, row.process_id, row.source_output_id)
        _validate_recipe(db, org_id, row, process, steps, output)
    except ValueError:
        return False
    if unit != row.unit or fingerprint != row.snapshot["workflow_fingerprint"]:
        return False
    org = db.query(service.Organisation).filter(service.Organisation.id == org_id).first()
    if org is None:
        return False
    try:
        _operational_site(db, org, row.site_id)
    except ValueError:
        return False
    return True


def _validate_recipe(db, org_id, row, process, steps, output):
    # Repository creates one native batch; no scaling multiplier is implemented.
    try:
        quantity = service._quantity(output.get("quantity") or output.get("quantity_produced"), row.unit)
    except ValueError as exc:
        raise service.PlanningConflictError("Workflow batch quantity needs review") from exc
    if quantity != row.quantity:
        raise service.PlanningConflictError("Planned quantity differs from the workflow batch size")
    version = service.latest_version(db, org_id, row.process_id)
    if (
        version is None
        or str(version.id) != row.snapshot.get("process_version_id")
        or version.version_number != row.snapshot.get("process_version_number")
        or service.version_fingerprint(version.snapshot) != row.snapshot.get("process_version_fingerprint")
        or service.version_fingerprint(version.snapshot)
        != service.version_fingerprint(service._process_snapshot(process, steps))
    ):
        raise service.PlanningConflictError("Workflow version changed; review and replan this batch")


def start_batch(db, org_id, batch_id, data, key):
    service._body(data, ("expected_revision",))
    if set(data) != {"expected_revision"}:
        raise ValueError("A batch revision is required")
    revision = service._integer(data["expected_revision"], minimum=1, maximum=2_147_483_647)
    if not isinstance(key, str) or re.fullmatch(r"[A-Za-z0-9_.:-]{8,110}", key) is None:
        raise ValueError("Send an Idempotency-Key of 8 to 110 letters, numbers or separators")
    org = service._lock_org(db, org_id)
    row = service._locked_batch(db, org_id, batch_id)
    if row is None:
        return None, False
    request_hash = hashlib.sha256(
        json.dumps({"batch_id": str(batch_id), "expected_revision": revision}, sort_keys=True).encode()
    ).hexdigest()
    stored_key = "planning-start:" + key
    replay = (
        db.query(ApiIdempotencyKey)
        .filter(ApiIdempotencyKey.org_id == org_id, ApiIdempotencyKey.key == stored_key)
        .first()
    )
    if replay is not None:
        if replay.payload_hash != request_hash:
            raise service.PlanningConflictError("This retry key was used for a different start request")
        return json.loads(replay.response_json), False
    changed = False
    if row.status != "started":
        if row.proposed_start_date > date.today():
            raise service.PlanningConflictError("Move the proposed start to today before starting early")
        if row.status == "cancelled" or row.revision != revision:
            raise service.PlanningConflictError("This batch changed; reload before starting")
        demand = (
            db.query(PlanningDemand).filter(PlanningDemand.org_id == org_id, PlanningDemand.id == row.demand_id).first()
        )
        if demand is None or demand.status != "open":
            raise service.PlanningConflictError("This demand is no longer open")
        # FOR UPDATE also blocks new steps/versions taking FK key-share locks.
        process = (
            db.query(Process)
            .filter(Process.org_id == org_id, Process.id == row.process_id)
            .with_for_update()
            .populate_existing()
            .first()
        )
        if process is None:
            raise service.PlanningConflictError("Workflow is no longer available")
        _, steps, output, unit, fingerprint = service._workflow(db, org_id, row.process_id, row.source_output_id)
        # Existing step edits cannot cross the snapshot/start boundary.
        db.query(service.Step).filter(
            service.Step.org_id == org_id, service.Step.process_id == row.process_id
        ).with_for_update(read=True).all()
        _, _, _, _, locked_fingerprint = service._workflow(db, org_id, row.process_id, row.source_output_id)
        if fingerprint != locked_fingerprint or fingerprint != row.snapshot["workflow_fingerprint"] or unit != row.unit:
            raise service.PlanningConflictError("Workflow changed; review and replan this batch")
        _validate_recipe(db, org_id, row, process, steps, output)
        if row.snapshot.get("start_reasons", row.snapshot["readiness_reasons"]):
            raise service.PlanningConflictError("Output ready-date settings need review")
        check = evaluate_start(db, org_id, row)
        if not isinstance(check, StartCheck) or check.blockers:
            reasons = check.blockers if isinstance(check, StartCheck) else ("Planning checks are unavailable",)
            raise service.PlanningConflictError("; ".join(reasons))
        site_id, explicit_site = _operational_site(db, org, row.site_id)
        if explicit_site:
            execution = ExecutionRepository(db).create_execution(org_id, row.process_id, commit=False, site_id=site_id)
        else:
            # Foundation operations are limited to the validated default site.
            execution = ExecutionRepository(db).create_execution(org_id, row.process_id, commit=False)
        if execution is None or execution.org_id != org_id or execution.site_id != row.site_id:
            raise service.PlanningConflictError("Execution did not retain the planned site")
        if str(getattr(execution, "process_version_id", None)) != row.snapshot["process_version_id"]:
            raise service.PlanningConflictError("Execution did not retain the planned workflow version")
        actual_steps = {
            item.step_id
            for item in db.query(ExecutionStep)
            .filter(ExecutionStep.org_id == org_id, ExecutionStep.execution_id == execution.id)
            .all()
        }
        if actual_steps != {step.id for step in steps}:
            raise service.PlanningConflictError("Workflow steps changed; review and replan this batch")
        row.execution_id = execution.id
        row.status = "started"
        # What planning held for it now belongs to the batch being made.
        from app.features.planning.material_adapter import close_commitments

        close_commitments(db, org_id, row.id, "consumed")
        row.blockers = row.snapshot["readiness_reasons"]
        row.revision += 1
        changed = True
        db.flush()
    result = service.batch_dict(row)
    db.add(
        ApiIdempotencyKey(
            org_id=org_id,
            key=stored_key,
            payload_hash=request_hash,
            response_json=json.dumps(result),
            http_status=201 if changed else 200,
        )
    )
    db.flush()
    return result, changed
