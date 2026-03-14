"""add session_timeout_minutes to user

Revision ID: bbf0ed8d20f4
Revises: 926821db3a65
Create Date: 2025-01-XX XX:XX:XX.XXXXXX

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'bbf0ed8d20f4'
down_revision: Union[str, None] = '926821db3a65'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add session_timeout_minutes column with default value of 10
    op.add_column('users', sa.Column('session_timeout_minutes', sa.Integer(), nullable=False, server_default='10'))


def downgrade() -> None:
    op.drop_column('users', 'session_timeout_minutes')

