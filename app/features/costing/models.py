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
    Date,
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

# purchase_lines has a foreign key to xero_accounts: register that table in the metadata
# wherever these models are imported, not only where the CRM slice happens to be loaded.
from app.features.crm.models.xero_account import XeroAccount  # noqa: E402,F401

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
    # 8.1b: purchases are fetched from start_date on, incrementally from purchases_cursor.
    start_date = Column(Date, nullable=True)
    purchases_cursor = Column(DateTime(timezone=True), nullable=True)
    purchases_tenant_id = Column(String(100), nullable=True)
    base_currency = Column(String(3), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)


class PurchaseDocument(TenantScoped, Base):
    """A purchase as the accounting system holds it (8.1b: Xero spend / receive money)."""

    __tablename__ = "purchase_documents"
    __table_args__ = (
        UniqueConstraint("org_id", "id", name="uq_purchase_documents_org_id"),
        UniqueConstraint("org_id", "source", "external_id", name="uq_purchase_documents_external"),
        CheckConstraint("source IN ('xero_bank')", name="ck_purchase_documents_source"),
        CheckConstraint("kind IN ('spend','refund')", name="ck_purchase_documents_kind"),
        CheckConstraint("status IN ('active','voided')", name="ck_purchase_documents_status"),
        CheckConstraint("fx_status IN ('ok','needs_rate')", name="ck_purchase_documents_fx"),
        Index("ix_purchase_documents_org_date", "org_id", "document_date"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source = Column(String(20), nullable=False)
    external_id = Column(String(100), nullable=False)
    xero_tenant_id = Column(String(100), nullable=True)
    kind = Column(String(10), nullable=False)
    payee_name = Column(String(255), nullable=True)
    xero_contact_id = Column(String(100), nullable=True)
    document_date = Column(Date, nullable=True)
    reference = Column(String(255), nullable=True)
    currency_code = Column(String(3), nullable=True)
    currency_rate = Column(Numeric(18, 8), nullable=True)
    fx_status = Column(String(12), nullable=False, default="ok", server_default="ok")
    status = Column(String(10), nullable=False)
    total_ex_tax = Column(Numeric(18, 4), nullable=True)
    total_tax = Column(Numeric(18, 4), nullable=True)
    bank_account_name = Column(String(255), nullable=True)
    is_reconciled = Column(Boolean, nullable=True)
    external_updated_at = Column(DateTime(timezone=True), nullable=True)
    last_synced_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)


class PurchaseLine(TenantScoped, Base):
    """One line of a purchase, in base currency ex GST; refunds are negative."""

    __tablename__ = "purchase_lines"
    __table_args__ = (
        UniqueConstraint("org_id", "id", name="uq_purchase_lines_org_id"),
        ForeignKeyConstraint(
            ["org_id", "document_id"],
            ["purchase_documents.org_id", "purchase_documents.id"],
            name="fk_purchase_lines_document",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["org_id", "account_id"],
            ["xero_accounts.org_id", "xero_accounts.id"],
            name="fk_purchase_lines_account",
        ),
        CheckConstraint("treatment IN ('stock','not_stock','duty','overhead')", name="ck_purchase_lines_treatment"),
        CheckConstraint(
            "state IN ('open','partly_recorded','recorded','skipped','not_stock')", name="ck_purchase_lines_state"
        ),
        CheckConstraint(
            "review_reason IS NULL OR review_reason IN ('amount_changed','recoded','deleted_in_xero')",
            name="ck_purchase_lines_review",
        ),
        Index(
            "uq_purchase_lines_live_key",
            "org_id",
            "document_id",
            "line_key",
            unique=True,
            postgresql_where=sa.text("superseded_at IS NULL"),
        ),
        Index("ix_purchase_lines_org_account", "org_id", "account_id"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    document_id = Column(UUID(as_uuid=True), nullable=False)
    account_id = Column(UUID(as_uuid=True), nullable=False)
    line_key = Column(String(120), nullable=False)
    position = Column(Integer, nullable=False)
    fingerprint = Column(String(64), nullable=False)
    description = Column(String(4000), nullable=True)
    item_code = Column(String(100), nullable=True)
    quantity = Column(Numeric(18, 4), nullable=True)
    source_unit_amount = Column(Numeric(18, 6), nullable=True)  # as Xero sent it
    account_code = Column(String(50), nullable=True)
    account_name = Column(String(255), nullable=True)
    amount_ex_tax = Column(Numeric(18, 4), nullable=True)
    tax_amount = Column(Numeric(18, 4), nullable=True)
    treatment = Column(String(20), nullable=False)
    superseded_at = Column(DateTime(timezone=True), nullable=True)
    # 8.1c-1: what has been done with the line
    state = Column(String(20), nullable=False, default="open", server_default="open")
    not_stock_amount = Column(Numeric(18, 4), nullable=False, default=0, server_default="0")
    review_reason = Column(String(20), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)


class PurchaseAllocation(TenantScoped, Base):
    """A purchase line paying for (part of) a lot's inflow; a negative one is a refund that
    lowers the lot's cost. Spec "8.1c-1 build contract"."""

    __tablename__ = "purchase_allocations"
    __table_args__ = (
        UniqueConstraint("org_id", "id", name="uq_purchase_allocations_org_id"),
        UniqueConstraint("org_id", "purchase_line_id", "inventory_item_id", name="uq_purchase_allocations_line_lot"),
        ForeignKeyConstraint(
            ["org_id", "purchase_line_id"],
            ["purchase_lines.org_id", "purchase_lines.id"],
            name="fk_purchase_allocations_line",
        ),
        ForeignKeyConstraint(
            ["org_id", "inventory_item_id"],
            ["inventory_items.org_id", "inventory_items.id"],
            name="fk_purchase_allocations_item",
        ),
        ForeignKeyConstraint(
            ["org_id", "cost_flow_id"],
            ["cost_flows.org_id", "cost_flows.id"],
            name="fk_purchase_allocations_flow",
        ),
        CheckConstraint("status IN ('active','orphaned')", name="ck_purchase_allocations_status"),
        CheckConstraint(
            "(amount < 0 AND cost_flow_id IS NULL AND quantity = 0)"
            " OR (amount >= 0 AND cost_flow_id IS NOT NULL AND quantity > 0)",
            name="ck_purchase_allocations_shape",
        ),
        Index("ix_purchase_allocations_item", "org_id", "inventory_item_id"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    purchase_line_id = Column(UUID(as_uuid=True), nullable=False)
    inventory_item_id = Column(UUID(as_uuid=True), nullable=False)
    cost_flow_id = Column(UUID(as_uuid=True), nullable=True)
    amount = Column(Numeric(18, 4), nullable=False)
    quantity = Column(Numeric(18, 4), nullable=False)
    status = Column(String(10), nullable=False, default="active", server_default="active")
    orphaned_by = Column(String(10), nullable=True)  # void | gone | amount: why it was orphaned
    created_by_user_id = Column(UUID(as_uuid=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)
