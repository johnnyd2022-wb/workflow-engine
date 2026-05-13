"""Repository for XeroSyncJob records."""

from datetime import datetime
from uuid import UUID

from sqlalchemy.orm import Session

from app.features.crm.models.xero_sync_job import XeroSyncJob


class XeroSyncJobRepository:
    def __init__(self, db: Session):
        self.db = db

    def create(self, org_id: UUID, xero_tenant_id: str, sync_type: str, triggered_by: str) -> XeroSyncJob:
        job = XeroSyncJob(
            org_id=org_id,
            xero_tenant_id=xero_tenant_id,
            sync_type=sync_type,
            status="running",
            triggered_by=triggered_by,
            started_at=datetime.utcnow(),
        )
        self.db.add(job)
        self.db.flush()
        return job

    def mark_completed(
        self,
        job_id: UUID,
        contacts_synced: int = 0,
        invoices_synced: int = 0,
    ) -> None:
        self.db.query(XeroSyncJob).filter(XeroSyncJob.id == job_id).update(
            {
                "status": "completed",
                "completed_at": datetime.utcnow(),
                "contacts_synced": contacts_synced,
                "invoices_synced": invoices_synced,
                "updated_at": datetime.utcnow(),
            }
        )

    def mark_failed(self, job_id: UUID, error_message: str, error_details: dict | None = None) -> None:
        self.db.query(XeroSyncJob).filter(XeroSyncJob.id == job_id).update(
            {
                "status": "failed",
                "completed_at": datetime.utcnow(),
                "error_message": error_message,
                "error_details": error_details,
                "updated_at": datetime.utcnow(),
            }
        )

    def mark_partial(
        self,
        job_id: UUID,
        contacts_synced: int,
        invoices_synced: int,
        error_message: str,
        error_details: dict | None = None,
    ) -> None:
        self.db.query(XeroSyncJob).filter(XeroSyncJob.id == job_id).update(
            {
                "status": "partial",
                "completed_at": datetime.utcnow(),
                "contacts_synced": contacts_synced,
                "invoices_synced": invoices_synced,
                "error_message": error_message,
                "error_details": error_details,
                "updated_at": datetime.utcnow(),
            }
        )

    def get_latest(self, org_id: UUID) -> XeroSyncJob | None:
        return (
            self.db.query(XeroSyncJob)
            .filter(XeroSyncJob.org_id == org_id)
            .order_by(XeroSyncJob.created_at.desc())
            .first()
        )

    def list_recent(self, org_id: UUID, limit: int = 10) -> list[XeroSyncJob]:
        return (
            self.db.query(XeroSyncJob)
            .filter(XeroSyncJob.org_id == org_id)
            .order_by(XeroSyncJob.created_at.desc())
            .limit(limit)
            .all()
        )
