"""Add unique constraint for steps (process_id, step_number)

Revision ID: uq_steps_process_step_number_001
Revises: idx_ready_date_scale_001
Create Date: 2026-04-13

Fixes TOCTOU race on step_number assignment by enforcing uniqueness at DB level.
"""

from typing import Sequence, Union

from alembic import op

revision: str = "uq_steps_process_step_number_001"
down_revision: Union[str, None] = "idx_ready_date_scale_001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_steps_process_step_number",
        "steps",
        ["process_id", "step_number"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_steps_process_step_number", "steps", type_="unique")

