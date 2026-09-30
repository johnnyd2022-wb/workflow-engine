"""Site resource capacity settings are planning observations, never reservations."""

import uuid

from sqlalchemy import CheckConstraint, Column, DateTime, ForeignKeyConstraint, Integer, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID

from app.core.db.models.models import Base
from app.core.db.models.tenant_mixin import TenantScoped
from app.core.utils.time import utc_now


class PlanningCapacitySetting(TenantScoped, Base):
    __tablename__ = "planning_capacity_settings"
    __table_args__ = (
        UniqueConstraint("org_id", "site_id", name="uq_planning_capacity_org_site"),
        ForeignKeyConstraint(["org_id", "site_id"], ["sites.org_id", "sites.id"], name="fk_planning_capacity_site"),
        CheckConstraint("revision > 0", name="ck_planning_capacity_revision"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    site_id = Column(UUID(as_uuid=True), nullable=False)
    revision = Column(Integer, nullable=False, default=1)
    config = Column(JSONB, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)
