"""Plan item 1.1: owners choose how sales are matched to batches (FIFO, hybrid, manual)."""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest

from app.core.db.models.inventory_item import InventoryItem, InventoryType
from app.core.db.models.organisation import Organisation
from app.core.db.repositories.inventory_repo import InventoryRepository
from app.features.crm.models.product_mapping import ProductMapping
from app.features.crm.models.sales_fifo_allocation import SalesFifoAllocation
from app.features.crm.models.sales_traceability_config import SalesTraceabilityConfig
from app.features.crm.models.xero_invoice import XeroInvoice
from app.features.crm.models.xero_invoice_line_item import XeroInvoiceLineItem
from app.features.crm.services.sales_traceability_service import SalesTraceabilityService
from tests.dag_traversal_helpers import clear_org_synthetic_data
from tests.test_compliant_routes import _admin_client, flask_app  # noqa: F401 -- fixture re-export

PRODUCT = "Gin - final product"


@pytest.fixture
def world(db, flask_app):  # noqa: F811
    org, client = _admin_client(db, flask_app)
    repo = InventoryRepository(db)

    def lot(batch, qty, bottled_on):
        item = repo.create_inventory_item(
            org_id=org.id,
            name=PRODUCT,
            quantity=str(qty),
            unit="bottles",
            inventory_type=InventoryType.FINAL_PRODUCT.value,
            supplier_batch_number=batch,
            purchase_date=bottled_on,
            extra_data={"bottled_on": bottled_on.isoformat()},
            commit=True,
        )
        return item

    def mode(strategy, review_days=7):
        client.put(
            "/api/crm/traceability-config",
            json={"matching_strategy": strategy, "manual_review_days": review_days, "strict_mapping": False},
        )

    def invoice(day, qty, description="Gin 700ml"):
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
        line = XeroInvoiceLineItem(
            org_id=org.id,
            invoice_id=inv.id,
            xero_line_item_id=f"l-{uuid4()}",
            description=description,
            quantity=Decimal(qty),
        )
        db.add(line)
        db.commit()
        return inv, line

    def reconcile():
        summary = SalesTraceabilityService(db).reconcile_org(org.id)
        db.commit()
        return summary

    def allocations():
        return db.query(SalesFifoAllocation).filter(SalesFifoAllocation.org_id == org.id).all()

    client.post(
        "/api/crm/product-mappings",
        json={"biz_e_product_name": PRODUCT, "xero_description_pattern": "Gin 700ml", "match_type": "exact"},
    )
    yield {
        "org": org,
        "client": client,
        "lot": lot,
        "mode": mode,
        "invoice": invoice,
        "reconcile": reconcile,
        "allocations": allocations,
        "db": db,
    }

    db.rollback()
    for model in (SalesFifoAllocation, XeroInvoiceLineItem, XeroInvoice, ProductMapping, SalesTraceabilityConfig):
        db.query(model).filter(model.org_id == org.id).delete(synchronize_session=False)
    db.commit()
    clear_org_synthetic_data(db, org.id)
    db.query(Organisation).filter(Organisation.id == org.id).delete(synchronize_session=False)
    db.commit()


def test_fifo_marks_a_presale_but_just_works(world):
    world["mode"]("fifo")
    world["lot"]("VAT44", 10, date(2026, 10, 20))  # bottled after the invoice
    world["invoice"](date(2026, 10, 5), "4")
    summary = world["reconcile"]()
    assert summary["allocated"] == 1 and summary["presold"] == 1
    (allocation,) = world["allocations"]()
    assert allocation.presold is True and allocation.status == "confirmed"


def test_hybrid_holds_presales_for_review_then_confirms_them(world):
    world["mode"]("hybrid", review_days=3)
    world["lot"]("VAT40", 10, date(2026, 9, 1))
    world["lot"]("VAT44", 10, date(2026, 10, 20))
    world["invoice"](date(2026, 10, 1), "4")  # VAT40 existed: normal
    presold_inv, _ = world["invoice"](date(2026, 10, 2), "10")  # needs VAT44: pre-sold
    world["reconcile"]()
    by_invoice = {}
    for a in world["allocations"]():
        by_invoice.setdefault(a.xero_invoice_id, []).append(a)
    statuses = {inv: {a.status for a in rows} for inv, rows in by_invoice.items()}
    assert statuses[presold_inv.xero_invoice_id] == {"pending_review"}
    assert sum(1 for s in statuses.values() if s == {"confirmed"}) == 1

    queue = world["client"].get("/api/crm/matching").get_json()
    assert queue["mode"] == "hybrid"
    (line,) = queue["pending_review"]
    assert line["presold"] is True and line["invoice_id"] == presold_inv.xero_invoice_id

    # After the review window, the match confirms itself on the next run.
    for a in by_invoice[presold_inv.xero_invoice_id]:
        a.review_due_at = datetime.now(UTC) - timedelta(minutes=1)
    world["db"].commit()
    summary = world["reconcile"]()
    assert summary.get("auto_confirmed") == 1
    assert {a.status for a in world["allocations"]()} == {"confirmed"}


