"""Store Core task archive policy and board layout per organisation.

Revision ID: core_task_archive_prefs_001
Revises: core_task_org_cascade_001
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "core_task_archive_prefs_001"
down_revision = "core_task_org_cascade_001"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("core_task_configs", sa.Column("done_archive_value", sa.Integer(), nullable=False, server_default="1"))
    op.add_column("core_task_configs", sa.Column("done_archive_unit", sa.String(length=10), nullable=False, server_default="weeks"))
    op.add_column(
        "core_task_configs",
        sa.Column("lane_order", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'[]'::jsonb")),
    )
    op.add_column(
        "core_task_configs",
        sa.Column("hidden_default_lanes", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'[]'::jsonb")),
    )
    op.create_check_constraint("ck_core_task_config_archive_value", "core_task_configs", "done_archive_value BETWEEN 1 AND 3650")
    op.create_check_constraint("ck_core_task_config_archive_unit", "core_task_configs", "done_archive_unit IN ('days', 'weeks', 'months')")


def downgrade():
    op.drop_constraint("ck_core_task_config_archive_unit", "core_task_configs", type_="check")
    op.drop_constraint("ck_core_task_config_archive_value", "core_task_configs", type_="check")
    op.drop_column("core_task_configs", "hidden_default_lanes")
    op.drop_column("core_task_configs", "lane_order")
    op.drop_column("core_task_configs", "done_archive_unit")
    op.drop_column("core_task_configs", "done_archive_value")
