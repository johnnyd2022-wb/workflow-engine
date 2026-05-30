"""Add revenue baseline target setting to CRM traceability config.

Revision ID: crm_revenue_baseline_target_001
Revises: crm_task_done_archive_001
Create Date: 2026-05-16
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "crm_revenue_baseline_target_001"
down_revision: str | None = "crm_task_done_archive_001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "crm_sales_traceability_config",
        sa.Column("revenue_baseline_target_mtd", sa.Numeric(12, 2), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("crm_sales_traceability_config", "revenue_baseline_target_mtd")
