"""Merge Alembic heads (inventory guard + steps ordering)

Revision ID: merge_steps_pos_001
Revises: inv_qty_pg_guard_003, steps_pos_grid_001
Create Date: 2026-04-13

CI expects a single Alembic head; this merge migration unifies branches.
"""

from typing import Sequence, Union

from alembic import op

revision: str = "merge_steps_pos_001"
down_revision: Union[str, tuple[str, ...], None] = ("inv_qty_pg_guard_003", "steps_pos_grid_001")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Merge-only migration: no schema changes.
    pass


def downgrade() -> None:
    pass

