"""Tenant-scoped manual compliance inputs, attestations and evidence references."""

import uuid

from sqlalchemy import Column, Date, DateTime, ForeignKey, Index, Numeric, String
from sqlalchemy.dialects.postgresql import JSONB, UUID

from app.core.db.models.models import Base
from app.core.utils.time import utc_now


class ComplianceRecord(Base):
    __tablename__ = "compliance_records"
    __table_args__ = (
        Index("ix_compliance_records_org_framework", "org_id", "framework_slug"),
        Index("ix_compliance_records_org_control_due", "org_id", "control_id", "due_date"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id = Column(UUID(as_uuid=True), ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False)
    framework_slug = Column(String(80), nullable=False)
    control_id = Column(String(160), nullable=False)
    record_type = Column(String(40), nullable=False)  # attestation | reading | lodgement | competency | incident
    status = Column(String(32), nullable=False, default="complete")  # complete | failed | open | superseded
    title = Column(String(255), nullable=False)
    period_start = Column(Date, nullable=True)
    period_end = Column(Date, nullable=True)
    due_date = Column(Date, nullable=True)
    measured_value = Column(Numeric(18, 4), nullable=True)
    limit_value = Column(Numeric(18, 4), nullable=True)
    owner_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    evidence_reference = Column(String(1024), nullable=True)
    # May contain execution_evidence IDs or core entity IDs; references remain in their
    # source system and retain its integrity guarantees.
    source_refs = Column(JSONB, nullable=False, default=list)
    details = Column(JSONB, nullable=False, default=dict)
    created_by_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)
