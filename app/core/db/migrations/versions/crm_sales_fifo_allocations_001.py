"""Persist the exact labelled inventory batches allocated to Xero sales lines.

Revision ID: crm_sales_fifo_allocations_001
Revises: core_task_archive_prefs_001
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "crm_sales_fifo_allocations_001"
down_revision: str | None = "core_task_archive_prefs_001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "crm_sales_fifo_allocations",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("xero_invoice_id", sa.String(length=100), nullable=False),
        sa.Column("xero_line_key", sa.String(length=160), nullable=False),
        sa.Column("inventory_item_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("product_mapping_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("product_name", sa.String(length=500), nullable=False),
        sa.Column("quantity", sa.Numeric(18, 4), nullable=False),
        sa.Column("unit", sa.String(length=50), nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["inventory_item_id"], ["inventory_items.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["org_id"], ["organisations.id"]),
        sa.ForeignKeyConstraint(["product_mapping_id"], ["product_mappings.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "org_id",
            "xero_invoice_id",
            "xero_line_key",
            "inventory_item_id",
            name="uq_crm_sales_fifo_allocation_line_item",
        ),
    )
    op.create_index("ix_crm_sales_fifo_allocations_org_id", "crm_sales_fifo_allocations", ["org_id"])
    op.create_index("ix_crm_sales_fifo_allocations_xero_invoice", "crm_sales_fifo_allocations", ["xero_invoice_id"])


def downgrade() -> None:
    op.drop_index("ix_crm_sales_fifo_allocations_xero_invoice", table_name="crm_sales_fifo_allocations")
    op.drop_index("ix_crm_sales_fifo_allocations_org_id", table_name="crm_sales_fifo_allocations")
    op.drop_table("crm_sales_fifo_allocations")
