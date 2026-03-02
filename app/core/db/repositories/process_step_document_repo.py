"""Repository for process step documents (SOP)."""

from uuid import UUID

from sqlalchemy.orm import Session

from app.core.db.models.process_step_document import ProcessStepDocument


class ProcessStepDocumentRepository:
    def __init__(self, db: Session):
        self.db = db

    def create(
        self,
        org_id: UUID,
        process_id: UUID,
        step_id: UUID,
        title: str,
        storage_path: str | None = None,
        content_markdown: str | None = None,
        mime_type: str | None = None,
        file_size: int | None = None,
        created_by: UUID | None = None,
    ) -> ProcessStepDocument:
        doc = ProcessStepDocument(
            org_id=org_id,
            process_id=process_id,
            step_id=step_id,
            title=title,
            storage_path=storage_path,
            content_markdown=content_markdown,
            mime_type=mime_type,
            file_size=file_size,
            created_by=created_by,
        )
        self.db.add(doc)
        self.db.flush()
        return doc

    def get_by_id(self, doc_id: UUID, org_id: UUID, exclude_deleted: bool = True) -> ProcessStepDocument | None:
        q = self.db.query(ProcessStepDocument).filter(
            ProcessStepDocument.id == doc_id,
            ProcessStepDocument.org_id == org_id,
        )
        if exclude_deleted:
            q = q.filter(ProcessStepDocument.deleted_at.is_(None))
        return q.first()

    def list_by_step(self, step_id: UUID, org_id: UUID) -> list[ProcessStepDocument]:
        return (
            self.db.query(ProcessStepDocument)
            .filter(
                ProcessStepDocument.step_id == step_id,
                ProcessStepDocument.org_id == org_id,
                ProcessStepDocument.deleted_at.is_(None),
            )
            .order_by(ProcessStepDocument.created_at.asc())
            .all()
        )

    def soft_delete(self, doc_id: UUID, org_id: UUID) -> bool:
        from datetime import datetime, timezone

        updated = (
            self.db.query(ProcessStepDocument)
            .filter(
                ProcessStepDocument.id == doc_id,
                ProcessStepDocument.org_id == org_id,
            )
            .update({"deleted_at": datetime.now(timezone.utc)})
        )
        return updated > 0

    def update_inline(
        self,
        doc_id: UUID,
        org_id: UUID,
        title: str | None = None,
        content_markdown: str | None = None,
    ) -> ProcessStepDocument | None:
        doc = self.get_by_id(doc_id, org_id)
        if not doc:
            return None
        if title is not None:
            doc.title = title
        if content_markdown is not None:
            doc.content_markdown = content_markdown
        self.db.flush()
        return doc
