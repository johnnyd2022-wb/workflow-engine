"""add trusted_devices table

Revision ID: c1d2e3f4a5b6
Revises: bbf0ed8d20f4
Create Date: 2025-01-XX XX:XX:XX.XXXXXX

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID


# revision identifiers, used by Alembic.
revision: str = 'c1d2e3f4a5b6'
down_revision: Union[str, None] = 'bbf0ed8d20f4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create trusted_devices table
    op.create_table(
        'trusted_devices',
        sa.Column('id', UUID(as_uuid=True), primary_key=True),
        sa.Column('user_id', UUID(as_uuid=True), nullable=False),
        sa.Column('device_token', sa.String(255), nullable=False),
        sa.Column('device_fingerprint', sa.String(255), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('last_used_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    )
    op.create_index(op.f('ix_trusted_devices_user_id'), 'trusted_devices', ['user_id'], unique=False)
    op.create_index(op.f('ix_trusted_devices_device_token'), 'trusted_devices', ['device_token'], unique=True)
    op.create_index(op.f('ix_trusted_devices_device_fingerprint'), 'trusted_devices', ['device_fingerprint'], unique=False)
    op.create_index(op.f('ix_trusted_devices_expires_at'), 'trusted_devices', ['expires_at'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_trusted_devices_expires_at'), table_name='trusted_devices')
    op.drop_index(op.f('ix_trusted_devices_device_fingerprint'), table_name='trusted_devices')
    op.drop_index(op.f('ix_trusted_devices_device_token'), table_name='trusted_devices')
    op.drop_index(op.f('ix_trusted_devices_user_id'), table_name='trusted_devices')
    op.drop_table('trusted_devices')

