"""A PDF or image attached to a compliance record (NP3 attestations and log entries)."""

import uuid

from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, String
from sqlalchemy.dialects.postgresql import UUID

from app.core.db.models.models import Base
from app.core.utils.time import utc_now


class ComplianceRecordFile(Base):
    __tablename__ = "compliance_record_files"
    __table_args__ = (Index("ix_compliance_record_files_org_record", "org_id", "record_id"),)

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id = Column(UUID(as_uuid=True), ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False)
    record_id = Column(UUID(as_uuid=True), ForeignKey("compliance_records.id", ondelete="CASCADE"), nullable=False)
    file_name = Column(String(512), nullable=False)  # the uploader's name, for display only
    storage_name = Column(String(80), nullable=False)  # uuid.ext under <root>/<org>/np3-<record>/
    mime_type = Column(String(128), nullable=False)
    file_size = Column(Integer, nullable=False)
    checksum_sha256 = Column(String(64), nullable=False)
    uploaded_by_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
