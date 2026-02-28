"""Execution evidence model for uploaded files (images, PDFs)."""

import uuid
from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import JSONB, UUID

from app.core.db.models.models import Base


class ExecutionEvidence(Base):
    """Stores metadata for evidence files linked to an execution (and optionally a step)."""

    __tablename__ = "execution_evidence"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id = Column(UUID(as_uuid=True), ForeignKey("organisations.id"), nullable=False, index=True)
    execution_id = Column(UUID(as_uuid=True), ForeignKey("executions.id"), nullable=False, index=True)
    step_id = Column(UUID(as_uuid=True), ForeignKey("steps.id"), nullable=True, index=True)
    file_name = Column(String(512), nullable=False)  # Original client filename (for display)
    storage_path = Column(String(1024), nullable=False)
    mime_type = Column(String(128), nullable=False)
    file_size = Column(Integer, nullable=False)
    checksum_sha256 = Column(String(64), nullable=False)
    uploaded_by = Column(String(512), nullable=True)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)
    extra_data = Column(JSONB, nullable=True)
