"""Plan item 1.3: go live with a stocktake instead of reconstructing history."""

from datetime import date, timedelta
from decimal import Decimal
from uuid import uuid4

from app.core.db.models.entity_event import EntityEvent
from app.core.db.models.inventory_item import InventoryItem, InventoryType
from app.core.db.models.organisation import Organisation
from app.core.db.models.user import UserRole
from app.core.db.repositories.inventory_repo import InventoryRepository
from app.core.db.repositories.process_repo import ProcessRepository
from app.core.db.repositories.user_repo import UserRepository
from app.core.security.auth_service import AuthService
from tests.dag_traversal_helpers import clear_org_synthetic_data
from tests.factories import DEFAULT_TEST_PASSWORD
from tests.test_compliant_routes import _admin_client, flask_app  # noqa: F401 -- fixture re-export


def _gin_workflow(db, org_id):
    repo = ProcessRepository(db)
    gin = repo.create_process(org_id=org_id, name="Gin", description="", is_draft=False)
    repo.add_step(
        process_id=gin.id,
        org_id=org_id,
        step_number=1,
        position=1000,
        name="Macerate",
        inputs=[],
        outputs=[{"name": "Aged gin", "quantity": "60", "unit": "L"}],
        execution_prompts=[],
    )
    repo.add_step(
        process_id=gin.id,
        org_id=org_id,
        step_number=2,
        position=2000,
        name="Bottle",
        inputs=[],
        outputs=[{"name": "Gin - final product", "quantity": "80", "unit": "bottles"}],
        execution_prompts=[],
    )
    db.commit()
    return gin


def _cleanup(db, org_id):
    db.rollback()
    from app.features.crm.models.product_mapping import ProductMapping
    from app.features.crm.models.sales_fifo_allocation import SalesFifoAllocation
    from app.features.crm.models.xero_invoice import XeroInvoice
    from app.features.crm.models.xero_invoice_line_item import XeroInvoiceLineItem

    for model in (SalesFifoAllocation, XeroInvoiceLineItem, XeroInvoice, ProductMapping):
        db.query(model).filter(model.org_id == org_id).delete(synchronize_session=False)
    db.commit()
    clear_org_synthetic_data(db, org_id)
    db.query(Organisation).filter(Organisation.id == org_id).delete(synchronize_session=False)
    db.commit()


def test_status_lists_final_and_in_progress_outputs(db, flask_app):  # noqa: F811
    org, client = _admin_client(db, flask_app)
    try:
        _gin_workflow(db, org.id)
        status = client.get("/api/core/go-live").get_json()
        assert status["go_live_date"] is None
        assert [o["name"] for o in status["final_outputs"]] == ["Gin - final product"]
        assert status["final_outputs"][0]["counted"] is True
        assert [o["name"] for o in status["intermediate_outputs"]] == ["Aged gin"]
        assert status["workflow_count"] == 1
    finally:
        _cleanup(db, org.id)


def test_opening_stock_needs_a_go_live_date_and_is_validated(db, flask_app):  # noqa: F811
    org, client = _admin_client(db, flask_app)
    try:
        _gin_workflow(db, org.id)
        row = {"name": "Gin - final product", "quantity": "44", "batch_id": "VAT44", "abv_percent": "44"}
        assert client.post("/api/core/opening-stock", json={"items": [row]}).status_code == 409
        assert client.put("/api/core/go-live", json={"go_live_date": "not-a-date"}).status_code == 400
        assert client.put("/api/core/go-live", json={"go_live_date": "2026-10-01"}).status_code == 200

        half = client.post("/api/core/opening-stock", json={"items": [{**row, "quantity": "44.5"}]})
        assert half.status_code == 400 and "whole numbers" in half.get_json()["error"]
        strong = client.post("/api/core/opening-stock", json={"items": [{**row, "abv_percent": "140"}]})
        assert strong.status_code == 400
        # All or nothing: a bad row stops the good one too.
        assert db.query(InventoryItem).filter(InventoryItem.org_id == org.id).count() == 0

        ok = client.post(
            "/api/core/opening-stock",
            json={
                "items": [
                    row,
                    {"name": "Gin - final product - Library stock", "unit": "ml", "quantity": "350"},
                    {
                        "name": "Aged gin",
                        "unit": "L",
                        "quantity": "120",
                        "inventory_type": "work_in_progress",
                        "abv_percent": "63",
                        "batch_id": "Barrel 3",
                    },
                ]
            },
        )
        assert ok.status_code == 201, ok.get_json()
        body = ok.get_json()
        assert body["created"] == 3
        by_name = {i["name"]: i for i in body["opening_items"]}
        assert by_name["Gin - final product"]["batch_id"] == "VAT44"
        assert by_name["Gin - final product"]["unit"] == "bottles"  # taken from the workflow
        assert by_name["Aged gin"]["inventory_type"] == InventoryType.WORK_IN_PROGRESS.value

        bottles = (
            db.query(InventoryItem)
            .filter(InventoryItem.org_id == org.id, InventoryItem.name == "Gin - final product")
            .one()
        )
        assert bottles.extra_data["opening_stock"] is True
        assert bottles.extra_data["opening_as_of"] == "2026-10-01"
        event = db.query(EntityEvent).filter(EntityEvent.entity_id == bottles.id).first()
        assert event.payload["add_method"] == "opening_stock"
        # Opening stock is not a traceability gap, even the WIP with no batch lineage.
        gaps = InventoryRepository(db).list_traceability_gap_items(org.id, limit=50)
        assert not any((g.extra_data or {}).get("opening_stock") for g in gaps)
    finally:
        _cleanup(db, org.id)


