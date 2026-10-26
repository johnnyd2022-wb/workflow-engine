"""Record a production step: one page from the Production overview's main button.

Recording used to start at the workflow list: pick a workflow, open its editor, find the
batch, then record. This page puts both everyday answers one tap away:

- **Carry on a batch**: every batch in flight, with the step it's waiting on and how long
  it has waited, each a link straight to that step's recording screen;
- **Start a new batch**: every workflow, most recently used first, each a link straight to
  the recording screen for its first step (the batch is created when that step is saved).
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from flask import Blueprint, g, jsonify, render_template
from sqlalchemy import func
from sqlalchemy.orm import selectinload

from app.core.db import db_session
from app.core.db.models.execution import Execution, ExecutionStatus
from app.core.db.models.execution_step import ExecutionStep, ExecutionStepStatus
from app.core.db.models.process import Process
from app.core.db.models.step import Step
from app.core.security.permissions import requires_auth

WAITING_SECONDS = 2 * 24 * 3600  # the Batches page's "waiting" threshold
# Far beyond a working floor's in-flight batches or product range; the oldest batches come first.
MAX_BATCHES = 500
MAX_WORKFLOWS = 200
_OPEN = (ExecutionStatus.PENDING, ExecutionStatus.IN_PROGRESS)
_CURRENT = (ExecutionStepStatus.READY, ExecutionStepStatus.IN_PROGRESS)

record_step_bp = Blueprint("record_step", __name__)


def _status(value) -> str:
    return getattr(value, "value", value) or ""


def _batch_label(steps: list[ExecutionStep]) -> str | None:
    """The batch code an operator typed on an output, as the Batches page shows it."""
    for step in steps:
        for out in step.actual_outputs or []:
            if isinstance(out, dict):
                for key in ("batch_id", "batchId", "lot_id", "lotId", "lot"):
                    if out.get(key):
                        return str(out[key]).strip() or None
    return None


def _operator(step: ExecutionStep | None) -> str | None:
    data = (step.execution_data if step is not None else None) or {}
    return (data.get("completed_by") or data.get("completed_by_email")) if isinstance(data, dict) else None


def record_options(session, org_id: UUID, now: datetime | None = None) -> dict:
    now = now or datetime.now(UTC)
    executions = (
        session.query(Execution)
        .options(selectinload(Execution.execution_steps).selectinload(ExecutionStep.step))
        .filter(Execution.org_id == org_id, Execution.status.in_(_OPEN))
        .order_by(Execution.started_at.asc())
        .limit(MAX_BATCHES)
        .all()
    )
    names = {p.id: p.name for p in session.query(Process.id, Process.name).filter(Process.org_id == org_id)}
    batches = []
    for ex in executions:
        # nosemgrep: orm-relationship-access-in-loop -- selectinload above loads every batch's steps at once
        steps = sorted(ex.execution_steps, key=lambda s: s.step_number or 0)
        current = next((s for s in steps if s.status in _CURRENT), None)
        if current is None:
            continue  # nothing to record (every step done or waiting on something else)
        done = [s for s in steps if s.status == ExecutionStepStatus.COMPLETED and s.completed_at]
        last = max(done, key=lambda s: s.completed_at) if done else None
        since = last.completed_at if last else (ex.started_at or ex.created_at)
        waited = max(0, int((now - since).total_seconds())) if since else 0
        label = _batch_label(steps)
        batches.append(
            {
                "execution_id": str(ex.id),
                "process_id": str(ex.process_id),
                "workflow": names.get(ex.process_id) or "Untitled workflow",
                "label": label,
                "started_at": (ex.started_at or ex.created_at).isoformat()
                if (ex.started_at or ex.created_at)
                else None,
                "step_name": (current.step.name if current.step is not None else None) or f"Step {current.step_number}",
                "step_number": steps.index(current) + 1,
                "step_total": len(steps),
                "waited_seconds": waited,
                "waiting": waited >= WAITING_SECONDS,
                "last_by": _operator(last),
                "href": f"/core/flows/batches/start?id={ex.process_id}&execution_id={ex.id}&return_to=/core/record",
            }
        )
    # The batch that has waited longest first: it is the one most likely to need recording now.
    batches.sort(key=lambda b: -b["waited_seconds"])

    last_used = dict(
        session.query(Execution.process_id, func.max(Execution.started_at))
        .filter(Execution.org_id == org_id)
        .group_by(Execution.process_id)
        .all()
    )
    in_flight: dict[str, int] = {}
    for b in batches:
        in_flight[b["process_id"]] = in_flight.get(b["process_id"], 0) + 1
    workflows = []
    processes = (
        session.query(Process)
        .options(selectinload(Process.steps))
        .filter(Process.org_id == org_id, Process.is_draft.is_(False))
        .order_by(Process.name.asc())
        .limit(MAX_WORKFLOWS)
        .all()
    )
    for p in processes:
        steps: list[Step] = list(p.steps)  # nosemgrep: orm-relationship-access-in-loop -- selectinload above
        if not steps:
            continue
        first = steps[0]
        used = last_used.get(p.id)
        workflows.append(
            {
                "process_id": str(p.id),
                "name": p.name,
                "step_count": len(steps),
                "first_step": first.name,
                "in_flight": in_flight.get(str(p.id), 0),
                "last_started_at": used.isoformat() if used else None,
                "href": f"/core/flows/batches/start?draft=1&id={p.id}&step_id={first.id}&return_to=/core/record",
            }
        )
    workflows.sort(
        key=lambda w: (
            w["last_started_at"] is None,
            -(datetime.fromisoformat(w["last_started_at"]).timestamp() if w["last_started_at"] else 0),
            w["name"].casefold(),
        )
    )
    return {"batches": batches, "workflows": workflows}


@record_step_bp.route("/core/record", methods=["GET"])
@requires_auth
def record_page():
    return render_template("record_step/record_step.html", active_page="core")


@record_step_bp.route("/api/core/record-options", methods=["GET"])
@requires_auth
def get_record_options():
    return jsonify(record_options(db_session, UUID(str(g.org_id)))), 200
