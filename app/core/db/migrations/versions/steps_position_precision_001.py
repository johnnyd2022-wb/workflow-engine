"""Increase steps.position precision (NUMERIC(50,20))

Revision ID: steps_pos_prec_001
Revises: drop_uq_steps_psn_001
Create Date: 2026-04-13
"""

from typing import Sequence, Union

from alembic import op

revision: str = "steps_pos_prec_001"
down_revision: Union[str, None] = "drop_uq_steps_psn_001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE steps ALTER COLUMN position TYPE NUMERIC(50,20);")


def downgrade() -> None:
    op.execute("ALTER TABLE steps ALTER COLUMN position TYPE NUMERIC(30,10);")

