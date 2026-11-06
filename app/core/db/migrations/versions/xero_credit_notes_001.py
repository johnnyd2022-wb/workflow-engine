"""Synced Xero receivable credit notes and audited return decisions.

Revision ID: xero_credit_notes_001
Revises: supplier_lead_time_001
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "xero_credit_notes_001"
down_revision = "supplier_lead_time_001"
branch_labels = None
depends_on = None


def upgrade():
    # Credit-note lines point at a tenant-owned mapping using both key columns.
    op.create_unique_constraint("uq_product_mappings_org_id", "product_mappings", ["org_id", "id"])

    op.create_table(
        "xero_credit_notes",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("org_id", UUID(as_uuid=True), sa.ForeignKey("organisations.id"), nullable=False),
        sa.Column("xero_credit_note_id", sa.String(100), nullable=False),
        sa.Column("xero_tenant_id", sa.String(100), nullable=False),
        sa.Column("number", sa.String(100)),
        sa.Column("contact", sa.String(255)),
        sa.Column("date", sa.Date()),
        sa.Column("status", sa.String(50), nullable=False),
        sa.Column("total", sa.Numeric(18, 4), nullable=False, server_default="0"),
        sa.Column("currency", sa.String(3), nullable=False, server_default="NZD"),
        sa.Column("allocated_invoice_ids", JSONB, nullable=False, server_default="[]"),
        sa.Column("raw_fields", JSONB, nullable=False, server_default="{}"),
        sa.Column("xero_updated_at", sa.TIMESTAMP(timezone=True)),
        sa.Column("last_synced_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("org_id", "id", name="uq_xero_credit_notes_org_id"),
        sa.UniqueConstraint("org_id", "xero_credit_note_id", name="uq_xero_credit_notes_org_xero"),
    )
    op.create_index("ix_xero_credit_notes_org_status_date", "xero_credit_notes", ["org_id", "status", "date"])

    op.create_table(
        "xero_credit_note_lines",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("org_id", UUID(as_uuid=True), sa.ForeignKey("organisations.id"), nullable=False),
        sa.Column("credit_note_id", UUID(as_uuid=True), nullable=False),
        sa.Column("line_key", sa.String(160), nullable=False),
        sa.Column("item_code", sa.String(100)),
        sa.Column("description", sa.Text()),
        sa.Column("quantity", sa.Numeric(18, 4)),
        sa.Column("unit_amount", sa.Numeric(18, 4)),
        sa.Column("line_amount", sa.Numeric(18, 4)),
        sa.Column("product_mapping_id", UUID(as_uuid=True)),
        sa.Column("is_current", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("no_return_note", sa.Text()),
        sa.Column("no_return_by_user_id", UUID(as_uuid=True)),
        sa.Column("no_return_at", sa.TIMESTAMP(timezone=True)),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("org_id", "id", name="uq_xero_credit_note_lines_org_id"),
        sa.UniqueConstraint("org_id", "credit_note_id", "line_key", name="uq_xero_credit_note_line_key"),
        sa.ForeignKeyConstraint(
            ["org_id", "credit_note_id"],
            ["xero_credit_notes.org_id", "xero_credit_notes.id"],
            name="fk_xero_credit_note_line_org_note",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["org_id", "product_mapping_id"],
            ["product_mappings.org_id", "product_mappings.id"],
            name="fk_xero_credit_note_line_org_mapping",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["org_id", "no_return_by_user_id"],
            ["users.org_id", "users.id"],
            name="fk_xero_credit_note_line_org_actor",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "no_return_at IS NULL OR length(trim(coalesce(no_return_note, ''))) > 0",
            name="ck_xero_credit_note_no_return_note",
        ),
    )
    op.create_index(
        "ix_xero_credit_note_lines_org_pending",
        "xero_credit_note_lines",
        ["org_id", "is_current", "no_return_at"],
    )
    op.add_column(
        "xero_sync_jobs",
        sa.Column("credit_notes_synced", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade():
    op.drop_column("xero_sync_jobs", "credit_notes_synced")
    op.drop_index("ix_xero_credit_note_lines_org_pending", table_name="xero_credit_note_lines")
    op.drop_table("xero_credit_note_lines")
    op.drop_index("ix_xero_credit_notes_org_status_date", table_name="xero_credit_notes")
    op.drop_table("xero_credit_notes")
    op.drop_constraint("uq_product_mappings_org_id", "product_mappings", type_="unique")
