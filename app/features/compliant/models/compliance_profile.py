"""Organisation-level enrolment and applicability data for Compliant."""

import uuid

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID

from app.core.db.models.models import Base
from app.core.utils.time import utc_now


class ComplianceProfile(Base):
    __tablename__ = "compliance_profiles"
    __table_args__ = (
        UniqueConstraint("org_id", name="uq_compliance_profiles_org"),
        Index("ix_compliance_profiles_org_enabled", "org_id", "enabled"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id = Column(UUID(as_uuid=True), ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False)
    enabled = Column(Boolean, nullable=False, default=False)
    industry_module = Column(String(80), nullable=False, default="nz_alcohol")
    council_name = Column(String(255), nullable=True)
    trade_waste_consent_reference = Column(String(255), nullable=True)
    # Product classification, framework applicability and local thresholds are explicit
    # configuration rather than hidden in check code.
    settings = Column(JSONB, nullable=False, default=dict)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)
