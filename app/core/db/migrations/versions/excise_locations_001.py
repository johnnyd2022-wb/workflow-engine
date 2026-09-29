"""Stock locations and transfers (Core), excise rates and lodgements (Compliant)

Revision ID: excise_locations_001
Revises: sales_matching_modes_001
Create Date: 2026-09-28

Plan item 2.1. Customs taxes alcohol when it is **removed** from the licensed area, not
when it is invoiced, so stock needs a place:

- ``stock_locations``: named places stock can be (a sales rep's car, an event, a shop),
  each either inside or outside the licensed (Customs-controlled) area. An inventory item
  with no location is in the main licensed area, as everything is today.
- ``stock_transfers``: moving part of a batch to another location splits it into a new
  lot with the same lineage; a move that crosses out of the licensed area is a removal.
- ``compliance_alcohol_product_profiles`` gains the pack volume, and ABV becomes an
  optional fallback (the batch's final-step ABV is the source).
- ``excise_rates``: dated duty rates per Customs tariff item (they change every 1 July).
- ``excise_lodgements``: a period's lodged figures, locked when confirmed.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision: str = "excise_locations_001"
down_revision: Union[str, None] = "sales_matching_modes_001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "stock_locations",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("org_id", UUID(as_uuid=True), sa.ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("inside_licensed_area", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("org_id", "name", name="uq_stock_locations_org_name"),
    )
    op.add_column(
        "inventory_items",
        sa.Column(
            "location_id", UUID(as_uuid=True), sa.ForeignKey("stock_locations.id", ondelete="RESTRICT"), nullable=True
        ),
    )
    op.create_index("ix_inventory_items_location", "inventory_items", ["org_id", "location_id"])
    # A batch can now be in two places (part moved to a rep's car), so batch uniqueness is
    # per location. "No location" is the main licensed area and counts as one place.
    op.drop_index("uq_inventory_items_org_name_batch", table_name="inventory_items")
    op.execute(
        "CREATE UNIQUE INDEX uq_inventory_items_org_name_batch_location ON inventory_items "
        "(org_id, name, supplier_batch_number, COALESCE(location_id, '00000000-0000-0000-0000-000000000000'::uuid)) "
        "WHERE supplier_batch_number IS NOT NULL"
    )
    op.create_table(
        "stock_transfers",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("org_id", UUID(as_uuid=True), sa.ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False),
        sa.Column(
            "from_item_id", UUID(as_uuid=True), sa.ForeignKey("inventory_items.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column(
            "to_item_id", UUID(as_uuid=True), sa.ForeignKey("inventory_items.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column("from_location_id", UUID(as_uuid=True), sa.ForeignKey("stock_locations.id"), nullable=True),
        sa.Column("to_location_id", UUID(as_uuid=True), sa.ForeignKey("stock_locations.id"), nullable=True),
        sa.Column("quantity", sa.Numeric(18, 4), nullable=False),
        sa.Column("unit", sa.String(50), nullable=False),
        # Crossing the licensed-area boundary: out = a removal for excise; in = a return.
        sa.Column("direction", sa.String(10), nullable=False, server_default="internal"),
        sa.Column("occurred_on", sa.Date(), nullable=False),
        sa.Column("note", sa.String(500), nullable=True),
        sa.Column(
            "created_by_user_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True
        ),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_stock_transfers_org_date", "stock_transfers", ["org_id", "occurred_on"])
    op.alter_column("compliance_alcohol_product_profiles", "abv_percent", existing_type=sa.Numeric(7, 4), nullable=True)
    op.add_column("compliance_alcohol_product_profiles", sa.Column("pack_volume_ml", sa.Numeric(10, 2), nullable=True))
    op.create_table(
        "excise_rates",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("org_id", UUID(as_uuid=True), sa.ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("tariff_item", sa.String(100), nullable=False),
        sa.Column("description", sa.String(255), nullable=True),
        sa.Column("rate_per_lal", sa.Numeric(12, 4), nullable=False),
        sa.Column("effective_from", sa.Date(), nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("org_id", "tariff_item", "effective_from", name="uq_excise_rates_org_item_from"),
    )
    op.create_table(
        "excise_lodgements",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("org_id", UUID(as_uuid=True), sa.ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column("period_end", sa.Date(), nullable=False),
        sa.Column("lodged_on", sa.Date(), nullable=False),
        sa.Column("entry_reference", sa.String(100), nullable=True),
        sa.Column("nil_return", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("snapshot", JSONB, nullable=False),
        sa.Column(
            "lodged_by_user_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True
        ),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("org_id", "period_start", name="uq_excise_lodgements_org_period"),
    )


def downgrade() -> None:
    op.drop_table("excise_lodgements")
    op.drop_table("excise_rates")
    op.drop_column("compliance_alcohol_product_profiles", "pack_volume_ml")
    op.execute("UPDATE compliance_alcohol_product_profiles SET abv_percent = 0 WHERE abv_percent IS NULL")
    op.alter_column(
        "compliance_alcohol_product_profiles", "abv_percent", existing_type=sa.Numeric(7, 4), nullable=False
    )
    op.drop_index("ix_stock_transfers_org_date", table_name="stock_transfers")
    op.drop_table("stock_transfers")
    # Fails if a batch is split across locations; move it back into one place first.
    op.execute("DROP INDEX IF EXISTS uq_inventory_items_org_name_batch_location")
    op.create_index(
        "uq_inventory_items_org_name_batch",
        "inventory_items",
        ["org_id", "name", "supplier_batch_number"],
        unique=True,
        postgresql_where=sa.text("supplier_batch_number IS NOT NULL"),
    )
    op.drop_index("ix_inventory_items_location", table_name="inventory_items")
    op.drop_column("inventory_items", "location_id")
    op.drop_table("stock_locations")
