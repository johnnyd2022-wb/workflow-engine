"""Merge add_is_draft_001 and execution_step_tracking_001 heads

Revision ID: merge_draft_tracking_001
Revises: add_is_draft_001, execution_step_tracking_001
Create Date: 2025-01-30

Ensures CI (which upgrades to head) applies both is_draft and execution_step_tracking.
"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'merge_draft_tracking_001'
down_revision: Union[str, tuple[str, ...], None] = ('add_is_draft_001', 'execution_step_tracking_001')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Merge migration: no schema changes
    pass


def downgrade() -> None:
    pass
