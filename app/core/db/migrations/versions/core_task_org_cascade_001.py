"""Cascade Core Task state on organisation deletion.

Revision ID: core_task_org_cascade_001
Revises: task_board_lanes_001
"""

from alembic import op

revision = "core_task_org_cascade_001"
down_revision = "task_board_lanes_001"
branch_labels = None
depends_on = None

_TABLES = ("core_tasks", "core_task_configs", "task_board_lanes")


def upgrade():
    for table in _TABLES:
        op.drop_constraint(f"{table}_org_id_fkey", table, type_="foreignkey")
        op.create_foreign_key(f"{table}_org_id_fkey", table, "organisations", ["org_id"], ["id"], ondelete="CASCADE")


def downgrade():
    for table in reversed(_TABLES):
        op.drop_constraint(f"{table}_org_id_fkey", table, type_="foreignkey")
        op.create_foreign_key(f"{table}_org_id_fkey", table, "organisations", ["org_id"], ["id"])
