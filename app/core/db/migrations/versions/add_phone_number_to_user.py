"""add phone_number to users table

Revision ID: add_phone_number_001
Revises: add_backup_codes_001
Create Date: 2025-01-XX XX:XX:XX.XXXXXX

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'add_phone_number_001'
down_revision: Union[str, None] = 'add_backup_codes_001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add phone_number column to users table (nullable to support existing data)
    op.add_column('users', sa.Column('phone_number', sa.String(length=15), nullable=True))


def downgrade() -> None:
    # Remove phone_number column from users table
    op.drop_column('users', 'phone_number')

