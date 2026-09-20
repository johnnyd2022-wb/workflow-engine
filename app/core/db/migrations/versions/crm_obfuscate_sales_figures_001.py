"""Add tenant CRM sales-figure obfuscation preference.

Revision ID: crm_obfuscate_sales_figures_001
Revises: crm_revenue_baseline_target_001
Create Date: 2026-09-20
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "crm_obfuscate_sales_figures_001"
down_revision: str | None = "crm_revenue_baseline_target_001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "crm_sales_traceability_config",
        sa.Column("obfuscate_sales_figures", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.alter_column("crm_sales_traceability_config", "obfuscate_sales_figures", server_default=None)


def downgrade() -> None:
    op.drop_column("crm_sales_traceability_config", "obfuscate_sales_figures")
