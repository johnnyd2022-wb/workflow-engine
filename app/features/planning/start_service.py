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
    """Future adapters must inspect current stock, capacity and module constraints.

    Persisted flags or HTTP payloads cannot grant clearance. Until those adapters
    are integrated, even an empty database blockers list is not evidence to start.
    """
    return StartCheck(
        ("Materials have not been checked", "Capacity has not been checked", "Site compliance has not been checked")
    )


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
