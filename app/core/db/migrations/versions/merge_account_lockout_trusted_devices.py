"""merge account lockout and trusted devices heads

Revision ID: merge_heads_001
Revises: ('add_account_lockout', 'c1d2e3f4a5b6')
Create Date: 2025-01-XX XX:XX:XX.XXXXXX

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'merge_heads_001'
down_revision: Union[str, tuple[str, ...], None] = ('add_account_lockout', 'c1d2e3f4a5b6')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Merge migration - no changes needed, just merges the two heads
    # Both migrations have already been applied, this just creates a single head
    pass


def downgrade() -> None:
    # Merge migration - no changes needed
    pass

