"""Add inventory_wastage table for recording wastage/disposal

Revision ID: inventory_wastage_001
Revises: source_output_id_001
Create Date: 2025-02-14

Dedicated table for wastage records; inventory quantity is deducted in application logic.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "inventory_wastage_001"
down_revision: Union[str, None] = "source_output_id_001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    insp = sa.inspect(conn)
    table_exists = "inventory_wastage" in insp.get_table_names()
    if not table_exists:
        op.create_table(
            "inventory_wastage",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
            sa.Column("org_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organisations.id"), nullable=False, index=True),
            sa.Column("inventory_item_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("inventory_items.id"), nullable=False, index=True),
            sa.Column("quantity_wasted", sa.String(50), nullable=False),
            sa.Column("unit", sa.String(50), nullable=False),
            sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("recorded_by", sa.String(255), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        )
    # Index on recorded_at (create if not exists for idempotency after partial runs)
    conn.execute(sa.text(
        "CREATE INDEX IF NOT EXISTS ix_inventory_wastage_recorded_at ON inventory_wastage (recorded_at)"
    ))


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(sa.text("DROP INDEX IF EXISTS ix_inventory_wastage_recorded_at"))
    op.drop_table("inventory_wastage")
