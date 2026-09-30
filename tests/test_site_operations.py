"""Actual additional-site production and sales when the internal release gate opens."""

from uuid import UUID, uuid4

import pytest

from app.core.db.models.execution_step import ExecutionStepStatus
from app.core.db.models.inventory_item import InventoryItem
from app.core.db.models.organisation import Organisation
from app.core.db.repositories.execution_repo import ExecutionRepository
from app.core.db.repositories.inventory_repo import InventoryRepository
from app.core.db.repositories.process_repo import ProcessRepository
from app.core.db.site_guard import SiteScopeError
from app.core.security.tenant_scope import unscoped
from app.features.crm.services.sales_traceability_service import SalesTraceabilityService
from tests.factories import InventoryItemFactory, ProcessFactory
from tests.test_sites import _add, _enable, flask_app, world  # noqa: F401 -- shared fixtures


@pytest.fixture
def released(world, db):  # noqa: F811 -- pytest fixture injection
    org, admin, other, neighbour = world
    default = _enable(admin)
    additional = _add(admin)
    with unscoped():
        db.get(Organisation, org.id).multiple_site_operations_enabled = True
        db.commit()
    return org, admin, other, neighbour, default, additional


def test_guarded_named_site_api_creation_and_strict_scope(released, db):
    org, admin, _, neighbour, _, additional = released
    foreign = _enable(neighbour)
    for site in (foreign["id"], "bad", str(uuid4()), None):
        assert admin.post("/api/core/stock-locations", json={"name": "A place", "site_id": site}).status_code == 400
    location = admin.post("/api/core/stock-locations", json={"name": "North tank", "site_id": additional["id"]})
    assert location.status_code == 201
    stock = admin.post(
        "/api/core/inventory", json={"name": "Botanicals", "quantity": "12", "unit": "kg", "site_id": additional["id"]}
    )
    assert stock.status_code == 201, stock.get_json()
    with unscoped():
        assert str(db.get(InventoryItem, stock.get_json()["id"]).site_id) == additional["id"]
        process = ProcessFactory(org_id=org.id)
    execution = admin.post("/api/core/executions", json={"process_id": str(process.id), "site_id": additional["id"]})
    assert execution.status_code == 201, execution.get_json()
    assert admin.put("/api/core/sites/settings", json={"enabled": False}).status_code == 400


def test_fifo_and_manual_sales_default_or_explicit_shipping_site(released, db):
    org, _, _, _, default, additional = released
    with unscoped():
        local = InventoryItemFactory(
            org_id=org.id, name="House Gin", quantity="10", unit="bottles", inventory_type="final_product"
        )
        remote = InventoryItemFactory(
            org_id=org.id,
            name="House Gin",
            quantity="20",
            unit="bottles",
            inventory_type="final_product",
            site_id=UUID(additional["id"]),
            extra_data={"batch_number": 1},
        )
        repo = InventoryRepository(db)
        assert repo.consume_final_product_fifo(org.id, "House Gin", "4")[0]["inventory_item_id"] == str(local.id)
        assert remote.quantity == 20
        with pytest.raises(ValueError, match="shipping site"):
            repo.consume_final_product_lot(org.id, remote.id, "1")
        db.rollback()
        assert repo.consume_final_product_lot(org.id, remote.id, "3", site_id=UUID(additional["id"]))[
            "inventory_item_id"
        ] == str(remote.id)
        assert repo.consume_final_product_fifo(org.id, "House Gin", "2", site_id=UUID(additional["id"]))[0][
            "inventory_item_id"
        ] == str(remote.id)
        candidates = SalesTraceabilityService(db).lot_candidates(org.id, "House Gin")
        assert [row["inventory_item_id"] for row in candidates] == [str(local.id)]
        assert [
            row["inventory_item_id"]
            for row in SalesTraceabilityService(db).lot_candidates(org.id, "House Gin", site_id=UUID(additional["id"]))
        ] == [str(remote.id)]
        assert str(local.site_id) == default["id"]


def test_production_rejects_other_site_then_consumes_and_inherits(released, db):
    org, admin, _, _, _, additional = released
    with unscoped():
        process = ProcessFactory(org_id=org.id)
        ProcessRepository(db).add_step(
            process.id,
            org.id,
            step_number=1,
            position=1000,
            name="Make",
            inputs=[{"name": "Input", "quantity": 2, "unit": "kg"}],
            outputs=[{"name": "Finished", "quantity": 2, "unit": "kg"}],
        )
        execution = ExecutionRepository(db).create_execution(org.id, process.id, site_id=UUID(additional["id"]))
        step = execution.execution_steps[0]
        local = InventoryItemFactory(org_id=org.id, name="Input", quantity="10", unit="kg")
        remote = InventoryItemFactory(
            org_id=org.id, name="Input", quantity="10", unit="kg", site_id=UUID(additional["id"])
        )
    path = f"/api/core/executions/{execution.id}/steps/{step.id}/complete"
    body = {
        "actual_inputs": [{"inventory_item_id": str(local.id), "name": "Input", "quantity": 2, "unit": "kg"}],
        "actual_outputs": [{"name": "Finished", "quantity": 2, "unit": "kg"}],
        "allow_consumption_override": True,
    }
    failed = admin.post(path, json=body)
    assert failed.status_code == 400, failed.get_json()
    with unscoped():
        db.expire_all()
        assert local.quantity == remote.quantity == 10
        assert step.status == ExecutionStepStatus.READY
    body["actual_inputs"][0]["inventory_item_id"] = str(remote.id)
    success = admin.post(path, json=body)
    assert success.status_code == 200, success.get_json()
    with unscoped():
        db.expire_all()
        assert remote.quantity == 8 and local.quantity == 10
        output = (
            db.query(InventoryItem)
            .filter(InventoryItem.org_id == org.id, InventoryItem.source_execution_id == execution.id)
            .one()
        )
        assert str(output.site_id) == additional["id"]


