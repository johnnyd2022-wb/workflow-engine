"""Repository for CRMNote and CRMTask records."""

from uuid import UUID

from sqlalchemy.orm import Session

from app.core.utils.time import utc_now
from app.features.crm.models.crm_note import CRMNote
from app.features.crm.models.crm_task import CRMTask


class CRMNoteRepository:
    def __init__(self, db: Session):
        self.db = db

    def create(self, org_id: UUID, contact_id: UUID, content: str, created_by_user_id: UUID | None) -> CRMNote:
        note = CRMNote(
            org_id=org_id,
            contact_id=contact_id,
            content=content,
            created_by_user_id=created_by_user_id,
        )
        self.db.add(note)
        return note

    def get_by_id(self, note_id: UUID, org_id: UUID) -> CRMNote | None:
        return self.db.query(CRMNote).filter(CRMNote.id == note_id, CRMNote.org_id == org_id).first()

    def list_for_contact(self, contact_id: UUID, org_id: UUID) -> list[CRMNote]:
        return (
            self.db.query(CRMNote)
            .filter(CRMNote.contact_id == contact_id, CRMNote.org_id == org_id)
            .order_by(CRMNote.created_at.desc())
            .all()
        )

    def update(self, note: CRMNote, content: str) -> CRMNote:
        note.content = content
        note.updated_at = utc_now()
        return note

    def delete(self, note: CRMNote) -> None:
        self.db.delete(note)


class CRMTaskRepository:
    def __init__(self, db: Session):
        self.db = db

    def create(
        self,
        org_id: UUID,
        title: str,
        contact_id: UUID | None = None,
        description: str | None = None,
        due_date=None,
        priority: str = "medium",
        assigned_to_user_id: UUID | None = None,
        created_by_user_id: UUID | None = None,
    ) -> CRMTask:
        task = CRMTask(
            org_id=org_id,
            contact_id=contact_id,
            title=title,
            description=description,
            due_date=due_date,
            priority=priority,
            status="pending",
            assigned_to_user_id=assigned_to_user_id,
            created_by_user_id=created_by_user_id,
        )
        self.db.add(task)
        return task

    def get_by_id(self, task_id: UUID, org_id: UUID) -> CRMTask | None:
        return self.db.query(CRMTask).filter(CRMTask.id == task_id, CRMTask.org_id == org_id).first()

    def list_for_org(
        self,
        org_id: UUID,
        contact_id: UUID | None = None,
        status: str | None = None,
        assigned_to_user_id: UUID | None = None,
    ) -> list[CRMTask]:
        q = self.db.query(CRMTask).filter(CRMTask.org_id == org_id)
        if contact_id:
            q = q.filter(CRMTask.contact_id == contact_id)
        if status:
            q = q.filter(CRMTask.status == status)
        if assigned_to_user_id:
            q = q.filter(CRMTask.assigned_to_user_id == assigned_to_user_id)
        return q.order_by(CRMTask.due_date.asc().nulls_last(), CRMTask.created_at.desc()).all()

    def update(self, task: CRMTask, **fields) -> CRMTask:
        for k, v in fields.items():
            setattr(task, k, v)
        if fields.get("status") == "completed" and not task.completed_at:
            task.completed_at = utc_now()
        task.updated_at = utc_now()
        return task

    def delete(self, task: CRMTask) -> None:
        self.db.delete(task)
