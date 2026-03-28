"""Add inventory_movements ledger (append-only signed quantities).

Revision ID: inventory_movements_001
Revises: merge_inv_qty_api_idem_001
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "inventory_movements_001"
down_revision: Union[str, None] = "merge_inv_qty_api_idem_001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    insp = sa.inspect(conn)
    if "inventory_movements" in insp.get_table_names():
        return
    op.create_table(
        "inventory_movements",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organisations.id"), nullable=False),
        sa.Column(
            "inventory_item_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("inventory_items.id"),
            nullable=False,
        ),
        sa.Column("type", sa.String(length=32), nullable=False),
        sa.Column("quantity", sa.Numeric(18, 4), nullable=False),
        sa.Column("unit", sa.String(length=50), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.create_index("ix_inventory_movements_org_id", "inventory_movements", ["org_id"])
    op.create_index("ix_inventory_movements_inventory_item_id", "inventory_movements", ["inventory_item_id"])
    op.create_index("ix_inventory_movements_type", "inventory_movements", ["type"])
    op.create_index("ix_inventory_movements_created_at", "inventory_movements", ["created_at"])
    op.create_index(
        "ix_inventory_movements_org_item_created",
        "inventory_movements",
        ["org_id", "inventory_item_id", "created_at"],
    )


def downgrade() -> None:
    conn = op.get_bind()
    insp = sa.inspect(conn)
    if "inventory_movements" not in insp.get_table_names():
        return
    op.drop_index("ix_inventory_movements_org_item_created", table_name="inventory_movements")
    op.drop_index("ix_inventory_movements_created_at", table_name="inventory_movements")
    op.drop_index("ix_inventory_movements_type", table_name="inventory_movements")
    op.drop_index("ix_inventory_movements_inventory_item_id", table_name="inventory_movements")
    op.drop_index("ix_inventory_movements_org_id", table_name="inventory_movements")
    op.drop_table("inventory_movements")
