"""Merge core models and phone number migrations

Revision ID: merge_core_phone_001
Revises: ('add_core_models_001', 'add_phone_number_001')
Create Date: 2025-01-XX XX:XX:XX.XXXXXX

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'merge_core_phone_001'
down_revision: Union[str, tuple[str, ...], None] = ('add_core_models_001', 'add_phone_number_001')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Merge migration - no changes needed, just merges the two heads
    # Both migrations have already been applied, this just creates a single head
    pass


def downgrade() -> None:
    # Merge migration - no changes needed
    pass

