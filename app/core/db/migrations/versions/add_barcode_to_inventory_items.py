"""Add barcode column to inventory_items for product identity / scanner flow

Revision ID: add_barcode_inventory_001
Revises: inventory_batch_unique_001
Create Date: 2025-02-28

Barcode is optional, indexed for lookup; not unique (same barcode can appear in multiple stock entries).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "add_barcode_inventory_001"
down_revision: Union[str, None] = "inventory_batch_unique_001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "inventory_items",
        sa.Column("barcode", sa.String(255), nullable=True),
    )
    op.create_index(
        "ix_inventory_items_barcode",
        "inventory_items",
        ["barcode"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_inventory_items_barcode", table_name="inventory_items")
    op.drop_column("inventory_items", "barcode")
