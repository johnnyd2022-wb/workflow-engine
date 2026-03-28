"""Ledger query indexes: (inventory_item_id, created_at) and partial WASTAGE.

Revision ID: inv_mov_item_created_ix_001
Revises: inv_mov_wastage_fk_001
"""

from typing import Sequence, Union

from alembic import op

revision: str = "inv_mov_item_created_ix_001"
down_revision: Union[str, None] = "inv_mov_wastage_fk_001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index(
        "ix_inventory_movements_item_created_at",
        "inventory_movements",
        ["inventory_item_id", "created_at"],
        unique=False,
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_inventory_movements_wastage_item_created
        ON inventory_movements (inventory_item_id, created_at)
        WHERE type = 'WASTAGE';
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_inventory_movements_wastage_item_created")
    op.drop_index("ix_inventory_movements_item_created_at", table_name="inventory_movements")
