"""Immutable customer raw title and receipt proof; known prerequisite branches only.

The two parents are published prerequisites, not a guessed food/register ancestry.
Linearize with the final food/sites/contracts migration train before operational release.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "contract_material_ownership_001"
down_revision = ("site_transfers_001", "contract_portal_001")
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "organisations", sa.Column("contract_materials_enabled", sa.Boolean(), nullable=False, server_default="false")
    )
    op.create_table(
        "contract_material_receipts",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("org_id", UUID(as_uuid=True), sa.ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("customer_id", UUID(as_uuid=True), nullable=False),
        sa.Column("inventory_item_id", UUID(as_uuid=True), nullable=False),
        sa.Column("quantity", sa.Numeric(18, 4), nullable=False),
        sa.Column("unit", sa.String(50), nullable=False),
        sa.Column("evidence_reference", sa.String(255), nullable=False),
        sa.Column("stock_snapshot", JSONB(), nullable=False),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("received_by", UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("org_id", "id", name="uq_material_receipt_org_id"),
        sa.UniqueConstraint("org_id", "customer_id", "id", "inventory_item_id", name="uq_material_receipt_owner_lot"),
        sa.UniqueConstraint("org_id", "idempotency_key", name="uq_material_receipt_key"),
        sa.CheckConstraint("quantity > 0", name="ck_material_receipt_quantity"),
        sa.ForeignKeyConstraint(["org_id", "customer_id"], ["contract_customers.org_id", "contract_customers.id"]),
        sa.ForeignKeyConstraint(["org_id", "received_by"], ["users.org_id", "users.id"]),
        sa.ForeignKeyConstraint(
            ["org_id", "inventory_item_id"],
            ["inventory_items.org_id", "inventory_items.id"],
            deferrable=True,
            initially="DEFERRED",
        ),
    )
    op.create_index("ix_material_receipts_customer", "contract_material_receipts", ["org_id", "customer_id"])
    op.add_column("inventory_items", sa.Column("contract_customer_id", UUID(as_uuid=True), nullable=True))
    op.add_column("inventory_items", sa.Column("material_receipt_id", UUID(as_uuid=True), nullable=True))
    op.create_index("ix_inventory_customer_owner", "inventory_items", ["org_id", "contract_customer_id"])
    op.create_foreign_key(
        "fk_inventory_customer_owner",
        "inventory_items",
        "contract_customers",
        ["org_id", "contract_customer_id"],
        ["org_id", "id"],
    )
    op.create_foreign_key(
        "fk_inventory_material_receipt",
        "inventory_items",
        "contract_material_receipts",
        ["org_id", "contract_customer_id", "material_receipt_id", "id"],
        ["org_id", "customer_id", "id", "inventory_item_id"],
        deferrable=True,
        initially="DEFERRED",
    )
    op.create_check_constraint(
        "ck_inventory_customer_raw",
        "inventory_items",
        "contract_customer_id IS NULL OR inventory_type = 'raw_material'",
    )
    op.create_check_constraint(
        "ck_inventory_material_proof",
        "inventory_items",
        "material_receipt_id IS NULL OR contract_customer_id IS NOT NULL",
    )
    op.drop_index("uq_inventory_items_org_name_batch_location", table_name="inventory_items")
    op.execute(
        "CREATE UNIQUE INDEX uq_inventory_items_org_name_batch_location ON inventory_items "
        "(org_id,name,supplier_batch_number,COALESCE(location_id,'00000000-0000-0000-0000-000000000000'::uuid),"
        "COALESCE(site_id,'00000000-0000-0000-0000-000000000000'::uuid)) "
        "WHERE supplier_batch_number IS NOT NULL AND transfer_receipt_id IS NULL AND material_receipt_id IS NULL"
    )
    op.execute("""CREATE FUNCTION enforce_contract_raw_title() RETURNS trigger AS $$
    DECLARE receipt contract_material_receipts%ROWTYPE; transfer_owner text;
    BEGIN
      IF current_setting('app.migration_mode', true) = '1' THEN
        IF TG_OP='DELETE' THEN RETURN OLD; ELSE RETURN NEW; END IF;
      END IF;
      IF TG_OP='DELETE' THEN
        IF OLD.contract_customer_id IS NOT NULL THEN
          RAISE EXCEPTION 'Customer stock evidence cannot be deleted';
        END IF;
        RETURN OLD;
      END IF;
      IF TG_OP = 'UPDATE' THEN
        IF NEW.contract_customer_id IS DISTINCT FROM OLD.contract_customer_id
          OR NEW.material_receipt_id IS DISTINCT FROM OLD.material_receipt_id
          OR NEW.transfer_receipt_id IS DISTINCT FROM OLD.transfer_receipt_id THEN
          RAISE EXCEPTION 'Recorded stock title and receipt proof are immutable';
        END IF;
        IF OLD.contract_customer_id IS NOT NULL AND (
          NEW.transfer_receipt_id IS DISTINCT FROM OLD.transfer_receipt_id
          OR NEW.name IS DISTINCT FROM OLD.name OR NEW.unit IS DISTINCT FROM OLD.unit
          OR NEW.inventory_type IS DISTINCT FROM OLD.inventory_type
          OR NEW.supplier IS DISTINCT FROM OLD.supplier
          OR NEW.supplier_batch_number IS DISTINCT FROM OLD.supplier_batch_number
          OR NEW.source_execution_id IS DISTINCT FROM OLD.source_execution_id
          OR NEW.source_execution_step_id IS DISTINCT FROM OLD.source_execution_step_id
          OR NEW.source_output_id IS DISTINCT FROM OLD.source_output_id
          OR NEW.source_step_name IS DISTINCT FROM OLD.source_step_name
          OR NEW.site_id IS DISTINCT FROM OLD.site_id
          OR NEW.location_id IS DISTINCT FROM OLD.location_id
          OR NEW.expiry_date IS DISTINCT FROM OLD.expiry_date
          OR NEW.purchase_date IS DISTINCT FROM OLD.purchase_date
          OR NEW.barcode IS DISTINCT FROM OLD.barcode
          OR NEW.extra_data IS DISTINCT FROM OLD.extra_data) THEN
          RAISE EXCEPTION 'Customer raw stock identity and lineage are immutable';
        END IF;
      ELSIF NEW.transfer_receipt_id IS NOT NULL THEN
          SELECT t.source_snapshot->>'contract_customer_id' INTO transfer_owner
            FROM site_stock_receipts r JOIN site_stock_transfers t
              ON t.org_id=r.org_id AND t.id=r.transfer_id
            WHERE r.org_id=NEW.org_id AND r.id=NEW.transfer_receipt_id;
          IF NOT FOUND OR transfer_owner IS DISTINCT FROM NEW.contract_customer_id::text THEN
            RAISE EXCEPTION 'Transfer receipt must conserve customer title';
          END IF;
      ELSIF NEW.contract_customer_id IS NOT NULL THEN
        IF NEW.material_receipt_id IS NOT NULL THEN
          SELECT * INTO receipt FROM contract_material_receipts
            WHERE org_id=NEW.org_id AND id=NEW.material_receipt_id
              AND customer_id=NEW.contract_customer_id AND inventory_item_id=NEW.id;
          IF NOT FOUND OR receipt.quantity<>NEW.quantity OR receipt.unit<>NEW.unit
            OR receipt.stock_snapshot->>'name' IS DISTINCT FROM NEW.name
            OR receipt.stock_snapshot->>'supplier' IS DISTINCT FROM NEW.supplier
            OR receipt.stock_snapshot->>'supplier_batch_number' IS DISTINCT FROM NEW.supplier_batch_number
            OR receipt.stock_snapshot->>'purchase_date' IS DISTINCT FROM NEW.purchase_date::text
            OR receipt.stock_snapshot->>'expiry_date' IS DISTINCT FROM NEW.expiry_date::text
            OR receipt.stock_snapshot->>'site_id' IS DISTINCT FROM NEW.site_id::text
            OR receipt.stock_snapshot->>'location_id' IS DISTINCT FROM NEW.location_id::text
            OR receipt.stock_snapshot->>'original_barcode' IS DISTINCT FROM NEW.extra_data->>'original_barcode'
            OR NEW.extra_data->>'origin_material_receipt_id' IS DISTINCT FROM NEW.material_receipt_id::text
            OR NEW.extra_data->>'free_issue_acquisition_cost' IS DISTINCT FROM '0'
            OR NEW.barcode IS NOT NULL
            OR NEW.source_execution_id IS NOT NULL
            OR NEW.source_execution_step_id IS NOT NULL
            OR NEW.source_output_id IS NOT NULL THEN
            RAISE EXCEPTION 'Customer stock requires a matching immutable raw receipt';
          END IF;
        ELSE RAISE EXCEPTION 'Customer stock requires recorded receipt proof'; END IF;
      END IF;
      RETURN NEW;
    END; $$ LANGUAGE plpgsql""")
    op.execute(
        "CREATE TRIGGER contract_raw_title BEFORE INSERT OR UPDATE OR DELETE ON inventory_items FOR EACH ROW EXECUTE FUNCTION enforce_contract_raw_title()"
    )
    op.execute("""CREATE FUNCTION enforce_material_receipt_immutable() RETURNS trigger AS $$
    BEGIN
      IF current_setting('app.migration_mode', true) = '1' THEN
        IF TG_OP='DELETE' THEN RETURN OLD; ELSE RETURN NEW; END IF;
      END IF;
      RAISE EXCEPTION 'Customer material receipt evidence is immutable';
    END; $$ LANGUAGE plpgsql""")
    op.execute(
        "CREATE TRIGGER material_receipt_immutable BEFORE UPDATE OR DELETE ON contract_material_receipts FOR EACH ROW EXECUTE FUNCTION enforce_material_receipt_immutable()"
    )

    op.execute("""CREATE FUNCTION enforce_transfer_customer_title() RETURNS trigger AS $$
    DECLARE actual_owner uuid;
    BEGIN
      IF current_setting('app.migration_mode', true) = '1' THEN
        IF TG_OP='DELETE' THEN RETURN OLD; ELSE RETURN NEW; END IF;
      END IF;
      IF TG_OP='DELETE' THEN
        IF OLD.source_snapshot->>'contract_customer_id' IS NOT NULL THEN
          RAISE EXCEPTION 'Customer transfer title evidence cannot be deleted';
        END IF;
        RETURN OLD;
      END IF;
      IF TG_OP='INSERT' THEN
        SELECT contract_customer_id INTO actual_owner FROM inventory_items
          WHERE org_id=NEW.org_id AND id=NEW.source_item_id;
        IF NEW.source_snapshot->>'contract_customer_id' IS DISTINCT FROM actual_owner::text THEN
          RAISE EXCEPTION 'Dispatch must preserve the trusted source customer title';
        END IF;
      ELSIF (OLD.source_snapshot->>'contract_customer_id' IS NOT NULL
        OR NEW.source_snapshot->>'contract_customer_id' IS NOT NULL) AND (
        NEW.source_snapshot IS DISTINCT FROM OLD.source_snapshot
        OR NEW.source_item_id IS DISTINCT FROM OLD.source_item_id
        OR NEW.org_id IS DISTINCT FROM OLD.org_id) THEN
        RAISE EXCEPTION 'Customer dispatch title and source facts are immutable';
      END IF;
      RETURN NEW;
    END; $$ LANGUAGE plpgsql""")
    op.execute(
        "CREATE TRIGGER transfer_customer_title BEFORE INSERT OR UPDATE OR DELETE ON site_stock_transfers FOR EACH ROW EXECUTE FUNCTION enforce_transfer_customer_title()"
    )


def downgrade():
    op.execute("""DO $$ BEGIN
      IF EXISTS(SELECT 1 FROM inventory_items WHERE contract_customer_id IS NOT NULL)
         OR EXISTS(SELECT 1 FROM contract_material_receipts) THEN
        RAISE EXCEPTION 'Archive customer stock and receipt evidence explicitly before ownership downgrade';
      END IF;
    END $$""")
    op.execute("DROP TRIGGER IF EXISTS transfer_customer_title ON site_stock_transfers")
    op.execute("DROP FUNCTION IF EXISTS enforce_transfer_customer_title()")
    op.execute("DROP TRIGGER material_receipt_immutable ON contract_material_receipts")
    op.execute("DROP FUNCTION enforce_material_receipt_immutable()")
    op.execute("DROP TRIGGER contract_raw_title ON inventory_items")
    op.execute("DROP FUNCTION enforce_contract_raw_title()")
    op.drop_constraint("fk_inventory_material_receipt", "inventory_items", type_="foreignkey")
    op.drop_constraint("fk_inventory_customer_owner", "inventory_items", type_="foreignkey")
    op.drop_constraint("ck_inventory_customer_raw", "inventory_items", type_="check")
    op.drop_constraint("ck_inventory_material_proof", "inventory_items", type_="check")
    op.drop_index("ix_inventory_customer_owner", table_name="inventory_items")
    op.drop_index("uq_inventory_items_org_name_batch_location", table_name="inventory_items")
    op.execute(
        "CREATE UNIQUE INDEX uq_inventory_items_org_name_batch_location ON inventory_items "
        "(org_id,name,supplier_batch_number,COALESCE(location_id,'00000000-0000-0000-0000-000000000000'::uuid),"
        "COALESCE(site_id,'00000000-0000-0000-0000-000000000000'::uuid)) "
        "WHERE supplier_batch_number IS NOT NULL AND transfer_receipt_id IS NULL"
    )
    op.drop_column("inventory_items", "material_receipt_id")
    op.drop_column("inventory_items", "contract_customer_id")
    op.drop_table("contract_material_receipts")
    op.drop_column("organisations", "contract_materials_enabled")
