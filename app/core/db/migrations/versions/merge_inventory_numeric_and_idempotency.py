"""Merge heads: inventory NUMERIC migration + api_idempotency_keys (both branched from add_first_last_name_to_user_001).

Revision ID: merge_qty_idem_001
Revises: inventory_quantity_numeric_001, api_idempotency_keys_001
"""
from typing import Sequence, Union

revision: str = "merge_qty_idem_001"
down_revision: Union[str, tuple[str, ...], None] = (
    "inventory_quantity_numeric_001",
    "api_idempotency_keys_001",
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
