"""The transfer migration runs against real DDL and retains ordinary lot safety."""

import importlib
from uuid import uuid4

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError


def test_transfer_migration_roundtrip_and_history_retention(db, monkeypatch):
    migration = importlib.import_module("app.core.db.migrations.versions.site_transfers_001")
    schema = "transfers_" + uuid4().hex
    with db.get_bind().connect() as connection:
        transaction = connection.begin()
        try:
            connection.execute(text(f'CREATE SCHEMA "{schema}"'))
            connection.execute(text(f'SET LOCAL search_path TO "{schema}", public'))
            for ddl in (
                "CREATE TABLE organisations(id uuid PRIMARY KEY)",
                "CREATE TABLE users(id uuid PRIMARY KEY,org_id uuid NOT NULL,UNIQUE(org_id,id))",
                "CREATE TABLE sites(id uuid PRIMARY KEY,org_id uuid NOT NULL,UNIQUE(org_id,id))",
                "CREATE TABLE stock_locations(id uuid PRIMARY KEY,org_id uuid NOT NULL,site_id uuid,UNIQUE(org_id,site_id,id))",
                "CREATE TABLE inventory_items(id uuid PRIMARY KEY,org_id uuid NOT NULL,name text,supplier_batch_number text,location_id uuid,site_id uuid,quantity numeric(18,4))",
                "CREATE UNIQUE INDEX uq_inventory_items_org_name_batch_location ON inventory_items(org_id,name,supplier_batch_number,COALESCE(location_id,'00000000-0000-0000-0000-000000000000'::uuid)) WHERE supplier_batch_number IS NOT NULL",
            ):
                connection.execute(text(ddl))
            values = {
                key: uuid4() for key in ("org", "other", "actor", "stranger", "site", "item", "transfer", "receipt")
            }
            connection.execute(text("INSERT INTO organisations VALUES(:org),(:other)"), values)
            connection.execute(text("INSERT INTO users VALUES(:actor,:org),(:stranger,:other)"), values)
            connection.execute(text("INSERT INTO sites VALUES(:site,:org)"), values)
            connection.execute(
                text("INSERT INTO inventory_items VALUES(:item,:org,'Batch','B-1',NULL,:site,9)"), values
            )
            monkeypatch.setattr(migration, "op", Operations(MigrationContext.configure(connection)))
            migration.upgrade()
            assert connection.execute(text("SELECT quantity FROM inventory_items WHERE id=:item"), values).scalar() == 9
            with pytest.raises(IntegrityError), connection.begin_nested():
                connection.execute(
                    text(
                        "INSERT INTO inventory_items(id,org_id,name,supplier_batch_number,site_id,quantity) VALUES(:copy,:org,'Batch','B-1',:site,2)"
                    ),
                    {**values, "copy": uuid4()},
                )
            dispatch_sql = text(
                "INSERT INTO site_stock_transfers(id,org_id,source_item_id,source_site_id,destination_site_id,quantity,unit,carrier,consignment_reference,occurred_on,source_snapshot,decision_snapshot,idempotency_key,request_hash,created_by_user_id,created_at) VALUES(:transfer,:org,:item,:site,:site,4,'bottles','Carrier','Docket',CURRENT_DATE,'{}','{}','dispatch','hash',:actor,NOW())"
            )
            with pytest.raises(IntegrityError), connection.begin_nested():
                connection.execute(dispatch_sql, {**values, "actor": values["stranger"]})
            connection.execute(dispatch_sql, values)
            connection.execute(
                text(
                    "INSERT INTO site_stock_receipts(id,org_id,transfer_id,quantity,occurred_on,decision_snapshot,idempotency_key,request_hash,created_by_user_id,created_at) VALUES(:receipt,:org,:transfer,2,CURRENT_DATE,'{}','receive','hash',:actor,NOW())"
                ),
                values,
            )
            connection.execute(
                text(
                    "INSERT INTO inventory_items(id,org_id,name,supplier_batch_number,site_id,quantity,transfer_receipt_id) VALUES(:copy,:org,'Batch','B-1',:site,2,:receipt)"
                ),
                {**values, "copy": uuid4()},
            )
            with pytest.raises(IntegrityError), connection.begin_nested():
                connection.execute(
                    text(
                        "INSERT INTO inventory_items(id,org_id,name,supplier_batch_number,site_id,quantity,transfer_receipt_id) VALUES(:copy,:org,'Batch','B-1',:site,2,:receipt)"
                    ),
                    {**values, "copy": uuid4()},
                )
            with pytest.raises(DBAPIError, match="history must be retained"), connection.begin_nested():
                migration.downgrade()
            connection.execute(text("DELETE FROM inventory_items WHERE transfer_receipt_id IS NOT NULL"))
            connection.execute(text("DELETE FROM site_stock_receipts"))
            connection.execute(text("DELETE FROM site_stock_transfers"))
            migration.downgrade()
            assert connection.execute(text("SELECT quantity FROM inventory_items WHERE id=:item"), values).scalar() == 9
        finally:
            transaction.rollback()
