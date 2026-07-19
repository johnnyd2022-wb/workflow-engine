"""Process repository with tenancy enforcement"""

from uuid import UUID

from sqlalchemy import func
from sqlalchemy.orm import Session, selectinload

from app.core.backend.event_writer import EventWriter
from app.core.db.models.process import Process, ProcessCategory
from app.core.db.models.process_version import ProcessVersion
from app.core.db.models.step import Step
from app.observability import start_span


def _step_snapshot(step: Step) -> dict:
    return {
        "id": str(step.id),
        "step_number": step.step_number,
        "position": str(step.position) if step.position is not None else None,
        "name": step.name,
        "description": step.description,
        "inputs": step.inputs or [],
        "outputs": step.outputs or [],
        "execution_prompts": step.execution_prompts or [],
    }


def _process_snapshot(process: Process, steps: list[Step]) -> dict:
    return {
        "id": str(process.id),
        "name": process.name,
        "description": process.description,
        "category": process.category.value if process.category else None,
        "is_draft": process.is_draft,
        "steps": [_step_snapshot(s) for s in sorted(steps, key=lambda s: s.step_number)],
    }


def _next_version_number(db: Session, process_id: UUID) -> int:
    row = (
        db.query(func.coalesce(func.max(ProcessVersion.version_number), 0))
        .filter(ProcessVersion.process_id == process_id)
        .scalar()
    )
    return (row or 0) + 1


def _insert_process_version(
    db: Session,
    org_id: UUID,
    process: Process,
    steps: list[Step],
    change_summary: str | None = None,
) -> ProcessVersion:
    version_number = _next_version_number(db, process.id)
    pv = ProcessVersion(
        org_id=org_id,
        process_id=process.id,
        version_number=version_number,
        snapshot=_process_snapshot(process, steps),
        change_summary=change_summary,
    )
    db.add(pv)
    db.flush()
    return pv


def _current_steps(db: Session, process_id: UUID) -> list[Step]:
    return db.query(Step).filter(Step.process_id == process_id).order_by(Step.step_number).all()


def _step_diff(before: Step, after: Step) -> dict:
    diff = {}
    for field in ("step_number", "name", "description", "inputs", "outputs", "execution_prompts"):
        old_val = getattr(before, field, None)
        new_val = getattr(after, field, None)
        if old_val != new_val:
            diff[field] = {"before": old_val, "after": new_val}
    return diff


