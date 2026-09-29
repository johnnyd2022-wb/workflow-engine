"""Persist proposed production dates without inventing material or capacity clearance."""

import hashlib
import json
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from uuid import UUID

from sqlalchemy import func

from app.core.db.models.organisation import Organisation
from app.core.db.models.process import Process
from app.core.db.models.process_version import ProcessVersion
from app.core.db.models.site import Site
from app.core.db.models.step import Step
from app.core.db.repositories.process_repo import _process_snapshot
from app.core.domain.ready_date_rules import VALID_READY_DATE_UNITS, duration_to_timedelta
from app.core.utils.unit_conversion import is_count_unit
from app.features.planning.batch_models import PlanningBatch, PlanningWorkflowSetting
from app.features.planning.demand_service import MAX_QUANTITY
from app.features.planning.engine import BatchRule, Demand, StepTiming, StockKey, build_plan, workflow_duration
from app.features.planning.models import PlanningDemand

MAX_PLAN_BATCHES = 500
MAX_MINUTES = 525_600


class PlanningConflictError(ValueError):
    """A stale request or unresolved prerequisite cannot change this plan."""


def _body(data, allowed):
    if not isinstance(data, dict) or set(data) - set(allowed):
        raise ValueError("Unexpected planning fields")


def _id(value):
    try:
        return UUID(str(value))
    except (ValueError, TypeError, AttributeError) as exc:
        raise ValueError("Choose a valid record ID") from exc


def _integer(value, minimum=0, maximum=100):
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise ValueError(f"Enter a whole number from {minimum} to {maximum}")
    return value


def _quantity(value, unit):
    try:
        quantity = Decimal(str(value))
    except InvalidOperation as exc:
        raise ValueError("Enter a positive batch quantity") from exc
    if not quantity.is_finite() or not 0 < quantity <= MAX_QUANTITY or quantity.as_tuple().exponent < -4:
        raise ValueError("Batch quantity must be positive with at most four decimal places")
    if is_count_unit(unit) and quantity != quantity.to_integral_value():
        raise ValueError("Counted batch quantities must be whole numbers")
    return quantity


def _lock_org(db, org_id):
    org = db.query(Organisation).filter(Organisation.id == org_id).with_for_update().populate_existing().first()
    if org is None:
        raise ValueError("Business not found")
    return org


def resolve_planning_site(db, org, site_id):
    """Validate registered planning scope; this does not enable site operations."""
    query = db.query(Site).filter(Site.org_id == org.id)
    if site_id is not None:
        if not org.multiple_sites_enabled:
            raise ValueError("Switch on multiple sites before selecting a site")
        site = query.filter(Site.id == _id(site_id)).with_for_update(read=True).first()
        if site is None or not site.is_active:
            raise ValueError("Choose an active site belonging to this business")
    else:
        site = query.filter(Site.is_default.is_(True)).with_for_update(read=True).first()
        if (site is not None and not site.is_active) or (org.multiple_sites_enabled and site is None):
            raise ValueError("An active default site is required")
    return site


def _definition_cache(all_steps):
    by_process, by_output = {}, {}
    for step in all_steps:
        by_process.setdefault(step.process_id, []).append(step)
        if not isinstance(step.outputs, list):
            continue
        for output in step.outputs or []:
            if not isinstance(output, dict):
                continue
            try:
                identity = _id(output.get("id"))
            except ValueError:
                continue
            by_output.setdefault(identity, []).append((step, output))
    return by_process, by_output


