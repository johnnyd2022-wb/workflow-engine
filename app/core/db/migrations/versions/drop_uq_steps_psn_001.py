"""Drop unique constraint steps(process_id, step_number) (Option B ordering)

Revision ID: drop_uq_steps_psn_001
Revises: steps_position_001
Create Date: 2026-04-13

Option B uses steps.position for ordering, so step_number is no longer canonical and
must not be constrained unique.
"""

from typing import Sequence, Union

from alembic import op

revision: str = "drop_uq_steps_psn_001"
down_revision: Union[str, None] = "steps_position_001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_constraint("uq_steps_process_step_number", "steps", type_="unique")


def downgrade() -> None:
    op.create_unique_constraint("uq_steps_process_step_number", "steps", ["process_id", "step_number"])