def test_only_admins_set_the_go_live_date(db, flask_app):  # noqa: F811
    org, _client = _admin_client(db, flask_app)
    try:
        email = f"staff_{uuid4()}@example.test"
        UserRepository(db).create_user(
            org_id=org.id,
            email=email,
            password_hash=AuthService.hash_password(DEFAULT_TEST_PASSWORD),
            role=UserRole.MEMBER,
        )
        db.commit()
        staff = flask_app.test_client()
        staff.environ_base["wsgi.url_scheme"] = "https"
        staff.environ_base["HTTP_X_FORWARDED_PROTO"] = "https"
        staff.post("/auth/login", json={"email": email, "password": DEFAULT_TEST_PASSWORD})
        assert staff.put("/api/core/go-live", json={"go_live_date": "2026-10-01"}).status_code == 403
        assert staff.get("/api/core/go-live").status_code == 200
    finally:
        _cleanup(db, org.id)


def test_sales_before_go_live_are_reported_but_not_matched(db, flask_app):  # noqa: F811
    from app.features.crm.models.sales_fifo_allocation import SalesFifoAllocation
    from app.features.crm.models.xero_invoice import XeroInvoice
    from app.features.crm.models.xero_invoice_line_item import XeroInvoiceLineItem
    from app.features.crm.services.sales_traceability_service import SalesTraceabilityService

    org, client = _admin_client(db, flask_app)
    try:
        _gin_workflow(db, org.id)
        go_live = date(2026, 10, 1)
        client.put("/api/core/go-live", json={"go_live_date": go_live.isoformat()})
        client.post(
            "/api/core/opening-stock",
            json={
                "items": [
                    {"name": "Gin - final product", "quantity": "40", "batch_id": "VAT44", "bottled_on": "2026-08-01"}
                ]
            },
        )
        # A batch bottled after go-live, recorded the normal way.
        InventoryRepository(db).create_inventory_item(
            org_id=org.id,
            name="Gin - final product",
            quantity="80",
            unit="bottles",
            inventory_type=InventoryType.FINAL_PRODUCT.value,
            supplier_batch_number="VAT60",
        )
        db.commit()
        client.post(
            "/api/crm/product-mappings",
            json={
                "biz_e_product_name": "Gin - final product",
                "xero_description_pattern": "Gin 700ml",
                "match_type": "exact",
            },
        )

        def invoice(day, qty):
            inv = XeroInvoice(
                org_id=org.id,
                xero_invoice_id=f"inv-{uuid4()}",
                xero_tenant_id="t",
                invoice_type="ACCREC",
                status="AUTHORISED",
                invoice_number=f"INV-{uuid4().hex[:4]}",
                date=day,
            )
            db.add(inv)
            db.flush()
            db.add(
                XeroInvoiceLineItem(
                    org_id=org.id,
                    invoice_id=inv.id,
                    xero_line_item_id=f"l-{uuid4()}",
                    description="Gin 700ml",
                    quantity=Decimal(qty),
                )
            )
            return inv

        before = invoice(go_live - timedelta(days=3), "6")
        after = invoice(go_live + timedelta(days=2), "10")
        db.commit()

        summary = SalesTraceabilityService(db).reconcile_org(org.id)
        db.commit()
        assert summary.get("before_go_live") == 1, summary
        assert summary.get("allocated") == 1, summary

        allocations = db.query(SalesFifoAllocation).filter(SalesFifoAllocation.org_id == org.id).all()
        assert {a.xero_invoice_id for a in allocations} == {after.xero_invoice_id}
        assert before.xero_invoice_id not in {a.xero_invoice_id for a in allocations}
        # The sale after go-live came out of the opening batch first (oldest first).
        opening = (
            db.query(InventoryItem)
            .filter(InventoryItem.org_id == org.id, InventoryItem.supplier_batch_number == "VAT44")
            .one()
        )
        assert Decimal(str(opening.quantity)) == 30
    finally:
        _cleanup(db, org.id)
