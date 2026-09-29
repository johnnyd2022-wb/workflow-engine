"""Stocktakes: counted lines and how each difference was resolved

Revision ID: stocktake_001
Revises: excise_locations_001
Create Date: 2026-09-28

Plan item 2.6. A stocktake compares what the system expects in each lot (by location)
with what was counted. Each difference is resolved with one or more reasons, applied as
ordinary dated stock operations (a move, a removal, wastage, an adjustment), so nothing
is overwritten and every change says who and why.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "stocktake_001"
down_revision: Union[str, None] = "excise_locations_001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "stocktakes",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("org_id", UUID(as_uuid=True), sa.ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("counted_on", sa.Date(), nullable=False),
        sa.Column("kind", sa.String(20), nullable=False, server_default="scheduled"),  # scheduled | customs_visit
        sa.Column("status", sa.String(20), nullable=False, server_default="counting"),  # counting | resolving | done
        sa.Column("note", sa.String(500), nullable=True),
        sa.Column(
            "created_by_user_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True
        ),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("completed_at", sa.TIMESTAMP(timezone=True), nullable=True),
    )
    op.create_index("ix_stocktakes_org_date", "stocktakes", ["org_id", "counted_on"])
    op.create_table(
        "stocktake_lines",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("org_id", UUID(as_uuid=True), sa.ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False),
        sa.Column(
            "stocktake_id", UUID(as_uuid=True), sa.ForeignKey("stocktakes.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column(
            "inventory_item_id",
            UUID(as_uuid=True),
            sa.ForeignKey("inventory_items.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("expected_quantity", sa.Numeric(18, 4), nullable=False),
        sa.Column("counted_quantity", sa.Numeric(18, 4), nullable=True),
        sa.Column("unit", sa.String(50), nullable=False),
        # open (not counted / not resolved) | matched | resolved | investigating
        sa.Column("status", sa.String(20), nullable=False, server_default="open"),
        sa.Column("investigate_until", sa.Date(), nullable=True),
        sa.UniqueConstraint("stocktake_id", "inventory_item_id", name="uq_stocktake_lines_item"),
    )
    op.create_table(
        "stocktake_resolutions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("org_id", UUID(as_uuid=True), sa.ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False),
        sa.Column(
            "line_id", UUID(as_uuid=True), sa.ForeignKey("stocktake_lines.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("reason", sa.String(40), nullable=False),
        sa.Column("quantity", sa.Numeric(18, 4), nullable=False),
        sa.Column("location_id", UUID(as_uuid=True), sa.ForeignKey("stock_locations.id"), nullable=True),
        sa.Column("occurred_on", sa.Date(), nullable=True),
        sa.Column("note", sa.String(500), nullable=True),
        sa.Column("dutiable", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("raise_with_customs", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "created_by_user_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True
        ),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("stocktake_resolutions")
    op.drop_table("stocktake_lines")
    op.drop_index("ix_stocktakes_org_date", table_name="stocktakes")
    op.drop_table("stocktakes")
