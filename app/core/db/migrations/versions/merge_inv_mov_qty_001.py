"""Merge heads: inv_mov_item_created_ix_001 + inv_qty_pg_guard_002.

Single linear head so ``alembic upgrade head`` works in CI and all environments.

Revision ID: merge_inv_mov_qty_001
Revises: inv_mov_item_created_ix_001, inv_qty_pg_guard_002
"""

from typing import Sequence, Union

revision: str = "merge_inv_mov_qty_001"
down_revision: Union[str, tuple[str, ...], None] = (
    "inv_mov_item_created_ix_001",
    "inv_qty_pg_guard_002",
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """No-op merge: both parents already applied their DDL."""
    pass


def downgrade() -> None:
    """Merge points are not split automatically."""
    pass
