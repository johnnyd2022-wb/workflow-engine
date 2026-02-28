"""Repository for execution evidence records."""

from uuid import UUID

from sqlalchemy.orm import Session

from app.core.db.models.execution_evidence import ExecutionEvidence


class EvidenceRepository:
    def __init__(self, db: Session):
        self.db = db

    def create(
        self,
        org_id: UUID,
        execution_id: UUID,
        file_name: str,
        storage_path: str,
        mime_type: str,
        file_size: int,
        checksum_sha256: str,
        step_id: UUID | None = None,
        uploaded_by: str | None = None,
        extra_data: dict | None = None,
    ) -> ExecutionEvidence:
        record = ExecutionEvidence(
            org_id=org_id,
            execution_id=execution_id,
            step_id=step_id,
            file_name=file_name,
            storage_path=storage_path,
            mime_type=mime_type,
            file_size=file_size,
            checksum_sha256=checksum_sha256,
            uploaded_by=uploaded_by,
            extra_data=extra_data,
        )
        self.db.add(record)
        self.db.flush()
        return record

    def get_by_id(self, evidence_id: UUID, org_id: UUID | None = None) -> ExecutionEvidence | None:
        q = self.db.query(ExecutionEvidence).filter(ExecutionEvidence.id == evidence_id)
        if org_id is not None:
            q = q.filter(ExecutionEvidence.org_id == org_id)
        return q.first()

    def list_by_execution(self, execution_id: UUID, org_id: UUID) -> list[ExecutionEvidence]:
        return (
            self.db.query(ExecutionEvidence)
            .filter(
                ExecutionEvidence.execution_id == execution_id,
                ExecutionEvidence.org_id == org_id,
            )
            .order_by(ExecutionEvidence.created_at.asc())
            .all()
        )

    def list_by_step(self, execution_id: UUID, step_id: UUID, org_id: UUID) -> list[ExecutionEvidence]:
        return (
            self.db.query(ExecutionEvidence)
            .filter(
                ExecutionEvidence.execution_id == execution_id,
                ExecutionEvidence.step_id == step_id,
                ExecutionEvidence.org_id == org_id,
            )
            .order_by(ExecutionEvidence.created_at.asc())
            .all()
        )
