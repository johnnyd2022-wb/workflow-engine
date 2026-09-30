"""Copy producer-selected execution milestones into an immutable portal update."""

from app.core.db.models.execution_step import ExecutionStep, ExecutionStepStatus
from app.core.db.models.step import Step
from app.features.contract_manufacturing.services.orders import OrderError, identifier, text_value

MAX_SHARED_STEPS = 100


def step_candidates(db, org_id, order):
    """Return only steps belonging to batches currently linked to this tenant's order."""
    batch_ids = {link.execution_id for line in order.lines for link in line.batches}
    if not batch_ids:
        return []
    rows = (
        db.query(ExecutionStep, Step)
        .join(Step, ExecutionStep.step_id == Step.id)
        .filter(
            ExecutionStep.org_id == org_id,
            Step.org_id == org_id,
            ExecutionStep.execution_id.in_(batch_ids),
        )
        .order_by(ExecutionStep.execution_id, ExecutionStep.step_number, ExecutionStep.id)
        .all()
    )
    return [
        {
            "execution_step_id": str(execution_step.id),
            "batch_id": str(execution_step.execution_id),
            "name": step.name,
            "status": execution_step.status.value,
        }
        for execution_step, step in rows
    ]


def derived_progress(db, org_id, order, shared_steps):
    """Validate explicit disclosure and freeze current statuses at publication time."""
    if not isinstance(shared_steps, list) or len(shared_steps) > MAX_SHARED_STEPS:
        raise OrderError(f"shared_steps must be a list of up to {MAX_SHARED_STEPS} steps")
    candidates = {row["execution_step_id"]: row for row in step_candidates(db, org_id, order)}
    selected = []
    seen = set()
    for item in shared_steps:
        if not isinstance(item, dict) or set(item) != {"execution_step_id", "label"}:
            raise OrderError("Each shared step needs an execution_step_id and label")
        step_id = str(identifier(item["execution_step_id"], "execution_step_id"))
        if step_id in seen:
            raise OrderError("A shared step can only be selected once")
        seen.add(step_id)
        row = candidates.get(step_id)
        if row is None:
            raise OrderError("Shared step is not linked to this order", 404)
        label = text_value(item["label"], "shared step label", 100)
        selected.append({"execution_step_id": step_id, "label": label})
    if not selected:
        return {
            "available": False,
            "stage_label": None,
            "step_label": None,
            "percent": None,
            "milestones": [],
            "selection": [],
        }
    milestones = [
        {
            "batch_id": candidates[item["execution_step_id"]]["batch_id"],
            "label": item["label"],
            "status": candidates[item["execution_step_id"]]["status"],
        }
        for item in selected
    ]
    completed = sum(row["status"] == ExecutionStepStatus.COMPLETED.value for row in milestones)
    statuses = {row["status"] for row in milestones}
    if ExecutionStepStatus.FAILED.value in statuses:
        stage = "Production needs attention"
    elif completed == len(milestones):
        stage = "Shared milestones complete"
    elif statuses & {ExecutionStepStatus.IN_PROGRESS.value, ExecutionStepStatus.COMPLETED.value}:
        stage = "In production"
    else:
        stage = "Shared milestones not started"
    active = next((row["label"] for row in milestones if row["status"] == ExecutionStepStatus.IN_PROGRESS.value), None)
    return {
        "available": True,
        "stage_label": stage,
        "step_label": active,
        "percent": format(completed * 100 / len(milestones), ".1f"),
        "milestones": milestones,
        "selection": selected,
    }
