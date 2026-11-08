"""Moving stock in a browser (GL-P07 A4): from a line in Inventory to another area (one step) or
another site (a dispatch), then receiving it in one click on Stock transfers.

Requests are routed into the Flask test client (see test_crm_contact_sync_ui). No compliance
module is installed here, so the movement policy allows everything and asks nothing.
"""

from __future__ import annotations

import pytest
from playwright.sync_api import expect

from app.core.db.models.inventory_movement import InventoryMovement
from app.core.db.models.site_transfer import SiteStockReceipt, SiteStockTransfer
from app.core.db.models.stock_location import StockLocation, StockTransfer
from app.core.db.models.user import UserRole
from app.core.security.tenant_scope import unscoped
from tests.dag_traversal_helpers import clear_org_synthetic_data
from tests.e2e.test_crm_contact_sync_ui import client, sales_page  # noqa: F401 -- fixture re-export
from tests.factories import grant_multi_site
from tests.test_crm import db, org  # noqa: F401 -- fixture re-export
from tests.test_crm import user as _member  # noqa: F401 -- fixture re-export

pytestmark = pytest.mark.e2e

BASE = "https://crm.test"
ROWS = "#inv-view-tbody tr"


@pytest.fixture()
def user(_member, db):  # noqa: F811
    _member.role = UserRole.ADMIN
    db.commit()
    grant_multi_site(db, _member.org_id)
    return _member


@pytest.fixture(autouse=True)
def _clean(org, db):  # noqa: F811
    yield
    db.rollback()
    from sqlalchemy import text

    with unscoped():
        db.execute(text("SELECT set_config('app.migration_mode','1',true)"))
        db.query(InventoryMovement).filter(InventoryMovement.org_id == org.id).delete(synchronize_session=False)
        db.execute(
            text(
                "UPDATE inventory_items SET supplier_batch_number = CASE WHEN transfer_receipt_id IS NOT NULL "
                "THEN NULL ELSE supplier_batch_number END, transfer_receipt_id = NULL WHERE org_id = :org"
            ),
            {"org": org.id},
        )
        db.query(SiteStockReceipt).filter(SiteStockReceipt.org_id == org.id).delete(synchronize_session=False)
        db.query(SiteStockTransfer).filter(SiteStockTransfer.org_id == org.id).delete(synchronize_session=False)
        db.query(StockTransfer).filter(StockTransfer.org_id == org.id).delete(synchronize_session=False)
        clear_org_synthetic_data(db, org.id)
        db.query(StockLocation).filter(StockLocation.org_id == org.id).delete(synchronize_session=False)
        db.commit()


def _setup(client):  # noqa: F811
    assert client.put("/api/core/sites/settings", json={"enabled": True}).status_code == 200
    main = client.get("/api/core/sites/choices").get_json()["sites"][0]
    bond = client.post("/api/core/sites", json={"name": "Bond store", "kind": "storage"}).get_json()
    bay = client.post(
        "/api/core/stock-locations", json={"name": "Bay 1", "site_id": main["id"], "inside_licensed_area": True}
    ).get_json()
    body = {"name": "Juniper", "quantity": "10", "unit": "kg", "inventory_type": "raw_material"}
    assert client.post("/api/core/inventory", json=body).status_code == 201
    return main, bond, bay


def _open_line(page, name="Juniper"):
    page.set_viewport_size({"width": 1440, "height": 900})
    page.goto(f"{BASE}/core/inventory/view")
    page.locator(ROWS).first.wait_for()
    page.locator(ROWS, has_text=name).first.locator(".inv-row__open").click()


