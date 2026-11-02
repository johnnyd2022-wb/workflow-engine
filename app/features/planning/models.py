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
        CheckConstraint("source IN ('manual','contract','forecast')", name="ck_planning_demand_source"),
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
    # GL-P07 B3: typed in, a confirmed contract order line (`source_ref` is its id), or an
    # accepted forecast suggestion.
    source = Column(String(20), nullable=False, default="manual", server_default="manual")
    source_ref = Column(String(100), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)


class PlanningStockTarget(TenantScoped, Base):
    """Weeks of cover to keep of a product (GL-P07 B3); the forecast turns it into demand."""

    __tablename__ = "planning_stock_targets"
    __table_args__ = (
        UniqueConstraint("org_id", "source_output_id", name="uq_planning_stock_target_output"),
        CheckConstraint("weeks_of_cover > 0 AND weeks_of_cover <= 104", name="ck_planning_stock_target_weeks"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source_output_id = Column(UUID(as_uuid=True), nullable=False)
    weeks_of_cover = Column(Numeric(6, 2), nullable=False)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)
