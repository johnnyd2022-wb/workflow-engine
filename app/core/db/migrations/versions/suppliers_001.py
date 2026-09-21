"""Add the suppliers address book.

Revision ID: suppliers_001
Revises: crm_obfuscate_sales_figures_001
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "suppliers_001"
down_revision = "crm_obfuscate_sales_figures_001"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "suppliers",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "org_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("contact_name", sa.String(length=255)),
        sa.Column("phone", sa.String(length=50)),
        sa.Column("email", sa.String(length=255)),
        sa.Column("address", sa.Text()),
        sa.Column("notes", sa.Text()),
        sa.Column("created_by_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_suppliers_org_id", "suppliers", ["org_id"])
    op.create_index("uq_suppliers_org_name_lower", "suppliers", ["org_id", sa.text("lower(name)")], unique=True)


def downgrade():
    op.drop_index("uq_suppliers_org_name_lower", table_name="suppliers")
    op.drop_index("ix_suppliers_org_id", table_name="suppliers")
    op.drop_table("suppliers")
