"""Add case-insensitive email uniqueness constraint

Revision ID: case_insensitive_email_001
Revises: acf7c513c15e
Create Date: 2025-01-XX XX:XX:XX.XXXXXX

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'case_insensitive_email_001'
down_revision: Union[str, None] = 'acf7c513c15e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create a unique index on LOWER(email) for case-insensitive uniqueness
    # This prevents race conditions where two signups with the same email (different case) could succeed
    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS ix_users_email_lower_unique 
        ON users (LOWER(email))
    """)


def downgrade() -> None:
    # Drop the case-insensitive unique index
    op.execute("DROP INDEX IF EXISTS ix_users_email_lower_unique")

