"""Add composite index for custom output expiry lookup

Revision ID: idx_inventory_expiry_lookup_001
Revises: add_process_step_docs_001
Create Date: 2026-03-06

Adds an expression index to support efficient lookup of inventory items by:
org_id + source_execution_step_id + case-insensitive name + trimmed unit.
"""

from typing import Sequence, Union

from alembic import op

revision: str = "idx_inventory_expiry_lookup_001"
down_revision: Union[str, None] = "add_process_step_docs_001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_inventory_expiry_lookup
        ON inventory_items (
            org_id,
            source_execution_step_id,
            lower(name),
            trim(unit)
        );
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_inventory_expiry_lookup;")

