"""Liquor licensing registers (plan 2.5)."""

import uuid

from sqlalchemy import TIMESTAMP, Boolean, Column, Date, ForeignKey, ForeignKeyConstraint, String, Text, Time
from sqlalchemy.dialects.postgresql import JSONB, UUID

from app.core.db.models.models import Base
from app.core.utils.time import utc_now


class LiquorLicence(Base):
    __tablename__ = "liquor_licences"
    __table_args__ = (
        ForeignKeyConstraint(
            ["org_id", "site_id"], ["sites.org_id", "sites.id"], name="fk_liquor_licence_site", ondelete="RESTRICT"
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id = Column(UUID(as_uuid=True), ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False)
    site_id = Column(UUID(as_uuid=True), nullable=True, index=True)
    kind = Column(String(10), nullable=False)
    licence_number = Column(String(100), nullable=True)
    issuing_dlc = Column(String(255), nullable=True)
    premises = Column(String(500), nullable=True)
    endorsements = Column(JSONB, nullable=False, default=list, server_default="[]")
    issued_on = Column(Date, nullable=True)
    expires_on = Column(Date, nullable=True)
    sale_hours = Column(String(255), nullable=True)
    delivery_hours_start = Column(Time, nullable=True)
    delivery_hours_end = Column(Time, nullable=True)
    conditions = Column(Text, nullable=True)
    annual_fee_due_on = Column(Date, nullable=True)
    renewal_lodged_on = Column(Date, nullable=True)
    event_name = Column(String(255), nullable=True)
    event_starts_on = Column(Date, nullable=True)
    event_ends_on = Column(Date, nullable=True)
    manager_on_duty = Column(String(255), nullable=True)
    status = Column(String(20), nullable=False, default="current", server_default="current")
    created_by_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(TIMESTAMP(timezone=True), nullable=False, default=utc_now)
    updated_at = Column(TIMESTAMP(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)


class ManagerCertificate(Base):
    __tablename__ = "manager_certificates"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id = Column(UUID(as_uuid=True), ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    holder_name = Column(String(255), nullable=False)
    certificate_number = Column(String(100), nullable=False)
    issuing_dlc = Column(String(255), nullable=True)
    issued_on = Column(Date, nullable=True)
    expires_on = Column(Date, nullable=False)
    renewal_lodged_on = Column(Date, nullable=True)
    active = Column(Boolean, nullable=False, default=True, server_default="true")
    created_at = Column(TIMESTAMP(timezone=True), nullable=False, default=utc_now)
    updated_at = Column(TIMESTAMP(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)


class LicensingLogEntry(Base):
    __tablename__ = "licensing_log_entries"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id = Column(UUID(as_uuid=True), ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False)
    kind = Column(String(30), nullable=False)
    occurred_at = Column(TIMESTAMP(timezone=True), nullable=False)
    location = Column(String(255), nullable=True)
    description = Column(Text, nullable=False)
    action_taken = Column(Text, nullable=True)
    staff_name = Column(String(255), nullable=True)
    reference = Column(String(255), nullable=True)
    created_by_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(TIMESTAMP(timezone=True), nullable=False, default=utc_now)
