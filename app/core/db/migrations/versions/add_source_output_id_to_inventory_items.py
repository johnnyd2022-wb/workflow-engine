"""Add source_output_id to inventory_items for ID-based link to step output definition

Revision ID: source_output_id_001
Revises: merge_draft_tracking_001
Create Date: 2025-02-13

Links produced inventory to the step output definition (step.outputs[].id) so
classification and traceability use IDs instead of name matching.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "source_output_id_001"
down_revision: Union[str, None] = "merge_draft_tracking_001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "inventory_items",
        sa.Column("source_output_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_index(
        "ix_inventory_items_source_output_id",
        "inventory_items",
        ["source_output_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_inventory_items_source_output_id", table_name="inventory_items")
    op.drop_column("inventory_items", "source_output_id")
