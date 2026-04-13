"""Normalize steps.position to 1000-grid and add CHECK constraint

Revision ID: steps_pos_grid_001
Revises: steps_pos_prec_001
Create Date: 2026-04-13

Enforces invariant: steps.position must be a positive multiple of 1000.
"""

from typing import Sequence, Union

from alembic import op

revision: str = "steps_pos_grid_001"
down_revision: Union[str, None] = "steps_pos_prec_001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Recompute positions deterministically per process using current order.
    op.execute(
        """
        WITH ranked AS (
            SELECT
                id,
                process_id,
                ROW_NUMBER() OVER (PARTITION BY process_id ORDER BY position, id) AS rn
            FROM steps
        )
        UPDATE steps s
        SET position = (ranked.rn * 1000)::numeric
        FROM ranked
        WHERE s.id = ranked.id;
        """
    )
    # Enforce invariant in DB.
    op.execute(
        """
        ALTER TABLE steps
        ADD CONSTRAINT chk_steps_position_grid
        CHECK (position > 0 AND MOD(position, 1000) = 0);
        """
    )


def downgrade() -> None:
    op.execute("ALTER TABLE steps DROP CONSTRAINT IF EXISTS chk_steps_position_grid;")

