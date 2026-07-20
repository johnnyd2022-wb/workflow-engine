"""CRMTask — an actionable task optionally linked to a CRM contact."""

import uuid

from sqlalchemy import TIMESTAMP, Column, Date, ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import UUID

from app.core.db.models.models import Base
from app.core.utils.time import utc_now


class CRMTask(Base):
    __tablename__ = "crm_tasks"
    __table_args__ = (
        Index("ix_crm_tasks_org_due_date", "org_id", "due_date"),
        Index("ix_crm_tasks_org_assigned_status", "org_id", "assigned_to_user_id", "status"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id = Column(UUID(as_uuid=True), ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False, index=True)
    contact_id = Column(
        UUID(as_uuid=True), ForeignKey("xero_contacts.id", ondelete="SET NULL"), nullable=True, index=True
    )
    title = Column(String(500), nullable=False)
    description = Column(Text, nullable=True)
    due_date = Column(Date, nullable=True)
    status = Column(String(50), nullable=False, default="pending")  # pending | in_progress | completed | cancelled
    priority = Column(String(20), nullable=False, default="medium")  # low | medium | high
    assigned_to_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_by_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    completed_at = Column(TIMESTAMP(timezone=True), nullable=True)
    created_at = Column(TIMESTAMP(timezone=True), nullable=False, default=utc_now)
    updated_at = Column(TIMESTAMP(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)

    def __repr__(self) -> str:
        return f"<CRMTask(id={self.id}, title={self.title!r}, status={self.status!r})>"
