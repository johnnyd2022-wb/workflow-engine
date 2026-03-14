"""Add unique constraint on (org_id, name, supplier_batch_number) for inventory_items

Revision ID: inventory_batch_unique_001
Revises: inventory_wastage_001
Create Date: 2025-02-22

Prevents duplicate batch numbers per org+name at DB level; safe under concurrent CSV uploads.
Partial index: only when supplier_batch_number IS NOT NULL.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "inventory_batch_unique_001"
down_revision: Union[str, None] = "inventory_wastage_001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Partial unique index: (org_id, name, supplier_batch_number) when batch is not null
    op.create_index(
        "uq_inventory_items_org_name_batch",
        "inventory_items",
        ["org_id", "name", "supplier_batch_number"],
        unique=True,
        postgresql_where=sa.text("supplier_batch_number IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_inventory_items_org_name_batch", table_name="inventory_items")