def version_fingerprint(snapshot):
    """Canonicalise SQL numeric positions in the existing version contract."""
    data = json.loads(json.dumps(snapshot))
    if not isinstance(data, dict) or not isinstance(data.get("steps"), list):
        raise ValueError("Workflow version needs review")
    for step in data["steps"]:
        try:
            position = Decimal(str(step["position"]))
        except (InvalidOperation, KeyError, TypeError) as exc:
            raise ValueError("Workflow version needs review") from exc
        if not position.is_finite():
            raise ValueError("Workflow version needs review")
        rendered = format(position, "f")
        step["position"] = rendered.rstrip("0").rstrip(".") if "." in rendered else rendered
    return hashlib.sha256(json.dumps(data, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def latest_version(db, org_id, process_id):
    return (
        db.query(ProcessVersion)
        .filter(ProcessVersion.org_id == org_id, ProcessVersion.process_id == process_id)
        .order_by(ProcessVersion.version_number.desc())
        .populate_existing()
        .first()
    )


def _workflow(db, org_id, process_id, output_id, *, cache=None):
    if cache is None:
        process = (
            db.query(Process).filter(Process.org_id == org_id, Process.id == process_id).populate_existing().first()
        )
        all_steps = (
            db.query(Step).filter(Step.org_id == org_id).order_by(Step.position, Step.id).populate_existing().all()
        )
        by_process, by_output = _definition_cache(all_steps)
    else:
        processes, by_process, by_output = cache
        process = processes.get(process_id)
    if process is None or process.is_draft:
        raise ValueError("Choose an available workflow belonging to this business")
    steps = by_process.get(process_id, [])
    if not steps or len(steps) > 200:
        raise ValueError("Workflow must contain from 1 to 200 steps")
    # Stable output IDs must map to exactly one producer across this organisation.
    producers = by_output.get(output_id, [])
    if len(producers) != 1 or producers[0][0].process_id != process_id:
        raise ValueError("Output mapping is missing or ambiguous in this business")
    output = producers[0][1]
    unit = output.get("unit", "units")
    if unit is None:
        unit = "units"
    if not isinstance(unit, str) or not unit.strip() or len(unit.strip()) > 50:
        raise ValueError("Output unit is not valid for planning")
    definitions = [
        {
            "id": str(step.id),
            "name": step.name,
            "description": step.description,
            "step_number": step.step_number,
            "execution_prompts": step.execution_prompts,
            "position": format(Decimal(str(step.position)), "f").rstrip("0").rstrip(".")
            if "." in format(Decimal(str(step.position)), "f")
            else str(step.position),
            "inputs": step.inputs,
            "outputs": step.outputs,
        }
        for step in steps
    ]
    definition = {
        "steps": definitions,
        "process": {
            "name": process.name,
            "description": process.description,
            "category": process.category.value if process.category else None,
            "settings": process.settings,
        },
    }
    fingerprint = hashlib.sha256(json.dumps(definition, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return process, steps, output, unit.strip(), fingerprint


def _timing_snapshot(steps, data):
    if not isinstance(data, list) or len(data) != len(steps):
        raise ValueError("Enter duration and waiting time for every workflow step")
    timings = {}
    for item in data:
        _body(item, ("step_id", "duration_minutes", "waiting_minutes"))
        identity = _id(item.get("step_id"))
        if identity in timings:
            raise ValueError("Each step needs exactly one timing")
        timings[identity] = (
            _integer(item.get("duration_minutes"), maximum=MAX_MINUTES),
            _integer(item.get("waiting_minutes"), maximum=MAX_MINUTES),
        )
    if set(timings) != {step.id for step in steps}:
        raise ValueError("Timing steps must belong to the selected workflow")
    outputs = {}
    for step in steps:
        if not isinstance(step.inputs, list) or not isinstance(step.outputs, list):
            raise ValueError("Workflow input/output definitions need review")
        for output in step.outputs:
            if not isinstance(output, dict):
                raise ValueError("Workflow output definitions need review")
            identity = output.get("id")
            if identity is not None:
                identity = str(_id(identity))
                if identity in outputs:
                    raise ValueError("Workflow outputs need distinct identities")
                outputs[identity] = step.id
    snapshot = []
    reasons = []
    start_reasons = []
    engine_steps = []
    for step in steps:
        predecessors = set()
        for item in step.inputs:
            if not isinstance(item, dict):
                raise ValueError("Workflow input definitions need review")
            source = item.get("source_output_id")
            if source is not None:
                producer = outputs.get(str(_id(source)))
                if producer is not None:
                    predecessors.add(producer)
        readiness = timedelta()
        for output in step.outputs:
            extra = output.get("extra_data")
            if extra is None:
                extra = {}
            if not isinstance(extra, dict):
                reasons.append(f"Ready date for {step.name} needs review")
                start_reasons.append(reasons[-1])
                continue
            rule = extra.get("ready_date")
            if rule is None:
                rule = {}
            if not isinstance(rule, dict):
                reasons.append(f"Ready date for {step.name} needs review")
                start_reasons.append(reasons[-1])
                continue
            enabled = rule.get("enabled", False)
            if enabled is False:
                continue
            if enabled is not True:
                reasons.append(f"Ready date for {step.name} needs review")
                start_reasons.append(reasons[-1])
                continue
            if rule.get("mode") == "set_at_execution":
                reasons.append(f"Ready date for {step.name} is not known until production")
                continue
            value, unit = rule.get("duration_value"), rule.get("duration_unit")
            if (
                rule.get("mode") != "fixed_duration"
                or isinstance(value, bool)
                or not isinstance(value, int)
                or not 0 < value <= 36_500
                or not isinstance(unit, str)
                or unit not in VALID_READY_DATE_UNITS
            ):
                reasons.append(f"Ready date for {step.name} needs review")
                start_reasons.append(reasons[-1])
                continue
            readiness = max(readiness, duration_to_timedelta(value, unit))
        duration, waiting = timings[step.id]
        row = {
            "step_id": str(step.id),
            "name": step.name,
            "duration_minutes": duration,
            "waiting_minutes": waiting,
            "readiness_seconds": int(readiness.total_seconds()),
            "predecessors": sorted(str(identity) for identity in predecessors),
        }
        snapshot.append(row)
        engine_steps.append(
            StepTiming(
                str(step.id),
                timedelta(minutes=duration),
                timedelta(minutes=waiting) + readiness,
                tuple(row["predecessors"]),
            )
        )
    try:
        elapsed = workflow_duration(tuple(engine_steps))
    except OverflowError as exc:
        raise ValueError("Workflow waiting time exceeds the supported calendar") from exc
    return {
        "steps": snapshot,
        "elapsed_seconds": int(elapsed.total_seconds()),
        "readiness_reasons": list(dict.fromkeys(reasons)),
        "start_reasons": list(dict.fromkeys(start_reasons)),
    }


def setting_dict(row):
    return {
        "id": str(row.id),
        "process_id": str(row.process_id),
        "source_output_id": str(row.source_output_id),
        "batch_quantity": str(row.batch_quantity),
        "unit": row.unit,
        "revision": row.revision,
        "snapshot": row.snapshot,
    }


def save_setting(db, org_id, process_id, data):
    _body(data, ("source_output_id", "batch_quantity", "steps", "expected_revision"))
    _lock_org(db, org_id)
    output_id = _id(data.get("source_output_id"))
    process, steps, output, unit, fingerprint = _workflow(db, org_id, process_id, output_id)
    quantity = _quantity(data.get("batch_quantity"), unit)
    snapshot = _timing_snapshot(steps, data.get("steps"))
    snapshot.update({"process_name": process.name, "output_name": str(output.get("name") or "Unnamed output")})
    row = (
        db.query(PlanningWorkflowSetting)
        .filter(
            PlanningWorkflowSetting.org_id == org_id,
            PlanningWorkflowSetting.process_id == process_id,
            PlanningWorkflowSetting.source_output_id == output_id,
        )
        .with_for_update()
        .populate_existing()
        .first()
    )
    revision = _integer(data.get("expected_revision"), maximum=2_147_483_647)
    if revision != (row.revision if row is not None else 0):
        raise PlanningConflictError("Workflow planning settings changed; reload before saving")
    if row is None:
        row = PlanningWorkflowSetting(org_id=org_id, process_id=process_id, source_output_id=output_id, revision=1)
        db.add(row)
    else:
        row.revision += 1
    row.batch_quantity, row.unit = quantity, unit
    row.workflow_fingerprint, row.snapshot = fingerprint, snapshot
    db.flush()
    return row


def workflow_catalog(db, org_id):
    from app.features.planning.demand_service import output_catalog

    processes = {row.id: row for row in db.query(Process).filter(Process.org_id == org_id).all()}
    all_steps = db.query(Step).filter(Step.org_id == org_id).order_by(Step.position, Step.id).all()
    by_process, by_output = _definition_cache(all_steps)
    cache = (processes, by_process, by_output)
    settings = {
        (row.process_id, row.source_output_id): row
        for row in db.query(PlanningWorkflowSetting).filter(PlanningWorkflowSetting.org_id == org_id).all()
    }
    rows = []
    for output in output_catalog(db, org_id):
        process_id, output_id = _id(output["process_id"]), _id(output["id"])
        try:
            process, steps, _, _, fingerprint = _workflow(db, org_id, process_id, output_id, cache=cache)
        except ValueError:
            continue
        setting = settings.get((process_id, output_id))
        rows.append(
            {
                **output,
                "process_name": process.name,
                "steps": [{"step_id": str(step.id), "name": step.name} for step in steps],
                "setting": setting_dict(setting) if setting else None,
                "stale": bool(setting and setting.workflow_fingerprint != fingerprint),
            }
        )
    return rows


def plan_demand(db, org_id, demand_id, data, *, today):
    _body(data, ("site_id",))
    org = _lock_org(db, org_id)
    demand = (
        db.query(PlanningDemand)
        .filter(PlanningDemand.org_id == org_id, PlanningDemand.id == demand_id)
        .with_for_update()
        .populate_existing()
        .first()
    )
    if demand is None:
        return None, False
    if demand.status != "open":
        raise PlanningConflictError("Only open demand can be planned")
    site = resolve_planning_site(db, org, data.get("site_id"))
    existing = (
        db.query(PlanningBatch)
        .filter(
            PlanningBatch.org_id == org_id, PlanningBatch.demand_id == demand_id, PlanningBatch.status != "cancelled"
        )
        .order_by(PlanningBatch.generation, PlanningBatch.batch_number)
        .with_for_update()
        .all()
    )
    if existing:
        if any(row.site_id != (site.id if site else None) for row in existing):
            raise PlanningConflictError("Demand already has a plan at another site; review that plan first")
        return existing, False
    setting = (
        db.query(PlanningWorkflowSetting)
        .filter(
            PlanningWorkflowSetting.org_id == org_id,
            PlanningWorkflowSetting.source_output_id == demand.source_output_id,
        )
        .first()
    )
    if setting is None:
        raise PlanningConflictError("Set the workflow batch size and step timings before planning")
    process, steps, output, unit, fingerprint = _workflow(db, org_id, setting.process_id, demand.source_output_id)
    if setting.unit != unit or demand.unit != unit or setting.workflow_fingerprint != fingerprint:
        raise PlanningConflictError("Workflow or output units changed; review demand and planning settings")
    key = StockKey(str(demand.source_output_id), unit, str(site.id) if site else None)
    try:
        plan = build_plan(
            (Demand(str(demand.id), key, demand.quantity, demand.due_date, demand.priority),),
            (),
            (
                BatchRule(
                    key, str(process.id), setting.batch_quantity, timedelta(seconds=setting.snapshot["elapsed_seconds"])
                ),
            ),
            today=today,
        )
    except OverflowError as exc:
        raise ValueError("Workflow timing exceeds the supported calendar") from exc
    group = plan.batches[0]
    if group.batch_count > MAX_PLAN_BATCHES:
        raise ValueError(f"Plan at most {MAX_PLAN_BATCHES} batches at once; review the demand or batch size")
    generation = (
        db.query(func.max(PlanningBatch.generation))
        .filter(PlanningBatch.org_id == org_id, PlanningBatch.demand_id == demand_id)
        .scalar()
        or 0
    ) + 1
    blockers = [
        *setting.snapshot["readiness_reasons"],
        "Materials have not been checked",
        "Capacity has not been checked",
        "Site compliance has not been checked",
    ]
    version = latest_version(db, org_id, process.id)
    start_reasons = list(setting.snapshot["start_reasons"])
    version_digest = None
    if version is None:
        start_reasons.append("Workflow version needs review")
    else:
        try:
            version_digest = version_fingerprint(version.snapshot)
            if version_digest != version_fingerprint(_process_snapshot(process, steps)):
                start_reasons.append("Workflow version needs review")
        except ValueError:
            start_reasons.append("Workflow version needs review")
    try:
        if _quantity(output.get("quantity") or output.get("quantity_produced"), unit) != setting.batch_quantity:
            start_reasons.append("Planned quantity differs from the workflow batch size")
    except ValueError:
        start_reasons.append("Workflow batch quantity needs review")
    blockers.extend(reason for reason in start_reasons if reason not in blockers)
    snapshot = {
        **setting.snapshot,
        "start_reasons": start_reasons,
        "process_version_id": str(version.id) if version else None,
        "process_version_number": version.version_number if version else None,
        "process_version_fingerprint": version_digest,
        "setting_revision": setting.revision,
        "workflow_fingerprint": fingerprint,
        "demand_reference": demand.reference,
        "due_date": demand.due_date.isoformat(),
        "batch_quantity": str(setting.batch_quantity),
        "site_name": site.name if site else "Main site",
        "timing_reason": group.reason,
        "elapsed_days": (group.ready_date - group.start_date).days,
    }
    rows = []
    for number in range(1, group.batch_count + 1):
        row = PlanningBatch(
            org_id=org_id,
            demand_id=demand_id,
            process_id=process.id,
            setting_id=setting.id,
            site_id=site.id if site else None,
            source_output_id=demand.source_output_id,
            generation=generation,
            batch_number=number,
            quantity=setting.batch_quantity,
            unit=unit,
            priority=demand.priority,
            revision=1,
            status="blocked",
            proposed_start_date=group.start_date,
            theoretical_ready_date=None if setting.snapshot["readiness_reasons"] else group.ready_date,
            forecast_ready_date=None,
            snapshot=snapshot,
            blockers=blockers,
        )
        db.add(row)
        rows.append(row)
    db.flush()
    return rows, True


def batch_dict(row, *, can_start=False):
    return {
        "id": str(row.id),
        "demand_id": str(row.demand_id),
        "process_id": str(row.process_id),
        "site_id": str(row.site_id) if row.site_id else None,
        "source_output_id": str(row.source_output_id),
        "execution_id": str(row.execution_id) if row.execution_id else None,
        "generation": row.generation,
        "batch_number": row.batch_number,
        "quantity": str(row.quantity),
        "unit": row.unit,
        "priority": row.priority,
        "pinned": row.pinned,
        "status": row.status,
        "revision": row.revision,
        "proposed_start_date": row.proposed_start_date.isoformat(),
        "theoretical_ready_date": row.theoretical_ready_date.isoformat() if row.theoretical_ready_date else None,
        "forecast_ready_date": row.forecast_ready_date.isoformat() if row.forecast_ready_date else None,
        "snapshot": row.snapshot,
        "blockers": row.blockers,
        "can_start": can_start,
    }


def list_batches(db, org_id, start, end):
    if end < start or (end - start).days > 90:
        raise ValueError("Choose a board range of at most 91 days")
    rows = (
        db.query(PlanningBatch)
        .filter(
            PlanningBatch.org_id == org_id,
            PlanningBatch.proposed_start_date >= start,
            PlanningBatch.proposed_start_date <= end,
            PlanningBatch.status != "cancelled",
        )
        .order_by(
            PlanningBatch.proposed_start_date,
            PlanningBatch.priority.desc(),
            PlanningBatch.demand_id,
            PlanningBatch.generation,
            PlanningBatch.batch_number,
            PlanningBatch.id,
        )
        .limit(1001)
        .all()
    )
    from app.features.planning.start_service import can_start_batch

    return {
        "batches": [batch_dict(row, can_start=can_start_batch(db, org_id, row)) for row in rows[:1000]],
        "truncated": len(rows) > 1000,
    }


def _locked_batch(db, org_id, batch_id):
    return (
        db.query(PlanningBatch)
        .filter(PlanningBatch.org_id == org_id, PlanningBatch.id == batch_id)
        .with_for_update()
        .populate_existing()
        .first()
    )


def update_batch(db, org_id, batch_id, data, *, today):
    _body(data, ("action", "expected_revision", "priority", "pinned", "start_date"))
    _lock_org(db, org_id)
    row = _locked_batch(db, org_id, batch_id)
    if row is None:
        return None, False
    action = data.get("action")
    fields = {"priority": {"priority"}, "pin": {"pinned"}, "reschedule": {"start_date"}, "cancel": set()}
    if (
        not isinstance(action, str)
        or action not in fields
        or set(data) != {"action", "expected_revision"} | fields[action]
    ):
        raise ValueError("Choose a valid planning action and its fields")
    revision = _integer(data.get("expected_revision"), minimum=1, maximum=2_147_483_647)
    if action == "cancel" and row.status == "cancelled":
        return row, False
    if revision != row.revision:
        raise PlanningConflictError("This batch changed; reload before editing")
    if row.status in ("cancelled", "started"):
        raise PlanningConflictError("Started or cancelled batches cannot be edited")
    demand = (
        db.query(PlanningDemand).filter(PlanningDemand.org_id == org_id, PlanningDemand.id == row.demand_id).first()
    )
    if demand is None or demand.status != "open":
        raise PlanningConflictError("This demand is no longer open")
    if action == "priority":
        row.priority = _integer(data["priority"])
    elif action == "pin":
        if not isinstance(data["pinned"], bool):
            raise ValueError("Pin must be true or false")
        row.pinned = data["pinned"]
    elif action == "reschedule":
        if row.pinned:
            raise PlanningConflictError("Unpin the batch before moving it")
        try:
            start = date.fromisoformat(data["start_date"])
        except (ValueError, TypeError) as exc:
            raise ValueError("Choose an ISO start date") from exc
        if start < today:
            raise ValueError("Choose a start date from today onwards")
        try:
            ready = start + timedelta(days=row.snapshot["elapsed_days"])
        except OverflowError as exc:
            raise ValueError("Start date exceeds the supported calendar") from exc
        row.proposed_start_date = start
        row.theoretical_ready_date = None if row.snapshot["readiness_reasons"] else ready
        row.forecast_ready_date = None
        row.status = "blocked"
    elif action == "cancel":
        row.status = "cancelled"
    row.revision += 1
    db.flush()
    return row, True
