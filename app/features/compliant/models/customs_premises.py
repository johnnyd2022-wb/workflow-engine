"""Module-owned Customs licences and dated coverage of physical stock areas."""

import uuid

from sqlalchemy import (
    CheckConstraint,
    Column,
    Date,
    DateTime,
    ForeignKeyConstraint,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID, ExcludeConstraint

from app.core.db.models.models import Base
from app.core.db.models.tenant_mixin import TenantScoped
from app.core.utils.time import utc_now


class CustomsLicence(TenantScoped, Base):
    __tablename__ = "customs_licences"
    __table_args__ = (
        UniqueConstraint("org_id", "id", name="uq_customs_licence_org_id"),
        UniqueConstraint("org_id", "number", name="uq_customs_licence_org_number"),
        CheckConstraint("kind IN ('lma','oss','duty_free','export')", name="ck_customs_licence_kind"),
        CheckConstraint("valid_until IS NULL OR valid_until >= valid_from", name="ck_customs_licence_dates"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    number = Column(String(100), nullable=False)
    name = Column(String(150), nullable=False)
    kind = Column(String(20), nullable=False)
    legal_entity_reference = Column(String(100), nullable=False)
    valid_from = Column(Date, nullable=False)
    valid_until = Column(Date)
    evidence_reference = Column(String(500), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)


class CustomsCoverage(TenantScoped, Base):
    """Null location means a site's main area, never all its named locations."""

    __tablename__ = "customs_coverage"
    __table_args__ = (
        ForeignKeyConstraint(
            ["org_id", "licence_id"],
            ["customs_licences.org_id", "customs_licences.id"],
            name="fk_customs_coverage_licence",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["org_id", "site_id"], ["sites.org_id", "sites.id"], name="fk_customs_coverage_site", ondelete="RESTRICT"
        ),
        ForeignKeyConstraint(
            ["org_id", "site_id", "location_id"],
            ["stock_locations.org_id", "stock_locations.site_id", "stock_locations.id"],
            name="fk_customs_coverage_location",
            ondelete="RESTRICT",
        ),
        CheckConstraint("valid_until IS NULL OR valid_until >= valid_from", name="ck_customs_coverage_dates"),
        ExcludeConstraint(
            ("org_id", "="),
            ("site_id", "="),
            (func.daterange(text("valid_from"), text("valid_until"), "[]"), "&&"),
            where=text("location_id IS NULL"),
            name="ex_customs_coverage_main_dates",
        ),
        ExcludeConstraint(
            ("org_id", "="),
            ("site_id", "="),
            ("location_id", "="),
            (func.daterange(text("valid_from"), text("valid_until"), "[]"), "&&"),
            where=text("location_id IS NOT NULL"),
            name="ex_customs_coverage_location_dates",
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    licence_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    site_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    location_id = Column(UUID(as_uuid=True), nullable=True)
    valid_from = Column(Date, nullable=False)
    valid_until = Column(Date)
    evidence_reference = Column(String(500), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
