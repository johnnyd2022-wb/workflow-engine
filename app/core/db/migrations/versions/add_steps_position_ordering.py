"""Add steps.position for flexible ordering (Option B)

Revision ID: steps_position_001
Revises: uq_steps_process_step_number_001
Create Date: 2026-04-13
"""

from typing import Sequence, Union

from alembic import op

revision: str = "steps_position_001"
down_revision: Union[str, None] = "uq_steps_process_step_number_001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add as nullable first for backfill.
    op.execute("ALTER TABLE steps ADD COLUMN IF NOT EXISTS position NUMERIC(30,10);")
    # Backfill: default position = step_number (stable, preserves current ordering).
    op.execute("UPDATE steps SET position = step_number WHERE position IS NULL;")
    # Enforce not-null after backfill.
    op.execute("ALTER TABLE steps ALTER COLUMN position SET NOT NULL;")
    op.execute("CREATE INDEX IF NOT EXISTS idx_steps_process_position ON steps (process_id, position);")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_steps_process_position;")
    op.execute("ALTER TABLE steps DROP COLUMN IF EXISTS position;")