def test_hybrid_reviews_loose_mappings_and_owner_can_confirm(world):
    world["mode"]("hybrid")
    world["client"].post(
        "/api/crm/product-mappings",
        json={"biz_e_product_name": PRODUCT, "xero_description_pattern": "Wildflower", "match_type": "contains"},
    )
    world["lot"]("VAT40", 10, date(2026, 9, 1))
    inv, line = world["invoice"](date(2026, 10, 1), "2", description="Whistlebird Wildflower 700ml - x1")
    world["reconcile"]()
    assert {a.status for a in world["allocations"]()} == {"pending_review"}
    ok = world["client"].post(
        "/api/crm/matching/confirm", json={"invoice_id": inv.xero_invoice_id, "line_key": line.xero_line_item_id}
    )
    assert ok.status_code == 200
    assert {a.status for a in world["allocations"]()} == {"confirmed"}


def test_manual_mode_waits_for_the_owner_to_pick_batches(world):
    world["mode"]("manual")
    old = world["lot"]("VAT40", 10, date(2026, 9, 1))
    new = world["lot"]("VAT44", 10, date(2026, 10, 20))
    inv, line = world["invoice"](date(2026, 10, 25), "6")
    summary = world["reconcile"]()
    assert summary.get("awaiting_assignment") == 1 and world["allocations"]() == []

    client = world["client"]
    queue = client.get("/api/crm/matching").get_json()
    assert [row["invoice_id"] for row in queue["to_assign"]] == [inv.xero_invoice_id]
    assert queue["to_assign"][0]["quantity"] == "6"

    candidates = client.get(f"/api/crm/matching/candidates?product={PRODUCT}").get_json()["batches"]
    assert [c["batch"] for c in candidates] == ["VAT40", "VAT44"]  # oldest first

    ref = {"invoice_id": inv.xero_invoice_id, "line_key": line.xero_line_item_id}
    short = client.post(
        "/api/crm/matching/assign", json={**ref, "picks": [{"inventory_item_id": str(new.id), "quantity": "5"}]}
    )
    assert short.status_code == 400 and "add up to 6" in short.get_json()["error"]
    too_much = client.post(
        "/api/crm/matching/assign", json={**ref, "picks": [{"inventory_item_id": str(old.id), "quantity": "11"}]}
    )
    assert too_much.status_code == 400

    ok = client.post(
        "/api/crm/matching/assign",
        json={
            **ref,
            "picks": [
                {"inventory_item_id": str(new.id), "quantity": "4"},
                {"inventory_item_id": str(old.id), "quantity": "2"},
            ],
        },
    )
    assert ok.status_code == 200, ok.get_json()
    rows = {str(a.inventory_item_id): Decimal(str(a.quantity)) for a in world["allocations"]()}
    assert rows == {str(new.id): 4, str(old.id): 2}
    db = world["db"]
    db.expire_all()
    assert Decimal(str(db.get(InventoryItem, new.id).quantity)) == 6
    # A later run leaves the owner's choice alone.
    assert world["reconcile"]().get("already_allocated") == 1


def test_owner_can_change_the_batch_on_an_automatic_match(world):
    world["mode"]("fifo")
    old = world["lot"]("VAT40", 10, date(2026, 9, 1))
    new = world["lot"]("VAT44", 10, date(2026, 9, 20))
    inv, line = world["invoice"](date(2026, 10, 1), "3")
    world["reconcile"]()
    assert {str(a.inventory_item_id) for a in world["allocations"]()} == {str(old.id)}  # FIFO took the oldest

    moved = world["client"].post(
        "/api/crm/matching/assign",
        json={
            "invoice_id": inv.xero_invoice_id,
            "line_key": line.xero_line_item_id,
            "picks": [{"inventory_item_id": str(new.id), "quantity": "3"}],
        },
    )
    assert moved.status_code == 200
    db = world["db"]
    db.expire_all()
    assert Decimal(str(db.get(InventoryItem, old.id).quantity)) == 10  # put back
    assert Decimal(str(db.get(InventoryItem, new.id).quantity)) == 7


def test_sale_nodes_carry_presold_and_review_status(world):
    from app.features.crm.services.sales_traceability_service import append_sales_to_dag

    world["mode"]("hybrid")
    lot = world["lot"]("VAT44", 10, date(2026, 10, 20))
    world["invoice"](date(2026, 10, 2), "1")
    world["reconcile"]()
    nodes, _edges = append_sales_to_dag(world["db"], world["org"].id, {str(lot.id)})
    (node,) = nodes
    assert node["presold"] is True and node["match_status"] == "pending_review"
