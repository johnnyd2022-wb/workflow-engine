"""Add always-on Core Tasks and their due-notification policy.

Revision ID: core_tasks_001
Revises: operational_cases_003
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "core_tasks_001"
down_revision = "operational_cases_003"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "core_tasks",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("due_date", sa.Date(), nullable=True),
        sa.Column("status", sa.String(length=50), nullable=False, server_default="pending"),
        sa.Column("priority", sa.String(length=20), nullable=False, server_default="medium"),
        sa.Column("assigned_to_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("created_by_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("completed_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.CheckConstraint("status IN ('pending', 'in_progress', 'completed', 'cancelled')", name="ck_core_tasks_status"),
        sa.CheckConstraint("priority IN ('low', 'medium', 'high')", name="ck_core_tasks_priority"),
    )
    op.create_index("ix_core_tasks_org_id", "core_tasks", ["org_id"])
    op.create_index("ix_core_tasks_org_due_status", "core_tasks", ["org_id", "due_date", "status"])
    op.create_index("ix_core_tasks_org_assignee_status", "core_tasks", ["org_id", "assigned_to_user_id", "status"])
    op.create_table(
        "core_task_configs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("due_notifications_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("notification_lead_value", sa.Integer(), nullable=False, server_default="7"),
        sa.Column("notification_lead_unit", sa.String(length=10), nullable=False, server_default="days"),
        sa.UniqueConstraint("org_id", name="uq_core_task_configs_org"),
        sa.CheckConstraint("notification_lead_value BETWEEN 1 AND 3650", name="ck_core_task_config_lead_value"),
        sa.CheckConstraint("notification_lead_unit IN ('days', 'weeks', 'months')", name="ck_core_task_config_lead_unit"),
    )
    op.create_index("ix_core_task_configs_org_id", "core_task_configs", ["org_id"])


def downgrade():
    op.drop_index("ix_core_task_configs_org_id", table_name="core_task_configs")
    op.drop_table("core_task_configs")
    op.drop_index("ix_core_tasks_org_assignee_status", table_name="core_tasks")
    op.drop_index("ix_core_tasks_org_due_status", table_name="core_tasks")
    op.drop_index("ix_core_tasks_org_id", table_name="core_tasks")
    op.drop_table("core_tasks")
