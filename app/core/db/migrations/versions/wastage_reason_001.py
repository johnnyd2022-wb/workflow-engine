"""Add reason column to inventory_wastage

Revision ID: wastage_reason_001
Revises: merge_steps_pos_001
Create Date: 2026-05-10

Adds a human-readable reason field to wastage records for audit trail.
Nullable in DB (existing records pre-date the field); enforced as required at the API layer going forward.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "wastage_reason_001"
down_revision: Union[str, None] = "merge_steps_pos_001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("inventory_wastage", sa.Column("reason", sa.String(500), nullable=True))


def downgrade() -> None:
    op.drop_column("inventory_wastage", "reason")
