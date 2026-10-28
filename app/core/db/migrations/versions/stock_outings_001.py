"""Taking stock out: a tasting or an event, with bottles sold and returned (founder, 2026-10-28).

- `tastings.kind`: 'tasting' (pours) or 'event' (pours and bottle sales); existing rows are tastings.
- `tasting_allocations.sold_units` / `returned_units`: whole bottles sold at the outing (counted at
  close, plus any linked Xero invoice lines) and brought back unopened; `return_item_id` is the
  duty-paid lot the returned bottles went back into stock as.
- `crm_sales_fifo_allocations.tasting_allocation_id`: a Xero sale made at an outing. It is matched to
  the batch it came from for traceability, but it consumed outing stock, not warehouse stock, and
  is never a second removal for excise.

- `uq_inventory_items_org_name_batch_location` also leaves out duty-paid returns. Bottles back from
  an outing are their own lot (duty was recorded when they left) beside the duty-suspended lot of
  the same batch at the same place, as transfer and material receipts already are.

All additive; downgrade drops them only when nothing has been recorded with them.

Revision ID: stock_outings_001
Revises: excise_cca_001
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import UUID

revision = "stock_outings_001"
down_revision = "excise_cca_001"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("tastings", sa.Column("kind", sa.String(20), nullable=False, server_default="tasting"))
    op.create_check_constraint("ck_tasting_kind", "tastings", "kind IN ('tasting','event')")
    for name in ("sold_units", "returned_units"):
        op.add_column(
            "tasting_allocations", sa.Column(name, sa.Numeric(18, 4), nullable=False, server_default="0")
        )
    op.add_column("tasting_allocations", sa.Column("return_item_id", UUID(as_uuid=True), nullable=True))
    op.create_foreign_key(
        "fk_tasting_allocation_return_item",
        "tasting_allocations",
        "inventory_items",
        ["org_id", "return_item_id"],
        ["org_id", "id"],
        ondelete="RESTRICT",
    )
    op.create_check_constraint(
        "ck_tasting_allocation_bottles", "tasting_allocations", "sold_units >= 0 AND returned_units >= 0"
    )
    op.add_column("crm_sales_fifo_allocations", sa.Column("tasting_allocation_id", UUID(as_uuid=True), nullable=True))
    op.create_index(
        "ix_sales_fifo_tasting_allocation",
        "crm_sales_fifo_allocations",
        ["org_id", "tasting_allocation_id"],
        postgresql_where=sa.text("tasting_allocation_id IS NOT NULL"),
    )
    # COALESCE: a row with no extra_data must stay in the index, not drop out on a NULL.
    _batch_index("AND NOT COALESCE(extra_data ? 'duty_paid_return', false)")


def _batch_index(extra=""):
    op.drop_index("uq_inventory_items_org_name_batch_location", table_name="inventory_items")
    op.execute(
        "CREATE UNIQUE INDEX uq_inventory_items_org_name_batch_location ON inventory_items "
        "(org_id,name,supplier_batch_number,COALESCE(location_id,'00000000-0000-0000-0000-000000000000'::uuid),"
        "COALESCE(site_id,'00000000-0000-0000-0000-000000000000'::uuid)) "
        "WHERE supplier_batch_number IS NOT NULL AND transfer_receipt_id IS NULL AND material_receipt_id IS NULL "
        + extra
    )


def downgrade():
    bind = op.get_bind()
    used = bind.execute(
        text(
            "SELECT 1 FROM tasting_allocations WHERE sold_units > 0 OR returned_units > 0 "
            "UNION ALL SELECT 1 FROM crm_sales_fifo_allocations WHERE tasting_allocation_id IS NOT NULL "
            "UNION ALL SELECT 1 FROM tastings WHERE kind <> 'tasting' LIMIT 1"
        )
    ).first()
    if used:
        raise RuntimeError("Outings have recorded sold or returned bottles; downgrading would lose them")
    _batch_index()
    op.drop_index("ix_sales_fifo_tasting_allocation", table_name="crm_sales_fifo_allocations")
    op.drop_column("crm_sales_fifo_allocations", "tasting_allocation_id")
    op.drop_constraint("ck_tasting_allocation_bottles", "tasting_allocations", type_="check")
    op.drop_constraint("fk_tasting_allocation_return_item", "tasting_allocations", type_="foreignkey")
    for name in ("return_item_id", "returned_units", "sold_units"):
        op.drop_column("tasting_allocations", name)
    op.drop_constraint("ck_tasting_kind", "tastings", type_="check")
    op.drop_column("tastings", "kind")
