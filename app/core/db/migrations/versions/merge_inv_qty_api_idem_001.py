"""Merge inventory_quantity_numeric_001 and api_idempotency_keys_001 (parallel branches from add_first_last_name).

Revision ID: merge_inv_qty_api_idem_001
Revises: inventory_quantity_numeric_001, api_idempotency_keys_001

Ensures CI and fresh databases apply both branches before inventory_movements_001.
No schema changes.

Note: revision id must stay <= 32 chars (PostgreSQL alembic_version.version_num default).
"""

from typing import Sequence, Union

from alembic import op

revision: str = "merge_inv_qty_api_idem_001"
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
