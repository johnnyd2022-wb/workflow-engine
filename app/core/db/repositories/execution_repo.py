"""Execution repository with tenancy enforcement"""

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy.orm import Session, joinedload

from app.core.backend.event_writer import EventWriter
from app.core.db.models.execution import Execution, ExecutionStatus
from app.core.db.models.execution_step import ExecutionStep, ExecutionStepStatus
from app.core.db.models.process import Process
from app.core.db.models.process_version import ProcessVersion
from app.core.db.models.step import Step
from app.observability import start_span


def _extract_consumed(actual_inputs: list) -> list[dict]:
    """Extract consumed item references from actual_inputs list."""
    result = []
    for inp in actual_inputs or []:
        if not isinstance(inp, dict):
            continue
        item_id = inp.get("inventory_item_id") or inp.get("item_id")
        if item_id:
            result.append(
                {
                    "item_id": str(item_id),
                    "quantity": inp.get("quantity") or inp.get("quantity_used"),
                    "unit": inp.get("unit"),
                }
            )
    return result


def _extract_produced(actual_outputs: list) -> list[dict]:
    """Extract produced item references from actual_outputs list."""
    result = []
    for out in actual_outputs or []:
        if not isinstance(out, dict):
            continue
        item_id = out.get("inventory_item_id") or out.get("item_id")
        if item_id:
            result.append(
                {
                    "item_id": str(item_id),
                    "quantity": out.get("quantity") or out.get("quantity_produced"),
                    "unit": out.get("unit"),
                }
            )
    return result