def test_reconciliation_and_wrong_execution_url_do_not_bypass(released, db):
    org, _, other, _, _, additional = released
    with unscoped():
        process = ProcessFactory(org_id=org.id)
        ProcessRepository(db).add_step(process.id, org.id, step_number=1, position=1000, name="Make")
        repo = ExecutionRepository(db)
        execution = repo.create_execution(org.id, process.id, site_id=UUID(additional["id"]))
        step = execution.execution_steps[0]
        local = InventoryItemFactory(org_id=org.id, extra_data={"untracked": True})
        foreign = InventoryItemFactory(org_id=other.id)
        for output in ({"untracked_item_id": str(local.id)}, {"untracked_item_id": str(foreign.id)}):
            with pytest.raises(SiteScopeError, match="execution's site"):
                repo.complete_step(step.id, org.id, actual_outputs=[output])
            db.rollback()
        with pytest.raises(ValueError, match="does not belong"):
            repo.complete_step(step.id, org.id, execution_id=uuid4())
        db.rollback()
        assert step.status == ExecutionStepStatus.READY


def test_barcode_add_cannot_put_stock_in_the_wrong_site(released, db):
    org, admin, _, _, default, additional = released
    with unscoped():
        remote = InventoryItemFactory(
            org_id=org.id,
            name="Botanicals",
            quantity="10",
            unit="kg",
            barcode="SITES-TEST-123",
            site_id=UUID(additional["id"]),
        )
    body = {"barcode": remote.barcode, "quantity": "2"}
    for hint in ({}, {"site_id": default["id"]}):
        assert admin.post("/api/core/inventory", json={**body, **hint}).status_code == 400
    success = admin.post("/api/core/inventory", json={**body, "site_id": additional["id"]})
    assert success.status_code == 200, success.get_json()
    with unscoped():
        db.expire_all()
        assert remote.quantity == 12


def test_xero_default_shipping_and_explicit_manual_rematch(released, db):
    from app.features.crm.models.product_mapping import ProductMapping
    from app.features.crm.models.sales_fifo_allocation import SalesFifoAllocation
    from app.features.crm.models.xero_invoice import XeroInvoice
    from app.features.crm.models.xero_invoice_line_item import XeroInvoiceLineItem
    from tests.test_sales_traceability import _add_mapping, _add_sale

    org, admin, _, _, _, additional = released
    with unscoped():
        local = InventoryItemFactory(
            org_id=org.id, name="Gin", quantity="10", unit="bottles", inventory_type="final_product"
        )
        remote = InventoryItemFactory(
            org_id=org.id,
            name="Gin",
            quantity="20",
            unit="bottles",
            inventory_type="final_product",
            site_id=UUID(additional["id"]),
            extra_data={"batch_number": 1},
        )
        try:
            _add_mapping(db, org.id, product="Gin", pattern="Gin")
            invoice_id = "sites-sale-" + str(uuid4())
            _add_sale(db, org.id, invoice_id=invoice_id, description="Gin", quantity="2")
            service = SalesTraceabilityService(db)
            assert service.reconcile_org(org.id)["allocated"] == 1
            db.commit()

            assert local.quantity == 8 and remote.quantity == 20
            candidates = admin.get("/api/crm/matching/candidates", query_string={"product": "Gin"})
            assert candidates.status_code == 200, candidates.get_json()
            assert [row["inventory_item_id"] for row in candidates.get_json()["batches"]] == [str(local.id)]
            candidates = admin.get(
                "/api/crm/matching/candidates", query_string={"product": "Gin", "site_id": additional["id"]}
            )
            assert candidates.status_code == 200, candidates.get_json()
            assert [row["inventory_item_id"] for row in candidates.get_json()["batches"]] == [str(remote.id)]
            picks = [{"inventory_item_id": str(remote.id), "quantity": "2"}]
            with pytest.raises(ValueError, match="shipping site"):
                service.assign_line(org.id, invoice_id, invoice_id + "-line-1", picks)
            db.rollback()
            response = admin.post(
                "/api/crm/matching/assign",
                json={
                    "invoice_id": invoice_id,
                    "line_key": invoice_id + "-line-1",
                    "picks": picks,
                    "site_id": additional["id"],
                },
            )
            assert response.status_code == 200, response.get_json()
            db.expire_all()
            assert (
                db.query(SalesFifoAllocation).filter(SalesFifoAllocation.org_id == org.id).one().inventory_item_id
                == remote.id
            )
            assert local.quantity == 10 and remote.quantity == 18
        finally:
            db.rollback()
            for model in (SalesFifoAllocation, XeroInvoiceLineItem, XeroInvoice, ProductMapping):
                db.query(model).filter(model.org_id == org.id).delete(synchronize_session=False)
            db.commit()


def test_stale_organisation_cannot_bypass_opt_out(released):
    from app.core.db import SessionLocal
    from app.core.db.models.stock_location import StockLocation

    org, admin, _, _, _, additional = released
    with SessionLocal() as stale, unscoped():
        cached = stale.get(Organisation, org.id)
        assert cached.multiple_sites_enabled
        assert admin.put("/api/core/sites/settings", json={"enabled": False}).status_code == 200
        assert cached.multiple_sites_enabled  # deliberately stale identity map
        stale.add(StockLocation(org_id=org.id, name="Stale write", site_id=UUID(additional["id"])))
        with pytest.raises(SiteScopeError, match="not available"):
            stale.flush()
        stale.rollback()
