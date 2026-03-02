"""Process step document (SOP) model: file-based or inline markdown."""

import uuid
from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID

from app.core.db.models.models import Base


class ProcessStepDocument(Base):
    """Stores SOP documentation for a process step: uploaded file or inline markdown."""

    __tablename__ = "process_step_documents"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id = Column(UUID(as_uuid=True), ForeignKey("organisations.id"), nullable=False, index=True)
    process_id = Column(UUID(as_uuid=True), ForeignKey("processes.id"), nullable=False, index=True)
    step_id = Column(UUID(as_uuid=True), ForeignKey("steps.id"), nullable=False, index=True)
    title = Column(String(512), nullable=False)
    storage_path = Column(String(1024), nullable=True)  # relative path for file-based SOP
    content_markdown = Column(Text, nullable=True)  # inline SOP
    mime_type = Column(String(128), nullable=True)
    file_size = Column(Integer, nullable=True)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    deleted_at = Column(DateTime(timezone=True), nullable=True)  # soft delete