def test_moving_to_another_area_here_is_one_step(sales_page, client):  # noqa: F811
    main, _, bay = _setup(client)
    _open_line(sales_page)
    sales_page.locator("[data-inv-move]").click()
    dialog = sales_page.locator("[data-move-dialog]")
    dialog.locator("#mv-to").select_option(f"{main['id']}|{bay['id']}")
    # Same site, same side of the licensed boundary: no carrier, no docket.
    expect(dialog.locator("#mv-carrier")).to_be_hidden()
    dialog.locator("#mv-quantity").fill("4")
    dialog.get_by_role("button", name="Move", exact=True).click()
    expect(sales_page.locator("[data-inv-moved]")).to_have_text("Moved to Bay 1.")
    expect(sales_page.locator(ROWS, has_text="Bay 1")).to_have_count(1)
    assert client.get("/api/core/site-transfers").get_json()["transfers"] == []


def test_another_site_is_a_dispatch_received_in_one_click(sales_page, client):  # noqa: F811
    _, bond, _ = _setup(client)
    _open_line(sales_page)
    sales_page.locator("[data-inv-move]").click()
    dialog = sales_page.locator("[data-move-dialog]")
    dialog.locator("#mv-to").select_option(f"{bond['id']}|")
    dialog.locator("#mv-carrier").fill("Own van")
    dialog.get_by_role("button", name="Dispatch", exact=True).click()
    expect(sales_page.locator("[data-inv-moved]")).to_contain_text("On its way to Bond store")
    sales_page.locator("[data-inv-moved] a").click()
    card = sales_page.locator("[data-transfer-id]")
    expect(card).to_contain_text("In transit")
    card.locator("[data-tr-full]").click()
    expect(sales_page.locator("[data-transfers-done]")).to_contain_text("receipt recorded at Bond store")
    expect(card).to_contain_text("Received")
    lines = client.get(f"/api/core/inventory?site_id={bond['id']}").get_json()["inventory_items"]
    assert [(i["name"], i["quantity"]) for i in lines] == [("Juniper", "10")]


def test_a_refused_move_stays_in_the_dialog(sales_page, client):  # noqa: F811
    _setup(client)
    _open_line(sales_page)
    sales_page.locator("[data-inv-move]").click()
    dialog = sales_page.locator("[data-move-dialog]")
    dialog.locator("#mv-quantity").fill("11")
    dialog.locator("#mv-to").select_option(index=1)
    dialog.get_by_role("button", name="Move", exact=True).click()
    expect(dialog.locator(".mv-error")).to_have_text("Move between 0 and 10 kg.")
    expect(dialog).to_be_visible()


def test_a_single_site_business_is_not_offered_a_move(sales_page, client):  # noqa: F811
    body = {"name": "Juniper", "quantity": "10", "unit": "kg", "inventory_type": "raw_material"}
    assert client.post("/api/core/inventory", json=body).status_code == 201
    _open_line(sales_page)
    expect(sales_page.locator("[data-inv-drawer]")).to_be_visible()
    expect(sales_page.locator("[data-inv-move]")).to_have_count(0)


@pytest.mark.parametrize("width", [390, 1440, 1920], ids=["phone", "laptop", "wall"])
def test_stock_transfers_fits_and_receives(sales_page, client, width):  # noqa: F811
    _, bond, _ = _setup(client)
    juniper = client.get("/api/core/inventory").get_json()["inventory_items"][0]
    made = client.post(
        "/api/core/site-transfers",
        json={
            "source_item_id": juniper["id"],
            "destination_site_id": bond["id"],
            "quantity": "3",
            "carrier": "Own van",
            "consignment_reference": "MV-1",
            "occurred_on": juniper["created_at"][:10],
            "approval": {},
        },
        headers={"Idempotency-Key": f"fit-{width}"},
    )
    assert made.status_code == 201, made.get_json()
    sales_page.set_viewport_size({"width": width, "height": 900})
    sales_page.goto(f"{BASE}/core/site-transfers")
    sales_page.locator("[data-transfers-root][aria-busy='false']").wait_for()
    assert sales_page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    receive = sales_page.locator("[data-tr-full]")
    expect(receive).to_have_count(1)  # never offered on the sending side
    receive.click()
    expect(sales_page.locator("[data-transfers-done]")).to_contain_text("receipt recorded")
