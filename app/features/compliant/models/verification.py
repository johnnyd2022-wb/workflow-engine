"""Food-safety verification visits and corrective actions (plan 2.2)."""

import uuid

from sqlalchemy import TIMESTAMP, Boolean, Column, Date, ForeignKey, ForeignKeyConstraint, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID

from app.core.db.models.models import Base
from app.core.utils.time import utc_now


class ComplianceVerification(Base):
    __tablename__ = "compliance_verifications"
    __table_args__ = (
        ForeignKeyConstraint(
            ["org_id", "food_registration_id"],
            ["food_registrations.org_id", "food_registrations.id"],
            name="fk_verification_food_registration",
            ondelete="RESTRICT",
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id = Column(UUID(as_uuid=True), ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False)
    food_registration_id = Column(UUID(as_uuid=True), nullable=True, index=True)
    programme = Column(String(10), nullable=False)
    verified_on = Column(Date, nullable=False)
    verifier_name = Column(String(255), nullable=False)
    verifier_agency = Column(String(255), nullable=True)
    report_reference = Column(String(255), nullable=True)
    outcome = Column(String(20), nullable=False)
    initial = Column(Boolean, nullable=False, default=False, server_default="false")
    attitude = Column(String(20), nullable=True)
    step = Column(Integer, nullable=False)
    next_due = Column(Date, nullable=True)
    notes = Column(Text, nullable=True)
    created_by_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(TIMESTAMP(timezone=True), nullable=False, default=utc_now)


class ComplianceVerificationAction(Base):
    __tablename__ = "compliance_verification_actions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id = Column(UUID(as_uuid=True), ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False)
    verification_id = Column(
        UUID(as_uuid=True), ForeignKey("compliance_verifications.id", ondelete="CASCADE"), nullable=False
    )
    description = Column(String(500), nullable=False)
    owner_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    owner_name = Column(String(255), nullable=True)
    due_on = Column(Date, nullable=False)
    status = Column(String(10), nullable=False, default="open", server_default="open")
    done_on = Column(Date, nullable=True)
    done_note = Column(String(500), nullable=True)
    done_by_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(TIMESTAMP(timezone=True), nullable=False, default=utc_now)