class ProcessRepository:
    """Repository for process operations with automatic tenancy enforcement"""

    def __init__(self, db: Session):
        self.db = db

    def create_process(
        self,
        org_id: UUID,
        name: str,
        description: str | None = None,
        category: ProcessCategory | None = None,
        is_draft: bool = False,
    ) -> Process:
        """Create a new process"""
        with start_span(
            "process.create",
            attributes={"org_id": str(org_id), "category": category.value if category else None},
        ):
            process = Process(org_id=org_id, name=name, description=description, category=category, is_draft=is_draft)
            self.db.add(process)
            self.db.flush()
            _ = process.id

            pv = _insert_process_version(self.db, org_id, process, [], change_summary="Process created")

            ew = EventWriter(self.db, org_id)
            ew.emit(
                event_type="process.created",
                entity_type="process",
                entity_id=process.id,
                payload={
                    **_process_snapshot(process, []),
                    "process_version_id": str(pv.id),
                    "version_number": pv.version_number,
                },
            )
            self.db.commit()
            return process

    def get_process_by_id(self, process_id: UUID, org_id: UUID) -> Process | None:
        """Get process by ID (must be scoped to org)."""
        return self.db.query(Process).filter(Process.id == process_id, Process.org_id == org_id).first()

    def list_processes(self, org_id: UUID) -> list[Process]:
        """List all processes for an organisation"""
        return self.db.query(Process).filter(Process.org_id == org_id).order_by(Process.created_at.desc()).all()

    def update_process(
        self,
        process_id: UUID,
        org_id: UUID,
        name: str | None = None,
        description: str | None = None,
        category: ProcessCategory | None = None,
        is_draft: bool | None = None,
    ) -> Process | None:
        """Update process (must belong to org)"""
        with start_span(
            "process.update",
            attributes={"org_id": str(org_id), "process_id": str(process_id)},
        ):
            process = self.get_process_by_id(process_id, org_id)
            if not process:
                return None

            diff: dict = {}
            if name is not None and name != process.name:
                diff["name"] = {"before": process.name, "after": name}
                process.name = name
            if description is not None and description != process.description:
                diff["description"] = {"before": process.description, "after": description}
                process.description = description
            if category is not None and category != process.category:
                diff["category"] = {
                    "before": process.category.value if process.category else None,
                    "after": category.value if category else None,
                }
                process.category = category
            if is_draft is not None and is_draft != process.is_draft:
                diff["is_draft"] = {"before": process.is_draft, "after": is_draft}
                process.is_draft = is_draft

            if not diff:
                return process

            steps = _current_steps(self.db, process_id)
            pv = _insert_process_version(self.db, org_id, process, steps, change_summary="Process updated")

            ew = EventWriter(self.db, org_id)
            ew.emit(
                event_type="process.updated",
                entity_type="process",
                entity_id=process.id,
                payload={
                    **_process_snapshot(process, steps),
                    "process_version_id": str(pv.id),
                    "version_number": pv.version_number,
                    "change_summary": "Process updated",
                },
                diff=diff,
            )
            self.db.commit()
            self.db.expire(process, ["updated_at"])
            _ = process.updated_at
            return process

    def delete_process(self, process_id: UUID, org_id: UUID) -> bool:
        """Delete process (cascade deletes steps)"""
        with start_span(
            "process.delete",
            attributes={"org_id": str(org_id), "process_id": str(process_id)},
        ):
            process = self.get_process_by_id(process_id, org_id)
            if not process:
                return False

            steps = _current_steps(self.db, process_id)
            ew = EventWriter(self.db, org_id)
            ew.emit(
                event_type="process.deleted",
                entity_type="process",
                entity_id=process.id,
                payload=_process_snapshot(process, steps),
            )
            self.db.delete(process)
            self.db.commit()
            return True

    def add_step(
        self,
        process_id: UUID,
        org_id: UUID,
        step_number: int,
        name: str,
        position=None,
        description: str | None = None,
        inputs: list | None = None,
        outputs: list | None = None,
        execution_prompts: list | None = None,
    ) -> Step | None:
        """Add a step to a process"""
        with start_span(
            "process.step_add",
            attributes={"org_id": str(org_id), "process_id": str(process_id), "step_number": step_number},
        ):
            process = self.get_process_by_id(process_id, org_id)
            if not process:
                return None

            step = Step(
                process_id=process_id,
                step_number=step_number,
                position=position,
                name=name,
                description=description,
                inputs=inputs or [],
                outputs=outputs or [],
                execution_prompts=execution_prompts or [],
            )
            self.db.add(step)
            self.db.flush()
            _ = step.id

            all_steps = _current_steps(self.db, process_id)
            pv = _insert_process_version(self.db, org_id, process, all_steps, change_summary=f"Added step: {name}")

            ew = EventWriter(self.db, org_id)
            ew.emit(
                event_type="process.step_added",
                entity_type="process",
                entity_id=process.id,
                payload={
                    "step": _step_snapshot(step),
                    "process_version_id": str(pv.id),
                    "version_number": pv.version_number,
                    "change_summary": f"Added step: {name}",
                },
            )
            self.db.commit()
            return step

    def update_step(
        self,
        step_id: UUID,
        process_id: UUID,
        org_id: UUID,
        step_number: int | None = None,
        name: str | None = None,
        position=None,
        description: str | None = None,
        inputs: list | None = None,
        outputs: list | None = None,
        execution_prompts: list | None = None,
    ) -> Step | None:
        """Update a step"""
        with start_span(
            "process.step_update",
            attributes={"org_id": str(org_id), "process_id": str(process_id), "step_id": str(step_id)},
        ):
            process = self.get_process_by_id(process_id, org_id)
            if not process:
                return None

            step = self.db.query(Step).filter(Step.id == step_id, Step.process_id == process_id).first()
            if not step:
                return None

            # Capture before state for diff
            before = _step_snapshot(step)

            if step_number is not None:
                step.step_number = step_number
            if position is not None:
                step.position = position
            if name is not None:
                step.name = name
            if description is not None:
                step.description = description
            if inputs is not None:
                step.inputs = inputs
            if outputs is not None:
                step.outputs = outputs
            if execution_prompts is not None:
                step.execution_prompts = execution_prompts

            after = _step_snapshot(step)
            diff = {k: {"before": before[k], "after": after[k]} for k in before if before[k] != after[k]}

            if not diff:
                return step

            all_steps = _current_steps(self.db, process_id)
            pv = _insert_process_version(
                self.db, org_id, process, all_steps, change_summary=f"Updated step: {step.name}"
            )

            ew = EventWriter(self.db, org_id)
            ew.emit(
                event_type="process.step_updated",
                entity_type="process",
                entity_id=process.id,
                payload={
                    "step": after,
                    "process_version_id": str(pv.id),
                    "version_number": pv.version_number,
                    "change_summary": f"Updated step: {step.name}",
                },
                diff={"step": diff},
            )
            self.db.commit()
            self.db.expire(step, ["updated_at"])
            _ = step.updated_at
            return step

    def delete_step(self, step_id: UUID, process_id: UUID, org_id: UUID) -> bool:
        """Delete a step from a process"""
        with start_span(
            "process.step_delete",
            attributes={"org_id": str(org_id), "process_id": str(process_id), "step_id": str(step_id)},
        ):
            process = self.get_process_by_id(process_id, org_id)
            if not process:
                return False

            step = self.db.query(Step).filter(Step.id == step_id, Step.process_id == process_id).first()
            if not step:
                return False

            step_snap = _step_snapshot(step)
            self.db.delete(step)
            self.db.flush()

            remaining_steps = _current_steps(self.db, process_id)
            pv = _insert_process_version(
                self.db, org_id, process, remaining_steps, change_summary=f"Deleted step: {step_snap['name']}"
            )

            ew = EventWriter(self.db, org_id)
            ew.emit(
                event_type="process.step_deleted",
                entity_type="process",
                entity_id=process.id,
                payload={
                    "deleted_step": step_snap,
                    "process_version_id": str(pv.id),
                    "version_number": pv.version_number,
                    "change_summary": f"Deleted step: {step_snap['name']}",
                },
            )
            self.db.commit()
            return True

    def get_process_with_steps(self, process_id: UUID, org_id: UUID) -> Process | None:
        """Get process with all its steps loaded in a single query."""
        return (
            self.db.query(Process)
            .filter(Process.id == process_id, Process.org_id == org_id)
            .options(selectinload(Process.steps))
            .first()
        )

    def get_processes_with_steps(self, process_ids: list[UUID], org_id: UUID) -> dict[UUID, Process]:
        """Batch version of get_process_with_steps — one query for many process IDs, keyed by id."""
        if not process_ids:
            return {}
        processes = (
            self.db.query(Process)
            .filter(Process.id.in_(process_ids), Process.org_id == org_id)
            .options(selectinload(Process.steps))
            .all()
        )
        return {p.id: p for p in processes}

    def get_latest_process_version(self, process_id: UUID) -> ProcessVersion | None:
        """Return the latest ProcessVersion for this process (used when creating executions)."""
        return (
            self.db.query(ProcessVersion)
            .filter(ProcessVersion.process_id == process_id)
            .order_by(ProcessVersion.version_number.desc())
            .first()
        )
