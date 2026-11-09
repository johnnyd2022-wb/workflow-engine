"""Tenant-scoped demand records; starting execution is a separate operation."""

import uuid

from sqlalchemy import (
    CheckConstraint,
    Column,
    Date,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    text,
)
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
        CheckConstraint("source IN ('manual', 'contract', 'forecast')", name="ck_planning_demand_source"),
        CheckConstraint(
            "(source = 'manual' AND source_ref IS NULL) OR (source <> 'manual' AND source_ref IS NOT NULL)",
            name="ck_planning_demand_source_ref",
        ),
        Index(
            "uq_planning_demand_source_ref",
            "org_id",
            "source_ref",
            unique=True,
            postgresql_where=text("source_ref IS NOT NULL"),
        ),
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
    # manual: typed in. contract: mirrors a confirmed contract order line (source_ref = line id).
    # forecast: a stock-target suggestion someone planned (source_ref = "forecast:<retry key>").
    source = Column(String(20), nullable=False, default="manual", server_default="manual")
    source_ref = Column(String(160), nullable=True)
    # Why a synced demand was left as it is, e.g. its order changed after a batch started.
    source_note = Column(String(300), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)


class PlanningStockTarget(TenantScoped, Base):
    """Weeks of cover to keep of an output; a forecast turns it into a suggested batch (GL-P07 B3)."""

    __tablename__ = "planning_stock_targets"
    __table_args__ = (
        CheckConstraint("weeks_of_cover > 0 AND weeks_of_cover <= 104", name="ck_planning_stock_target_weeks"),
        ForeignKeyConstraint(
            ["org_id", "site_id"], ["sites.org_id", "sites.id"], name="fk_planning_stock_target_org_site"
        ),
        Index(
            "uq_planning_stock_target_output_site",
            "org_id",
            "source_output_id",
            text("coalesce(site_id, '00000000-0000-0000-0000-000000000000'::uuid)"),
            unique=True,
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source_output_id = Column(UUID(as_uuid=True), nullable=False)
    site_id = Column(UUID(as_uuid=True), nullable=True)
    weeks_of_cover = Column(Numeric(6, 2), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)
