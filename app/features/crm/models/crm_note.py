"""CRMNote — a freeform note attached to a CRM contact."""

import uuid
from datetime import datetime

from sqlalchemy import TIMESTAMP, Column, ForeignKey, Text
from sqlalchemy.dialects.postgresql import UUID

from app.core.db.models.models import Base


class CRMNote(Base):
    __tablename__ = "crm_notes"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id = Column(UUID(as_uuid=True), ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False, index=True)
    contact_id = Column(
        UUID(as_uuid=True), ForeignKey("xero_contacts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    content = Column(Text, nullable=False)
    created_by_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(TIMESTAMP(timezone=True), nullable=False, default=datetime.utcnow)
    updated_at = Column(TIMESTAMP(timezone=True), nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self) -> str:
        return f"<CRMNote(id={self.id}, contact_id={self.contact_id})>"
