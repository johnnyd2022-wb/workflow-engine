"""XeroSyncJob — tracks a single sync run (contacts, invoices, or full)."""

import uuid
from datetime import datetime

from sqlalchemy import TIMESTAMP, Column, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID

from app.core.db.models.models import Base


class XeroSyncJob(Base):
    __tablename__ = "xero_sync_jobs"
    __table_args__ = (Index("ix_xero_sync_jobs_org_created", "org_id", "created_at"),)

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id = Column(UUID(as_uuid=True), ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False, index=True)
    xero_tenant_id = Column(String(100), nullable=False)
    sync_type = Column(String(50), nullable=False)  # contacts | invoices | full
    status = Column(String(50), nullable=False)  # pending | running | completed | failed | partial
    started_at = Column(TIMESTAMP(timezone=True), nullable=True)
    completed_at = Column(TIMESTAMP(timezone=True), nullable=True)
    contacts_synced = Column(Integer, nullable=False, default=0)
    invoices_synced = Column(Integer, nullable=False, default=0)
    error_message = Column(Text, nullable=True)
    error_details = Column(JSONB, nullable=True)
    triggered_by = Column(String(50), nullable=True)  # manual | oauth_connect | scheduled
    created_at = Column(TIMESTAMP(timezone=True), nullable=False, default=datetime.utcnow)
    updated_at = Column(TIMESTAMP(timezone=True), nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self) -> str:
        return f"<XeroSyncJob(id={self.id}, type={self.sync_type!r}, status={self.status!r})>"
