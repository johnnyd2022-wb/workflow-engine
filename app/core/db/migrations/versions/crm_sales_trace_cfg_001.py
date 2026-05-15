"""Add CRM sales traceability configuration table.

Revision ID: crm_sales_trace_cfg_001
Revises: crm_prod_mapping_outputid_001
Create Date: 2026-05-15
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "crm_sales_trace_cfg_001"
down_revision: str | None = "crm_prod_mapping_outputid_001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "crm_sales_traceability_config",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("matching_strategy", sa.String(length=30), nullable=False),
        sa.Column("matching_key", sa.String(length=30), nullable=False),
        sa.Column("manual_review_days", sa.Integer(), nullable=False),
        sa.Column("strict_mapping", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["org_id"], ["organisations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("org_id", name="uq_crm_sales_traceability_org"),
    )
    op.create_index(
        "ix_crm_sales_traceability_org",
        "crm_sales_traceability_config",
        ["org_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_crm_sales_traceability_org", table_name="crm_sales_traceability_config")
    op.drop_table("crm_sales_traceability_config")
