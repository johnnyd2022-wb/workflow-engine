"""Add done-task archive days setting to CRM traceability config.

Revision ID: crm_task_done_archive_001
Revises: org_fk_cascade_users_audit_001
Create Date: 2026-05-16
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "crm_task_done_archive_001"
down_revision: str | None = "org_fk_cascade_users_audit_001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "crm_sales_traceability_config",
        sa.Column("task_done_archive_days", sa.Integer(), nullable=False, server_default="7"),
    )


def downgrade() -> None:
    op.drop_column("crm_sales_traceability_config", "task_done_archive_days")
