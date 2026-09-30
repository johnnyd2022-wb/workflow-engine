"""Planned production is separate from inventory allocations and live execution."""

import uuid

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    Date,
    DateTime,
    ForeignKeyConstraint,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID

from app.core.db.models.models import Base
from app.core.db.models.tenant_mixin import TenantScoped
from app.core.utils.time import utc_now


class PlanningWorkflowSetting(TenantScoped, Base):
    __tablename__ = "planning_workflow_settings"
    __table_args__ = (
        UniqueConstraint("org_id", "id", name="uq_planning_settings_org_id"),
        UniqueConstraint("org_id", "process_id", "source_output_id", name="uq_planning_settings_output"),
        ForeignKeyConstraint(
            ["org_id", "process_id"], ["processes.org_id", "processes.id"], name="fk_planning_settings_org_process"
        ),
        CheckConstraint(
            "batch_quantity > 0 AND batch_quantity <= 99999999999999.9999", name="ck_planning_settings_quantity"
        ),
        CheckConstraint("revision > 0", name="ck_planning_settings_revision"),
    )
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    process_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    source_output_id = Column(UUID(as_uuid=True), nullable=False)
    batch_quantity = Column(Numeric(18, 4), nullable=False)
    unit = Column(String(50), nullable=False)
    revision = Column(Integer, nullable=False, default=1)
    workflow_fingerprint = Column(String(64), nullable=False)
    snapshot = Column(JSONB, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)


class PlanningBatch(TenantScoped, Base):
    __tablename__ = "planning_batches"
    __table_args__ = (
        UniqueConstraint("org_id", "id", name="uq_planning_batches_org_id"),
        UniqueConstraint("org_id", "demand_id", "generation", "batch_number", name="uq_planning_batch_generation"),
        UniqueConstraint("execution_id", name="uq_planning_batch_execution"),
        ForeignKeyConstraint(
            ["org_id", "demand_id"],
            ["planning_demands.org_id", "planning_demands.id"],
            name="fk_planning_batch_org_demand",
        ),
        ForeignKeyConstraint(
            ["org_id", "process_id"], ["processes.org_id", "processes.id"], name="fk_planning_batch_org_process"
        ),
        ForeignKeyConstraint(
            ["org_id", "setting_id"],
            ["planning_workflow_settings.org_id", "planning_workflow_settings.id"],
            name="fk_planning_batch_org_setting",
        ),
        ForeignKeyConstraint(["org_id", "site_id"], ["sites.org_id", "sites.id"], name="fk_planning_batch_org_site"),
        ForeignKeyConstraint(
            ["org_id", "execution_id"], ["executions.org_id", "executions.id"], name="fk_planning_batch_org_execution"
        ),
        CheckConstraint("quantity > 0 AND quantity <= 99999999999999.9999", name="ck_planning_batch_quantity"),
        CheckConstraint("priority >= 0 AND priority <= 100", name="ck_planning_batch_priority"),
        CheckConstraint("revision > 0 AND generation > 0 AND batch_number > 0", name="ck_planning_batch_revision"),
        CheckConstraint("status IN ('blocked','planned','cancelled','started')", name="ck_planning_batch_status"),
        CheckConstraint(
            "theoretical_ready_date IS NULL OR theoretical_ready_date >= proposed_start_date",
            name="ck_planning_batch_dates",
        ),
        CheckConstraint("status != 'started' OR execution_id IS NOT NULL", name="ck_planning_batch_started"),
    )
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    demand_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    process_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    setting_id = Column(UUID(as_uuid=True), nullable=False)
    site_id = Column(UUID(as_uuid=True), nullable=True, index=True)
    source_output_id = Column(UUID(as_uuid=True), nullable=False)
    execution_id = Column(UUID(as_uuid=True), nullable=True)
    generation = Column(Integer, nullable=False)
    batch_number = Column(Integer, nullable=False)
    quantity = Column(Numeric(18, 4), nullable=False)
    unit = Column(String(50), nullable=False)
    priority = Column(Integer, nullable=False)
    pinned = Column(Boolean, nullable=False, default=False, server_default="false")
    status = Column(String(20), nullable=False, default="blocked", server_default="blocked")
    revision = Column(Integer, nullable=False, default=1)
    proposed_start_date = Column(Date, nullable=False, index=True)
    theoretical_ready_date = Column(Date, nullable=True)
    # Never populated from timing alone; trusted material/capacity stages come later.
    forecast_ready_date = Column(Date, nullable=True)
    snapshot = Column(JSONB, nullable=False)
    blockers = Column(JSONB, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)
