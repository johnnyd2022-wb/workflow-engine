"""Persist task-board lanes and placement across devices.

Revision ID: task_board_lanes_001
Revises: core_tasks_001
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "task_board_lanes_001"
down_revision = "core_tasks_001"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "task_board_lanes",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("board", sa.String(length=20), nullable=False),
        sa.Column("title", sa.String(length=80), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_by_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.CheckConstraint("board IN ('core', 'crm')", name="ck_task_board_lanes_board"),
        sa.UniqueConstraint("org_id", "board", "title", name="uq_task_board_lanes_org_board_title"),
    )
    op.create_index("ix_task_board_lanes_org_id", "task_board_lanes", ["org_id"])
    op.create_index("ix_task_board_lanes_org_board_position", "task_board_lanes", ["org_id", "board", "position"])
    op.add_column("core_tasks", sa.Column("board_lane_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.create_foreign_key("fk_core_tasks_board_lane", "core_tasks", "task_board_lanes", ["board_lane_id"], ["id"], ondelete="SET NULL")
    op.create_index("ix_core_tasks_org_board_lane", "core_tasks", ["org_id", "board_lane_id"])
    op.add_column("crm_tasks", sa.Column("board_lane_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.create_foreign_key("fk_crm_tasks_board_lane", "crm_tasks", "task_board_lanes", ["board_lane_id"], ["id"], ondelete="SET NULL")
    op.create_index("ix_crm_tasks_org_board_lane", "crm_tasks", ["org_id", "board_lane_id"])


def downgrade():
    op.drop_index("ix_crm_tasks_org_board_lane", table_name="crm_tasks")
    op.drop_constraint("fk_crm_tasks_board_lane", "crm_tasks", type_="foreignkey")
    op.drop_column("crm_tasks", "board_lane_id")
    op.drop_index("ix_core_tasks_org_board_lane", table_name="core_tasks")
    op.drop_constraint("fk_core_tasks_board_lane", "core_tasks", type_="foreignkey")
    op.drop_column("core_tasks", "board_lane_id")
    op.drop_index("ix_task_board_lanes_org_board_position", table_name="task_board_lanes")
    op.drop_index("ix_task_board_lanes_org_id", table_name="task_board_lanes")
    op.drop_table("task_board_lanes")
