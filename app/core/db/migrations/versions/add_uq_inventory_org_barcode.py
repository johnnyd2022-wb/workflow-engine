"""Add unique constraint (org_id, barcode) for inventory_items to prevent duplicate product identity

Revision ID: uq_inventory_org_barcode_001
Revises: add_barcode_inventory_001
Create Date: 2025-02-28

Ensures one row per barcode per org; repeat scans add quantity to existing row.
Partial index: only when barcode IS NOT NULL.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "uq_inventory_org_barcode_001"
down_revision: Union[str, None] = "add_barcode_inventory_001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index(
        "uq_inventory_org_barcode",
        "inventory_items",
        ["org_id", "barcode"],
        unique=True,
        postgresql_where=sa.text("barcode IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_inventory_org_barcode", table_name="inventory_items")
