"""Repository for execution evidence records."""

from uuid import UUID

from sqlalchemy.orm import Session

from app.core.db.models.execution_evidence import (
    ExecutionEvidence,
    EVIDENCE_STATUS_ACTIVE,
    EVIDENCE_STATUS_PENDING,
)


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
        evidence_status: str = EVIDENCE_STATUS_PENDING,
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
            evidence_status=evidence_status,
        )
        self.db.add(record)
        self.db.flush()
        return record

    def get_by_id(
        self, evidence_id: UUID, org_id: UUID | None = None, active_only: bool = True
    ) -> ExecutionEvidence | None:
        q = self.db.query(ExecutionEvidence).filter(ExecutionEvidence.id == evidence_id)
        if org_id is not None:
            q = q.filter(ExecutionEvidence.org_id == org_id)
        if active_only:
            q = q.filter(ExecutionEvidence.evidence_status == EVIDENCE_STATUS_ACTIVE)
        return q.first()

    def update_status(self, evidence_id: UUID, org_id: UUID, evidence_status: str) -> bool:
        updated = (
            self.db.query(ExecutionEvidence)
            .filter(ExecutionEvidence.id == evidence_id, ExecutionEvidence.org_id == org_id)
            .update({"evidence_status": evidence_status})
        )
        return updated > 0

    def delete_by_id(self, evidence_id: UUID, org_id: UUID) -> bool:
        deleted = (
            self.db.query(ExecutionEvidence)
            .filter(ExecutionEvidence.id == evidence_id, ExecutionEvidence.org_id == org_id)
            .delete()
        )
        return deleted > 0

    def list_by_execution(self, execution_id: UUID, org_id: UUID) -> list[ExecutionEvidence]:
        return (
            self.db.query(ExecutionEvidence)
            .filter(
                ExecutionEvidence.execution_id == execution_id,
                ExecutionEvidence.org_id == org_id,
                ExecutionEvidence.evidence_status == EVIDENCE_STATUS_ACTIVE,
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
                ExecutionEvidence.evidence_status == EVIDENCE_STATUS_ACTIVE,
            )
            .order_by(ExecutionEvidence.created_at.asc())
            .all()
        )
