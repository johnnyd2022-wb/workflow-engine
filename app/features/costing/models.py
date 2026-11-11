"""Costing facts (live-cogs 8.1a; spec .agents/specs/live-cogs.md, "Data model").

Facts only: every cost is computed on read from these rows (``engine.py``). Nothing here is
derived from anything else here.
"""

from __future__ import annotations

import uuid

import sqlalchemy as sa
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID

from app.core.db.models.models import Base
from app.core.db.models.tenant_mixin import TenantScoped
from app.core.utils.time import utc_now

IN_KINDS = ("created", "added", "produced", "transfer_in", "reconciled_in")
OUT_KINDS = ("consumed",)
DIRECT_KINDS = ("created", "added")  # inflows a price fact can pay for


class CostFlow(TenantScoped, Base):
    """Every quantity into or out of a lot that cost cares about, in the lot's unit."""

    __tablename__ = "cost_flows"
    __table_args__ = (
        UniqueConstraint("org_id", "id", name="uq_cost_flows_org_id"),
        UniqueConstraint("org_id", "source_key", name="uq_cost_flows_source_key"),
        ForeignKeyConstraint(
            ["org_id", "inventory_item_id"],
            ["inventory_items.org_id", "inventory_items.id"],
            name="fk_cost_flows_item",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["org_id", "execution_id"],
            ["executions.org_id", "executions.id"],
            name="fk_cost_flows_execution",
            ondelete="CASCADE",
        ),
        # the step is this org's, and a step of that very execution
        ForeignKeyConstraint(
            ["org_id", "execution_id", "execution_step_id"],
            ["execution_steps.org_id", "execution_steps.execution_id", "execution_steps.id"],
            name="fk_cost_flows_execution_step",
            ondelete="CASCADE",
        ),
        CheckConstraint("quantity > 0", name="ck_cost_flows_quantity_positive"),
        CheckConstraint(
            "execution_step_id IS NULL OR execution_id IS NOT NULL", name="ck_cost_flows_step_needs_execution"
        ),
        CheckConstraint(
            "(direction = 'in' AND kind IN ('created','added','produced','transfer_in','reconciled_in'))"
            " OR (direction = 'out' AND kind = 'consumed')",
            name="ck_cost_flows_kind",
        ),
        CheckConstraint(
            "kind NOT IN ('produced','reconciled_in','consumed')"
            " OR (execution_id IS NOT NULL AND execution_step_id IS NOT NULL AND step_number IS NOT NULL)",
            name="ck_cost_flows_execution_kinds",
        ),
        Index("ix_cost_flows_item_direction", "org_id", "inventory_item_id", "direction"),
        Index("ix_cost_flows_execution_step", "org_id", "execution_id", "step_number"),
        Index("ix_cost_flows_execution_step_id", "execution_step_id"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    inventory_item_id = Column(UUID(as_uuid=True), nullable=False)
    direction = Column(String(3), nullable=False)
    kind = Column(String(20), nullable=False)
    quantity = Column(Numeric(18, 4), nullable=False)
    execution_id = Column(UUID(as_uuid=True), nullable=True)
    execution_step_id = Column(UUID(as_uuid=True), nullable=True)
    step_number = Column(Integer, nullable=True)
    source_output_id = Column(UUID(as_uuid=True), nullable=True)
    source_key = Column(String(200), nullable=False)
    write_reason = Column(String(50), nullable=False)
    reconstructed = Column(Boolean, nullable=False, default=False, server_default=sa.false())
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)


class LotCostEntry(TenantScoped, Base):
    """A cost with no purchase behind it: a typed price, or 'free'."""

    __tablename__ = "lot_cost_entries"
    __table_args__ = (
        UniqueConstraint("org_id", "id", name="uq_lot_cost_entries_org_id"),
        ForeignKeyConstraint(
            ["org_id", "inventory_item_id"],
            ["inventory_items.org_id", "inventory_items.id"],
            name="fk_lot_cost_entries_item",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["org_id", "cost_flow_id"],
            ["cost_flows.org_id", "cost_flows.id"],
            name="fk_lot_cost_entries_flow",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["org_id", "created_by_user_id"],
            ["users.org_id", "users.id"],
            name="fk_lot_cost_entries_creator",
            ondelete="SET NULL (created_by_user_id)",
        ),
        CheckConstraint("kind IN ('manual','free')", name="ck_lot_cost_entries_kind"),
        CheckConstraint("amount >= 0", name="ck_lot_cost_entries_amount"),
        CheckConstraint("quantity > 0", name="ck_lot_cost_entries_quantity"),
        CheckConstraint("kind <> 'free' OR amount = 0", name="ck_lot_cost_entries_free_zero"),
        Index(
            "uq_lot_cost_entries_active_flow",
            "org_id",
            "inventory_item_id",
            "cost_flow_id",
            unique=True,
            postgresql_where=sa.text("is_active AND cost_flow_id IS NOT NULL"),
        ),
        Index(
            "uq_lot_cost_entries_active_whole_lot",
            "org_id",
            "inventory_item_id",
            unique=True,
            postgresql_where=sa.text("is_active AND cost_flow_id IS NULL"),
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    inventory_item_id = Column(UUID(as_uuid=True), nullable=False)
    cost_flow_id = Column(UUID(as_uuid=True), nullable=True)
    kind = Column(String(10), nullable=False)
    amount = Column(Numeric(18, 4), nullable=False)
    quantity = Column(Numeric(18, 4), nullable=False)
    note = Column(String(500), nullable=True)
    is_active = Column(Boolean, nullable=False, default=True, server_default=sa.true())
    created_by_user_id = Column(UUID(as_uuid=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    deactivated_at = Column(DateTime(timezone=True), nullable=True)


class CostingSettings(TenantScoped, Base):
    """One row per org; absent means the defaults."""

    __tablename__ = "costing_settings"
    __table_args__ = (
        UniqueConstraint("org_id", "id", name="uq_costing_settings_org_id"),
        UniqueConstraint("org_id", name="uq_costing_settings_org"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    use_last_known_price = Column(Boolean, nullable=False, default=True, server_default=sa.true())
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)