class ExecutionRepository:
    """Repository for execution operations with automatic tenancy enforcement"""

    def __init__(self, db: Session):
        self.db = db

    def create_execution(self, org_id: UUID, process_id: UUID, commit: bool = True) -> Execution:
        """Create a new execution and initialize execution steps.

        This operation is fully transactional - either all execution steps are created
        or none are (prevents partial execution state under concurrent requests).
        If commit=False, caller is responsible for commit (e.g. atomic reconciliation).
        """
        from sqlalchemy.exc import IntegrityError

        with start_span(
            "execution.create",
            attributes={"org_id": str(org_id), "process_id": str(process_id)},
        ) as span:
            try:
                # Verify process exists and belongs to org
                process = self.db.query(Process).filter(Process.id == process_id, Process.org_id == org_id).first()
                if not process:
                    raise ValueError(f"Process {process_id} not found or does not belong to org {org_id}")

                # Create execution
                execution = Execution(org_id=org_id, process_id=process_id, status=ExecutionStatus.PENDING)
                self.db.add(execution)
                self.db.flush()
                _ = execution.id
                if span is not None:
                    span.set_attribute("execution_id", str(execution.id))

                # Create execution steps for each step in the process
                steps = self.db.query(Step).filter(Step.process_id == process_id).order_by(Step.position).all()
                execution_steps = []
                total_steps = len(steps)
                if span is not None:
                    span.set_attribute("total_steps", total_steps)

                # Snapshot total_steps at creation for progress calculation integrity
                execution.total_steps = total_steps

                # Determine terminal step (last in position order).
                terminal_index = total_steps

                for i, step in enumerate(steps, start=1):
                    is_terminal = i == terminal_index if terminal_index else False
                    exec_step = ExecutionStep(
                        execution_id=execution.id,
                        step_id=step.id,
                        # Snapshot an execution-local ordering index so later step reorders
                        # do not change execution progression.
                        step_number=i,
                        status=ExecutionStepStatus.PENDING,
                        is_terminal_step=is_terminal,
                    )
                    execution_steps.append(exec_step)
                    self.db.add(exec_step)

                # Mark first step(s) as ready (steps with no dependencies or dependencies already met)
                # For now, we'll mark the first step as ready
                if execution_steps:
                    execution_steps[0].status = ExecutionStepStatus.READY

                execution.status = ExecutionStatus.IN_PROGRESS

                # Link to the current process version snapshot
                latest_version = (
                    self.db.query(ProcessVersion)
                    .filter(ProcessVersion.process_id == process_id)
                    .order_by(ProcessVersion.version_number.desc())
                    .first()
                )
                if latest_version:
                    execution.process_version_id = latest_version.id

                ew = EventWriter(self.db, org_id)
                ew.emit(
                    event_type="execution.created",
                    entity_type="execution",
                    entity_id=execution.id,
                    payload={
                        "execution_id": str(execution.id),
                        "process_id": str(process_id),
                        "process_version_id": str(latest_version.id) if latest_version else None,
                        "process_version_number": latest_version.version_number if latest_version else None,
                        "process_version_date": latest_version.created_at.isoformat() if latest_version else None,
                        "total_steps": total_steps,
                        "status": ExecutionStatus.IN_PROGRESS.value,
                    },
                )
                # Also emit on the process entity so process summary tracks run counts
                if latest_version:
                    ew.emit(
                        event_type="execution.created",
                        entity_type="process",
                        entity_id=process_id,
                        payload={
                            "execution_id": str(execution.id),
                            "process_id": str(process_id),
                            "process_version_number": latest_version.version_number,
                        },
                    )

                if commit:
                    self.db.commit()
                return execution
            except IntegrityError:
                # Rollback on any integrity error to prevent partial state
                self.db.rollback()
                raise
            except Exception:
                # Rollback on any other error to prevent partial state
                self.db.rollback()
                raise

    def get_execution_by_id(self, execution_id: UUID, org_id: UUID | None = None) -> Execution | None:
        """Get execution by ID, optionally scoped to org"""
        query = self.db.query(Execution).filter(Execution.id == execution_id)
        if org_id:
            query = query.filter(Execution.org_id == org_id)
        return query.first()

    def list_executions(
        self, org_id: UUID, process_id: UUID | None = None, status: ExecutionStatus | None = None
    ) -> list[Execution]:
        """List executions for an organisation, optionally filtered by process or status"""
        query = (
            self.db.query(Execution)
            .options(joinedload(Execution.execution_steps).joinedload(ExecutionStep.step))
            .filter(Execution.org_id == org_id)
        )
        if process_id:
            query = query.filter(Execution.process_id == process_id)
        if status:
            query = query.filter(Execution.status == status)
        return query.order_by(Execution.created_at.desc()).all()

    def get_execution_with_steps(self, execution_id: UUID, org_id: UUID) -> Execution | None:
        """Get execution with execution steps and related Step rows loaded (no N+1)."""
        q = self.db.query(Execution).options(joinedload(Execution.execution_steps).joinedload(ExecutionStep.step))
        q = q.filter(Execution.id == execution_id, Execution.org_id == org_id)
        return q.first()

    def get_ready_steps(self, execution_id: UUID, org_id: UUID) -> list[ExecutionStep]:
        """Get all execution steps that are ready to execute"""
        execution = self.get_execution_by_id(execution_id, org_id)
        if not execution:
            return []

        return (
            self.db.query(ExecutionStep)
            .filter(
                ExecutionStep.execution_id == execution_id,
                ExecutionStep.status == ExecutionStepStatus.READY,
            )
            .order_by(ExecutionStep.step_number)
            .all()
        )

    def complete_step(
        self,
        execution_step_id: UUID,
        org_id: UUID,
        actual_inputs: list | None = None,
        actual_outputs: list | None = None,
        execution_data: dict | None = None,
        commit: bool = True,
        completed_at_override: datetime | None = None,
    ) -> ExecutionStep | None:
        """Complete an execution step and advance execution.

        Enforces step order: all prior steps must be completed before this step can be completed.
        If commit=False, caller is responsible for commit (e.g. atomic reconciliation).
        completed_at_override: optional datetime for tests/fixtures that need a specific completion time
        (e.g. expired output expiry); when None, uses utcnow().
        """
        with start_span(
            "execution.complete_step",
            attributes={
                "org_id": str(org_id),
                "execution_step_id": str(execution_step_id),
                "items_consumed_count": len(actual_inputs or []),
                "items_produced_count": len(actual_outputs or []),
            },
        ) as span:
            execution_step = (
                self.db.query(ExecutionStep)
                .join(Execution)
                .filter(ExecutionStep.id == execution_step_id, Execution.org_id == org_id)
                .first()
            )
            if not execution_step:
                return None

            execution = execution_step.execution
            if span is not None:
                span.set_attribute("execution_id", str(execution.id))
                span.set_attribute("step_number", execution_step.step_number)

            # Enforce step order FIRST: all prior steps must be completed. This ensures that
            # out-of-order attempts raise a distinct error that tests (and callers) can rely on.
            prior_steps = (
                self.db.query(ExecutionStep)
                .filter(
                    ExecutionStep.execution_id == execution.id,
                    ExecutionStep.step_number < execution_step.step_number,
                )
                .all()
            )
            incomplete_prior_steps = [es for es in prior_steps if es.status != ExecutionStepStatus.COMPLETED]
            if incomplete_prior_steps:
                raise ValueError(
                    f"Cannot complete step {execution_step.step_number}: "
                    f"prior steps {[es.step_number for es in incomplete_prior_steps]} are not completed"
                )

            # Then enforce that this step itself is in a completable state
            if execution_step.status not in (ExecutionStepStatus.READY, ExecutionStepStatus.IN_PROGRESS):
                raise ValueError(f"Step {execution_step_id} is not in a state that can be completed")

            # Update step status and data
            execution_step.status = ExecutionStepStatus.COMPLETED
            execution_step.actual_inputs = actual_inputs or []
            execution_step.actual_outputs = actual_outputs or []
            execution_step.execution_data = execution_data or {}
            execution_step.completed_at = (
                completed_at_override if completed_at_override is not None else datetime.now(timezone.utc)
            )

            # Advance execution: mark next steps as ready
            self._advance_execution(execution)

            # --- Event emission with causal chain ---
            step_name = execution_step.step.name if execution_step.step else f"Step {execution_step.step_number}"
            items_consumed = _extract_consumed(actual_inputs or [])
            items_produced = _extract_produced(actual_outputs or [])
            evidence_ids = (execution_data or {}).get("evidence_ids", [])

            ew = EventWriter(self.db, org_id)
            step_event = ew.emit(
                event_type="execution.step_completed",
                entity_type="execution",
                entity_id=execution.id,
                payload={
                    "execution_id": str(execution.id),
                    "execution_step_id": str(execution_step.id),
                    "step_id": str(execution_step.step_id) if execution_step.step_id else None,
                    "step_number": execution_step.step_number,
                    "step_name": step_name,
                    "actual_inputs": actual_inputs or [],
                    "actual_outputs": actual_outputs or [],
                    "execution_data": execution_data or {},
                    "items_consumed": items_consumed,
                    "items_produced": items_produced,
                    "evidence_ids": evidence_ids,
                    "completed_at": execution_step.completed_at.isoformat() if execution_step.completed_at else None,
                },
            )

            # Consumed items — causation_id links back to the step_completed event
            for consumed in items_consumed:
                item_id = consumed.get("item_id")
                if item_id:
                    try:
                        from uuid import UUID as _UUID

                        item_uuid = _UUID(str(item_id))
                        ew.emit(
                            event_type="inventory_item.consumed",
                            entity_type="inventory_item",
                            entity_id=item_uuid,
                            payload={
                                "inventory_item_id": str(item_id),
                                "quantity_consumed": consumed.get("quantity"),
                                "unit": consumed.get("unit"),
                                "execution_id": str(execution.id),
                                "execution_step_id": str(execution_step.id),
                                "step_name": step_name,
                                "process_id": str(execution.process_id),
                            },
                            causation_id=step_event.id,
                        )
                    except Exception:
                        pass

            # Produced items
            for produced in items_produced:
                item_id = produced.get("item_id")
                if item_id:
                    try:
                        from uuid import UUID as _UUID

                        item_uuid = _UUID(str(item_id))
                        ew.emit(
                            event_type="inventory_item.produced",
                            entity_type="inventory_item",
                            entity_id=item_uuid,
                            payload={
                                "inventory_item_id": str(item_id),
                                "quantity_produced": produced.get("quantity"),
                                "unit": produced.get("unit"),
                                "execution_id": str(execution.id),
                                "execution_step_id": str(execution_step.id),
                                "step_name": step_name,
                            },
                            causation_id=step_event.id,
                        )
                    except Exception:
                        pass

            # If execution is now complete, emit execution.completed
            if execution.status == ExecutionStatus.COMPLETED:
                ew.emit(
                    event_type="execution.completed",
                    entity_type="execution",
                    entity_id=execution.id,
                    payload={
                        "execution_id": str(execution.id),
                        "process_id": str(execution.process_id),
                        "total_steps": execution.total_steps,
                        "completed_at": execution.completed_at.isoformat() if execution.completed_at else None,
                    },
                    causation_id=step_event.id,
                )
                # Update process summary for completed run
                ew.emit(
                    event_type="execution.completed",
                    entity_type="process",
                    entity_id=execution.process_id,
                    payload={
                        "execution_id": str(execution.id),
                        "process_id": str(execution.process_id),
                    },
                    causation_id=step_event.id,
                )

            if commit:
                self.db.commit()
            return execution_step

    def _advance_execution(self, execution: Execution) -> None:
        """Advance execution by marking next steps as ready based on DAG dependencies"""
        with start_span(
            "execution.advance",
            attributes={
                "execution_id": str(execution.id),
                "org_id": str(execution.org_id),
            },
        ):
            # Get all execution steps for this execution
            execution_steps = (
                self.db.query(ExecutionStep)
                .filter(ExecutionStep.execution_id == execution.id)
                .order_by(ExecutionStep.step_number)
                .all()
            )

            # Build a map of step outputs to step numbers for dependency tracking
            # For now, we'll use a simple sequential model: step N+1 depends on step N
            # In a full DAG implementation, we'd parse step inputs/outputs to determine dependencies
            completed_step_numbers = {
                es.step_number for es in execution_steps if es.status == ExecutionStepStatus.COMPLETED
            }

            # Mark next steps as ready (simplified: next step after highest completed)
            if completed_step_numbers:
                max_completed = max(completed_step_numbers)
                # Find next step(s) that should be ready
                for exec_step in execution_steps:
                    if exec_step.step_number > max_completed and exec_step.status == ExecutionStepStatus.PENDING:
                        # Check if all previous steps are completed (simple sequential check)
                        all_previous_completed = all(
                            es.status == ExecutionStepStatus.COMPLETED
                            for es in execution_steps
                            if es.step_number < exec_step.step_number
                        )
                        if all_previous_completed:
                            exec_step.status = ExecutionStepStatus.READY

            # Check if execution is complete (all steps completed)
            all_completed = all(es.status == ExecutionStepStatus.COMPLETED for es in execution_steps)
            if all_completed and execution.status != ExecutionStatus.COMPLETED:
                execution.status = ExecutionStatus.COMPLETED
                execution.completed_at = datetime.now(timezone.utc)
