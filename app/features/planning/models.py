"""Tenant-scoped demand records; starting execution is a separate operation."""

import uuid

from sqlalchemy import CheckConstraint, Column, Date, DateTime, Integer, Numeric, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID

from app.core.db.models.models import Base
from app.core.db.models.tenant_mixin import TenantScoped
from app.core.utils.time import utc_now


class PlanningDemand(TenantScoped, Base):
    __tablename__ = "planning_demands"
    __table_args__ = (
        UniqueConstraint("org_id", "id", name="uq_planning_demands_org_id"),
        CheckConstraint("quantity > 0 AND quantity <= 99999999999999.9999", name="ck_planning_demand_quantity"),
        CheckConstraint("priority >= 0 AND priority <= 100", name="ck_planning_demand_priority"),
        CheckConstraint("status IN ('open', 'cancelled', 'fulfilled')", name="ck_planning_demand_status"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    reference = Column(String(200), nullable=False)
    # Outputs are JSONB definitions with stable UUIDs; there is no output table FK.
    source_output_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    quantity = Column(Numeric(18, 4), nullable=False)
    unit = Column(String(50), nullable=False)
    due_date = Column(Date, nullable=False, index=True)
    priority = Column(Integer, nullable=False, default=0, server_default="0")
    status = Column(String(20), nullable=False, default="open", server_default="open")
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)
