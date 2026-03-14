"""add two factor backup codes table

Revision ID: add_backup_codes_001
Revises: merge_heads_001
Create Date: 2025-01-XX XX:XX:XX.XXXXXX

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID


# revision identifiers, used by Alembic.
revision: str = 'add_backup_codes_001'
down_revision: Union[str, None] = 'merge_heads_001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create two_factor_backup_codes table
    op.create_table(
        'two_factor_backup_codes',
        sa.Column('id', UUID(as_uuid=True), primary_key=True),
        sa.Column('user_id', UUID(as_uuid=True), nullable=False),
        sa.Column('encrypted_code', sa.String(), nullable=False),
        sa.Column('consumed', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    )
    op.create_index('ix_two_factor_backup_codes_user_id', 'two_factor_backup_codes', ['user_id'])


def downgrade() -> None:
    op.drop_index('ix_two_factor_backup_codes_user_id', table_name='two_factor_backup_codes')
    op.drop_table('two_factor_backup_codes')

