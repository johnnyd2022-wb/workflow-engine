"""Physical customer returns, apart from credit notes and duty (GL-P01b).

`sales_returns`: what came back, how much, in what condition, and which lot it went into
(or the hold placed on it). Downgrade refuses while any return exists.

Revision ID: sales_returns_001
Revises: xero_credit_notes_001
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import UUID

revision = "sales_returns_001"
down_revision = "xero_credit_notes_001"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "sales_returns",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("org_id", UUID(as_uuid=True), sa.ForeignKey("organisations.id"), nullable=False),
        sa.Column("credit_note_line_id", UUID(as_uuid=True), nullable=True),
        sa.Column("allocation_id", UUID(as_uuid=True), nullable=True),
        sa.Column("xero_invoice_id", sa.String(100), nullable=True),
        sa.Column("product_name", sa.String(500), nullable=False),
        sa.Column("quantity", sa.Numeric(18, 4), nullable=False),
        sa.Column("unit", sa.String(50), nullable=False),
        sa.Column("condition", sa.String(20), nullable=False),
        sa.Column("received_on", sa.Date(), nullable=False),
        sa.Column("original_lot_id", UUID(as_uuid=True), nullable=True),
        sa.Column("resulting_lot_id", UUID(as_uuid=True), nullable=True),
        sa.Column("site_id", UUID(as_uuid=True), nullable=True),
        sa.Column("location_id", UUID(as_uuid=True), nullable=True),
        sa.Column(
            "wastage_id", UUID(as_uuid=True), sa.ForeignKey("inventory_wastage.id", ondelete="RESTRICT"), nullable=True
        ),
        sa.Column(
            "contact_id", UUID(as_uuid=True), sa.ForeignKey("xero_contacts.id", ondelete="SET NULL"), nullable=True
        ),
        sa.Column("hold_id", UUID(as_uuid=True), sa.ForeignKey("lot_holds.id", ondelete="RESTRICT"), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("recorded_by", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("org_id", "id", name="uq_sales_returns_org_id"),
        sa.ForeignKeyConstraint(
            ["org_id", "credit_note_line_id"],
            ["xero_credit_note_lines.org_id", "xero_credit_note_lines.id"],
            name="fk_sales_return_org_credit_line",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["org_id", "original_lot_id"],
            ["inventory_items.org_id", "inventory_items.id"],
            name="fk_sales_return_org_original_lot",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["org_id", "resulting_lot_id"],
            ["inventory_items.org_id", "inventory_items.id"],
            name="fk_sales_return_org_resulting_lot",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["org_id", "location_id"],
            ["stock_locations.org_id", "stock_locations.id"],
            name="fk_sales_return_org_location",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["org_id", "site_id"], ["sites.org_id", "sites.id"], name="fk_sales_return_org_site", ondelete="RESTRICT"
        ),
        sa.CheckConstraint("quantity > 0", name="ck_sales_return_quantity"),
        sa.CheckConstraint("condition IN ('resaleable', 'damaged', 'destroyed')", name="ck_sales_return_condition"),
        sa.CheckConstraint(
            "resulting_lot_id IS NOT NULL AND ((condition = 'destroyed') = (wastage_id IS NOT NULL))",
            name="ck_sales_return_stock_matches_condition",
        ),
    )
    op.create_index("ix_sales_returns_org_id", "sales_returns", ["org_id"])
    op.create_index("ix_sales_returns_credit_note_line_id", "sales_returns", ["credit_note_line_id"])
    op.create_index("ix_sales_returns_org_received", "sales_returns", ["org_id", "received_on"])
    op.create_index("ix_sales_returns_org_contact", "sales_returns", ["org_id", "contact_id"])
    op.create_index("ix_sales_returns_allocation", "sales_returns", ["allocation_id"])


def downgrade():
    if op.get_bind().execute(text("SELECT 1 FROM sales_returns LIMIT 1")).first():
        raise RuntimeError("Customer returns are recorded; downgrading would lose them")
    op.drop_table("sales_returns")
