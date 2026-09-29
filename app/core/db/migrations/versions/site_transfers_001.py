"""Recorded dispatch, transit, receipt and fragment proof (partial plan 7.1d).

Revision ID: site_transfers_001
Revises: customs_premises_001
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "site_transfers_001"
down_revision = "customs_premises_001"
branch_labels = None
depends_on = None


def upgrade():
    op.drop_index("uq_inventory_items_org_name_batch_location", table_name="inventory_items")
    op.create_unique_constraint("uq_inventory_items_org_id", "inventory_items", ["org_id", "id"])
    op.execute("""CREATE TABLE site_stock_transfers (
        id uuid PRIMARY KEY, org_id uuid NOT NULL REFERENCES organisations(id) ON DELETE CASCADE,
        source_item_id uuid NOT NULL, source_site_id uuid NOT NULL, destination_site_id uuid NOT NULL,
        source_location_id uuid, destination_location_id uuid,
        quantity numeric(18,4) NOT NULL, received_quantity numeric(18,4) NOT NULL DEFAULT 0,
        loss_quantity numeric(18,4) NOT NULL DEFAULT 0, unit varchar(50) NOT NULL,
        carrier varchar(120) NOT NULL, consignment_reference varchar(160) NOT NULL,
        occurred_on date NOT NULL, source_snapshot jsonb NOT NULL, decision_snapshot jsonb NOT NULL,
        idempotency_key varchar(128) NOT NULL, request_hash varchar(64) NOT NULL,
        created_by_user_id uuid NOT NULL REFERENCES users(id), created_at timestamptz NOT NULL,
        CONSTRAINT uq_site_stock_transfers_org_id UNIQUE(org_id,id),
        CONSTRAINT uq_site_transfer_dispatch_key UNIQUE(org_id,idempotency_key),
        CONSTRAINT fk_site_transfer_actor FOREIGN KEY(org_id,created_by_user_id) REFERENCES users(org_id,id),
        CONSTRAINT fk_site_transfer_source_item FOREIGN KEY(org_id,source_item_id) REFERENCES inventory_items(org_id,id),
        CONSTRAINT fk_site_transfer_source_site FOREIGN KEY(org_id,source_site_id) REFERENCES sites(org_id,id),
        CONSTRAINT fk_site_transfer_destination_site FOREIGN KEY(org_id,destination_site_id) REFERENCES sites(org_id,id),
        CONSTRAINT fk_site_transfer_source_location FOREIGN KEY(org_id,source_site_id,source_location_id) REFERENCES stock_locations(org_id,site_id,id),
        CONSTRAINT fk_site_transfer_destination_location FOREIGN KEY(org_id,destination_site_id,destination_location_id) REFERENCES stock_locations(org_id,site_id,id),
        CONSTRAINT ck_site_transfer_conservation CHECK(quantity>0 AND received_quantity>=0 AND loss_quantity>=0 AND received_quantity+loss_quantity<=quantity)
    )""")
    op.execute("""CREATE TABLE site_stock_receipts (
        id uuid PRIMARY KEY, org_id uuid NOT NULL REFERENCES organisations(id) ON DELETE CASCADE,
        transfer_id uuid NOT NULL, quantity numeric(18,4) NOT NULL,
        damaged_quantity numeric(18,4) NOT NULL DEFAULT 0, short_quantity numeric(18,4) NOT NULL DEFAULT 0,
        loss_reason varchar(500), occurred_on date NOT NULL, decision_snapshot jsonb NOT NULL,
        idempotency_key varchar(128) NOT NULL, request_hash varchar(64) NOT NULL,
        created_by_user_id uuid NOT NULL REFERENCES users(id), created_at timestamptz NOT NULL,
        CONSTRAINT uq_site_stock_receipts_org_id UNIQUE(org_id,id),
        CONSTRAINT uq_site_transfer_receipt_key UNIQUE(org_id,idempotency_key),
        CONSTRAINT fk_site_receipt_actor FOREIGN KEY(org_id,created_by_user_id) REFERENCES users(org_id,id),
        CONSTRAINT fk_site_stock_receipt_transfer FOREIGN KEY(org_id,transfer_id) REFERENCES site_stock_transfers(org_id,id),
        CONSTRAINT ck_site_receipt_quantities CHECK(quantity>=0 AND damaged_quantity>=0 AND short_quantity>=0 AND quantity+damaged_quantity+short_quantity>0),
        CONSTRAINT ck_site_receipt_loss_reason CHECK(damaged_quantity+short_quantity=0 OR (loss_reason IS NOT NULL AND length(trim(loss_reason))>0))
    )""")
    op.create_index("ix_site_stock_receipts_transfer_id", "site_stock_receipts", ["transfer_id"])
    op.add_column("inventory_items", sa.Column("transfer_receipt_id", UUID(as_uuid=True), nullable=True))
    # Ordinary lot deduplication remains. Only immutable receipt-backed fragments
    # have a separate identity and may share a batch/site/place.
    op.execute(
        "CREATE UNIQUE INDEX uq_inventory_items_org_name_batch_location ON inventory_items "
        "(org_id,name,supplier_batch_number,COALESCE(location_id,'00000000-0000-0000-0000-000000000000'::uuid),"
        "COALESCE(site_id,'00000000-0000-0000-0000-000000000000'::uuid)) "
        "WHERE supplier_batch_number IS NOT NULL AND transfer_receipt_id IS NULL"
    )
    op.create_unique_constraint("uq_inventory_transfer_receipt", "inventory_items", ["org_id", "transfer_receipt_id"])
    op.create_foreign_key(
        "fk_inventory_transfer_receipt",
        "inventory_items",
        "site_stock_receipts",
        ["org_id", "transfer_receipt_id"],
        ["org_id", "id"],
    )


def downgrade():
    op.execute("""DO $$ BEGIN IF EXISTS (SELECT 1 FROM site_stock_transfers)
        THEN RAISE EXCEPTION 'Recorded transfer history must be retained'; END IF; END $$""")
    op.drop_constraint("fk_inventory_transfer_receipt", "inventory_items", type_="foreignkey")
    op.drop_constraint("uq_inventory_transfer_receipt", "inventory_items", type_="unique")
    op.drop_index("uq_inventory_items_org_name_batch_location", table_name="inventory_items")
    op.drop_column("inventory_items", "transfer_receipt_id")
    op.drop_table("site_stock_receipts")
    op.drop_table("site_stock_transfers")
    op.drop_constraint("uq_inventory_items_org_id", "inventory_items", type_="unique")
    op.execute(
        "CREATE UNIQUE INDEX uq_inventory_items_org_name_batch_location ON inventory_items "
        "(org_id,name,supplier_batch_number,COALESCE(location_id,'00000000-0000-0000-0000-000000000000'::uuid)) "
        "WHERE supplier_batch_number IS NOT NULL"
    )
