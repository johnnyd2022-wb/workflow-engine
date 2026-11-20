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

from flask import Blueprint, g, jsonify, render_template, request
from sqlalchemy import exists, func, select
from sqlalchemy.orm import selectinload

from app.core.backend.dagtraversal import _split_trace_prompts
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
    """The batch code an operator recorded: the step's "Batch number" prompt (the convention the
    process builder and the trace use), else a batch or lot id typed on an output."""
    for step in steps:
        if isinstance(step.execution_data, dict):
            code, _ = _split_trace_prompts(step.execution_data)
            if code not in (None, ""):
                return str(code).strip() or None
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


def _batch_row(ex: Execution, names: dict, now: datetime) -> dict | None:
    """One batch's row, or None when it has no step to record (all done, or waiting)."""
    # nosemgrep: orm-relationship-access-in-loop -- callers selectinload the steps
    steps = sorted(ex.execution_steps, key=lambda s: s.step_number or 0)
    current = next((s for s in steps if s.status in _CURRENT), None)
    if current is None:
        return None
    done = [s for s in steps if s.status == ExecutionStepStatus.COMPLETED and s.completed_at]
    last = max(done, key=lambda s: s.completed_at) if done else None
    since = last.completed_at if last else (ex.started_at or ex.created_at)
    waited = max(0, int((now - since).total_seconds())) if since else 0
    begun = ex.started_at or ex.created_at
    return {
        "execution_id": str(ex.id),
        "process_id": str(ex.process_id),
        "workflow": names.get(ex.process_id) or "Untitled workflow",
        "label": _batch_label(steps),
        "started_at": begun.isoformat() if begun else None,
        "step_name": (current.step.name if current.step is not None else None) or f"Step {current.step_number}",
        "step_number": steps.index(current) + 1,
        "step_total": len(steps),
        "waited_seconds": waited,
        "waiting": waited >= WAITING_SECONDS,
        "last_by": _operator(last),
        "href": f"/core/flows/batches/start?id={ex.process_id}&execution_id={ex.id}&return_to=/core/record",
    }


def _recorded(session, org_id: UUID, execution_id: str | None, names: dict, now: datetime) -> dict | None:
    """The batch just recorded, read on its own: whether it is finished can't be inferred from
    its absence in the (bounded) list."""
    try:
        eid = UUID(str(execution_id))
    except (TypeError, ValueError):
        return None
    ex = (
        session.query(Execution)
        .options(selectinload(Execution.execution_steps).selectinload(ExecutionStep.step))
        .filter(Execution.org_id == org_id, Execution.id == eid)
        .one_or_none()
    )
    if ex is None:
        return None
    return {
        "execution_id": str(ex.id),
        "finished": _status(ex.status) == ExecutionStatus.COMPLETED.value,
        "batch": _batch_row(ex, names, now),
    }


def record_options(session, org_id: UUID, now: datetime | None = None, recorded: str | None = None) -> dict:
    now = now or datetime.now(UTC)
    names = {p.id: p.name for p in session.query(Process.id, Process.name).filter(Process.org_id == org_id)}

    # Only batches with a step to record, so the limit is spent on rows the page can show.
    recordable = exists().where(ExecutionStep.execution_id == Execution.id, ExecutionStep.status.in_(_CURRENT))
    open_batches = session.query(Execution).filter(Execution.org_id == org_id, Execution.status.in_(_OPEN), recordable)
    batches_total = open_batches.count()
    executions = (
        open_batches.options(selectinload(Execution.execution_steps).selectinload(ExecutionStep.step))
        .order_by(Execution.started_at.asc())
        .limit(MAX_BATCHES)
        .all()
    )
    batches = [row for row in (_batch_row(ex, names, now) for ex in executions) if row is not None]
    # The batch that has waited longest first: it is the one most likely to need recording now.
    batches.sort(key=lambda b: -b["waited_seconds"])

    in_flight = dict(
        session.query(Execution.process_id, func.count(Execution.id))
        .filter(Execution.org_id == org_id, Execution.status.in_(_OPEN), recordable)
        .group_by(Execution.process_id)
        .all()
    )
    last_used = (
        select(Execution.process_id, func.max(Execution.started_at).label("used"))
        .where(Execution.org_id == org_id)
        .group_by(Execution.process_id)
        .subquery()
    )
    # Runnable (not a draft, has a step) and most recently used first, before the limit, so
    # the limit never hides a runnable workflow behind empty ones or alphabetical order.
    runnable = session.query(Process).filter(
        Process.org_id == org_id,
        Process.is_draft.is_(False),
        exists().where(Step.process_id == Process.id),
    )
    workflows_total = runnable.count()
    processes = (
        runnable.outerjoin(last_used, last_used.c.process_id == Process.id)
        .add_columns(last_used.c.used)
        .options(selectinload(Process.steps))
        .order_by(last_used.c.used.desc().nulls_last(), func.lower(Process.name), Process.id)
        .limit(MAX_WORKFLOWS)
        .all()
    )
    workflows = []
    for p, used in processes:
        steps: list[Step] = list(p.steps)  # nosemgrep: orm-relationship-access-in-loop -- selectinload above
        first = steps[0]
        workflows.append(
            {
                "process_id": str(p.id),
                "name": p.name,
                "step_count": len(steps),
                "first_step": first.name,
                "in_flight": in_flight.get(p.id, 0),
                "last_started_at": used.isoformat() if used else None,
                "href": f"/core/flows/batches/start?draft=1&id={p.id}&step_id={first.id}&return_to=/core/record",
            }
        )
    return {
        "batches": batches,
        "batches_total": batches_total,
        "workflows": workflows,
        "workflows_total": workflows_total,
        "recorded": _recorded(session, org_id, recorded, names, now) if recorded else None,
    }


@record_step_bp.route("/core/record", methods=["GET"])
@requires_auth
def record_page():
    return render_template("record_step/record_step.html", active_page="core")


@record_step_bp.route("/api/core/record-options", methods=["GET"])
@requires_auth
def get_record_options():
    return jsonify(record_options(db_session, UUID(str(g.org_id)), recorded=request.args.get("recorded"))), 200
