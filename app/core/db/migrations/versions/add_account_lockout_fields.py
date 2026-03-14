"""add account lockout fields to user

Revision ID: add_account_lockout
Revises: 926821db3a65
Create Date: 2025-01-XX XX:XX:XX.XXXXXX

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import TIMESTAMP


# revision identifiers, used by Alembic.
revision: str = 'add_account_lockout'
down_revision: Union[str, None] = 'bbf0ed8d20f4'  # Depends on session_timeout migration
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add account lockout fields for brute force protection
    op.add_column('users', sa.Column('failed_login_attempts', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('users', sa.Column('account_locked_until', TIMESTAMP(timezone=True), nullable=True))


def downgrade() -> None:
    # Remove account lockout fields
    op.drop_column('users', 'account_locked_until')
    op.drop_column('users', 'failed_login_attempts')

