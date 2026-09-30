"""Explicit food registrations and the sites/activities they cover."""

import uuid

from sqlalchemy import CheckConstraint, Column, Date, DateTime, ForeignKeyConstraint, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID

from app.core.db.models.models import Base
from app.core.db.models.tenant_mixin import TenantScoped
from app.core.utils.time import utc_now


class FoodRegistration(TenantScoped, Base):
    __tablename__ = "food_registrations"
    __table_args__ = (
        UniqueConstraint("org_id", "id", name="uq_food_registration_org_id"),
        UniqueConstraint("org_id", "reference", name="uq_food_registration_org_reference"),
        CheckConstraint("programme IN ('np1','np2','np3','fcp')", name="ck_food_registration_programme"),
        CheckConstraint("registered_as IN ('new','existing')", name="ck_food_registration_registered_as"),
        CheckConstraint("valid_until IS NULL OR valid_until >= registered_on", name="ck_food_registration_dates"),
    )
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    reference = Column(String(100), nullable=False)
    name = Column(String(150), nullable=False)
    programme = Column(String(10), nullable=False)
    registered_on = Column(Date, nullable=False)
    registered_as = Column(String(10), nullable=False)
    valid_until = Column(Date)
    evidence_reference = Column(String(500), nullable=False)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)


class FoodRegistrationSite(TenantScoped, Base):
    __tablename__ = "food_registration_sites"
    __table_args__ = (
        ForeignKeyConstraint(
            ["org_id", "registration_id"],
            ["food_registrations.org_id", "food_registrations.id"],
            name="fk_food_registration_scope_registration",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["org_id", "site_id"],
            ["sites.org_id", "sites.id"],
            name="fk_food_registration_scope_site",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("org_id", "registration_id", "site_id", "activity", name="uq_food_registration_scope"),
        CheckConstraint("activity IN ('manufacturing','storage','selling')", name="ck_food_registration_activity"),
    )
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    registration_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    site_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    activity = Column(String(20), nullable=False)
    evidence_reference = Column(String(500), nullable=False)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)
