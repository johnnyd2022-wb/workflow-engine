"""Process repository with tenancy enforcement"""

from uuid import UUID

from sqlalchemy.orm import Session

from app.core.db.models.process import Process, ProcessCategory
from app.core.db.models.step import Step


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
    ) -> Process:
        """Create a new process"""
        process = Process(org_id=org_id, name=name, description=description, category=category)
        self.db.add(process)
        self.db.flush()
        _ = process.id
        self.db.commit()
        return process

    def get_process_by_id(self, process_id: UUID, org_id: UUID | None = None) -> Process | None:
        """Get process by ID, optionally scoped to org"""
        query = self.db.query(Process).filter(Process.id == process_id)
        if org_id:
            query = query.filter(Process.org_id == org_id)
        return query.first()

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
    ) -> Process | None:
        """Update process (must belong to org)"""
        process = self.get_process_by_id(process_id, org_id)
        if not process:
            return None

        if name is not None:
            process.name = name
        if description is not None:
            process.description = description
        if category is not None:
            process.category = category

        self.db.commit()
        self.db.expire(process, ["updated_at"])
        _ = process.updated_at
        return process

    def delete_process(self, process_id: UUID, org_id: UUID) -> bool:
        """Delete process (cascade deletes steps)"""
        process = self.get_process_by_id(process_id, org_id)
        if not process:
            return False

        self.db.delete(process)
        self.db.commit()
        return True

    def add_step(
        self,
        process_id: UUID,
        org_id: UUID,
        step_number: int,
        name: str,
        description: str | None = None,
        inputs: list | None = None,
        outputs: list | None = None,
        execution_prompts: list | None = None,
    ) -> Step | None:
        """Add a step to a process"""
        process = self.get_process_by_id(process_id, org_id)
        if not process:
            return None

        step = Step(
            process_id=process_id,
            step_number=step_number,
            name=name,
            description=description,
            inputs=inputs or [],
            outputs=outputs or [],
            execution_prompts=execution_prompts or [],
        )
        self.db.add(step)
        self.db.flush()
        _ = step.id
        self.db.commit()
        return step

    def update_step(
        self,
        step_id: UUID,
        process_id: UUID,
        org_id: UUID,
        step_number: int | None = None,
        name: str | None = None,
        description: str | None = None,
        inputs: list | None = None,
        outputs: list | None = None,
        execution_prompts: list | None = None,
    ) -> Step | None:
        """Update a step"""
        process = self.get_process_by_id(process_id, org_id)
        if not process:
            return None

        step = self.db.query(Step).filter(Step.id == step_id, Step.process_id == process_id).first()
        if not step:
            return None

        if step_number is not None:
            step.step_number = step_number
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

        self.db.commit()
        self.db.expire(step, ["updated_at"])
        _ = step.updated_at
        return step

    def delete_step(self, step_id: UUID, process_id: UUID, org_id: UUID) -> bool:
        """Delete a step from a process"""
        process = self.get_process_by_id(process_id, org_id)
        if not process:
            return False

        step = self.db.query(Step).filter(Step.id == step_id, Step.process_id == process_id).first()
        if not step:
            return False

        self.db.delete(step)
        self.db.commit()
        return True

    def get_process_with_steps(self, process_id: UUID, org_id: UUID) -> Process | None:
        """Get process with all its steps loaded"""
        process = self.get_process_by_id(process_id, org_id)
        if process:
            # Eager load steps
            _ = process.steps
        return process
