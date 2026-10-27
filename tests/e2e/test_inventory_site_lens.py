"""Inventory with several sites, in a browser (GL-P07 A3): where each line is, narrowing to one
site, the add form opening on the site you last used, and a single-site business seeing the page
exactly as before.

Requests are routed into the Flask test client (see test_crm_contact_sync_ui).
"""

from __future__ import annotations

import pytest
from playwright.sync_api import expect

from app.core.db.models.api_idempotency_key import ApiIdempotencyKey
from app.core.db.models.stock_location import StockLocation
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
def _clean_stock(org, db):  # noqa: F811
    """These tests record stock; the shared org fixture only expects an empty organisation."""
    yield
    db.rollback()
    with unscoped():
        # A save sent with an Idempotency-Key leaves its replay record behind.
        db.query(ApiIdempotencyKey).filter(ApiIdempotencyKey.org_id == org.id).delete(synchronize_session=False)
        clear_org_synthetic_data(db, org.id)
        db.query(StockLocation).filter(StockLocation.org_id == org.id).delete(synchronize_session=False)
        db.commit()


def _two_sites(client):  # noqa: F811
    assert client.put("/api/core/sites/settings", json={"enabled": True}).status_code == 200
    bond = client.post("/api/core/sites", json={"name": "Bond store", "kind": "storage"}).get_json()
    body = {"quantity": "5", "unit": "kg", "inventory_type": "raw_material"}
    assert client.post("/api/core/inventory", json={**body, "name": "Juniper"}).status_code == 201
    assert client.post("/api/core/inventory", json={**body, "name": "Orris", "site_id": bond["id"]}).status_code == 201
    return bond


def _open(page, width=1440):
    page.set_viewport_size({"width": width, "height": 900})
    page.goto(f"{BASE}/core/inventory/view")
    page.locator(ROWS).first.wait_for()


def test_a_single_site_business_sees_no_site_controls(sales_page, client):  # noqa: F811
    body = {"name": "Juniper", "quantity": "5", "unit": "kg", "inventory_type": "raw_material"}
    assert client.post("/api/core/inventory", json=body).status_code == 201
    _open(sales_page)
    expect(sales_page.locator(".inv-th--where")).to_have_count(0)
    expect(sales_page.locator("[data-inv-sites]")).to_be_hidden()
    sales_page.goto(f"{BASE}/core/inventory/add/manual")
    sales_page.locator("#add-inventory-name").wait_for()
    expect(sales_page.locator("[data-site-select]")).to_have_count(0)


def test_each_line_says_where_and_a_site_tab_narrows_the_list(sales_page, client):  # noqa: F811
    _two_sites(client)
    _open(sales_page)
    expect(sales_page.locator(ROWS)).to_have_count(2)
    expect(sales_page.locator(ROWS, has_text="Orris").locator(".inv-cell-where")).to_have_text("Bond store")
    sales_page.locator(".inv-site-tab", has_text="Bond store").click()
    expect(sales_page.locator(ROWS)).to_have_count(1)
    expect(sales_page.locator("#inv-view-count")).to_have_text("1 line on hand at Bond store")
    # The choice is in the address, so a refresh or a shared link keeps it.
    assert "site=" in sales_page.url
    sales_page.reload()
    expect(sales_page.locator(ROWS)).to_have_count(1)


def test_the_add_form_opens_on_the_site_last_used(sales_page, client, db):  # noqa: F811
    bond = _two_sites(client)
    sales_page.goto(f"{BASE}/core/inventory/add/manual")
    select = sales_page.locator("[data-site-select]")
    expect(select).to_have_value(client.get("/api/core/sites/choices").get_json()["default_id"])
    sales_page.locator("#add-inventory-name").fill("Cassia bark")
    sales_page.locator("#add-inventory-quantity").fill("2")
    select.select_option(bond["id"])
    with sales_page.expect_response(
        lambda r: r.url.endswith("/api/core/inventory") and r.request.method == "POST"
    ) as sent:
        sales_page.locator("#add-inv-manual-submit-btn").click()
    assert sent.value.status == 201
    lines = {i["name"]: i for i in client.get("/api/core/inventory").get_json()["inventory_items"]}
    assert lines["Cassia bark"]["site_id"] == bond["id"]
    sales_page.goto(f"{BASE}/core/inventory/add/manual")
    expect(sales_page.locator("[data-site-select]")).to_have_value(bond["id"])


@pytest.mark.parametrize("width", [390, 1440, 1920], ids=["phone", "laptop", "wall"])
def test_the_site_tabs_fit_and_narrow(sales_page, client, width):  # noqa: F811
    _two_sites(client)
    _open(sales_page, width=width)
    assert sales_page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    sales_page.locator(".inv-site-tab", has_text="Bond store").click()
    expect(sales_page.locator(ROWS)).to_have_count(1)
    expect(sales_page.locator(ROWS).first).to_contain_text("Orris")
