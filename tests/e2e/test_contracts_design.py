"""Contract orders lead with the orders; the forms wait behind their buttons; dates read in words."""

from datetime import date, timedelta
from uuid import UUID

import pytest
from playwright.sync_api import expect

from app.core.db import db_session
from app.core.db.models.user import UserRole
from app.features.contract_manufacturing.models.orders import ContractOrder
from tests.e2e.conftest import csrf_headers, login_through_ui

pytestmark = pytest.mark.e2e


def _due(days):
    return date.today() + timedelta(days=days)


@pytest.fixture
def contracts_page(browser, app_url, fresh_user):
    """A sales admin with two customers (one inactive) and orders overdue, soon, later and cancelled."""
    admin = fresh_user(UserRole.ADMIN)
    context = browser.new_context(base_url=app_url, ignore_https_errors=True, viewport={"width": 1440, "height": 900})
    page = context.new_page()
    login_through_ui(page, admin["email"], admin["password"])
    headers = csrf_headers(page)

    def customer(name, active=True):
        made = page.request.post("/api/core/contract-customers", headers=headers, data={"name": name})
        assert made.status == 201, made.text()
        found = made.json()["customer"]
        if not active:
            assert page.request.patch(
                f"/api/core/contract-customers/{found['id']}", headers=headers, data={"is_active": False}
            ).ok
        return found["id"]

    def order(customer_id, reference, quantity, status="confirmed", unit="bottles"):
        made = page.request.post(
            "/api/core/contract-orders",
            headers=headers,
            data={
                "customer_id": customer_id,
                "reference": reference,
                "due_date": _due(30).isoformat(),
                "status": "confirmed" if status == "cancelled" else status,
                "duty_responsibility": "producer_licensee",
                "lines": [
                    {
                        "product_name": "Navy Gin 700 mL",
                        "quantity": quantity,
                        "unit": unit,
                        "materials_source": "producer",
                    }
                ],
            },
        )
        assert made.status == 201, made.text()
        found = made.json()["order"]
        if status == "cancelled":
            assert page.request.patch(
                f"/api/core/contract-orders/{found['id']}", headers=headers, data={"status": "cancelled"}
            ).ok
        return found["id"]

    harbour = customer("Harbour Spirits Co.")
    customer("Old Mill Brewing", active=False)
    ids = {
        "late": order(harbour, "HS-1", "600"),
        "soon": order(harbour, "HS-2", "240.5", unit="L"),
        "later": order(harbour, "HS-3", "300", status="draft"),
        "gone": order(harbour, "HS-4", "100", status="cancelled"),
    }
    # The API only takes future dates; an order goes overdue by time passing, so set the dates here.
    session = db_session()
    for key, days in [("late", -3), ("soon", 1), ("later", 21)]:
        session.query(ContractOrder).filter(
            ContractOrder.id == UUID(ids[key]), ContractOrder.org_id == UUID(admin["org_id"])
        ).update({"due_date": _due(days)})
    session.commit()
    yield page
    context.close()


def _open(page, style=None):
    page.goto("/core/contracts" + (f"?style={style}" if style else ""))
    expect(page.locator("[data-contracts-root]")).to_be_visible()


def test_orders_say_when_they_are_due_and_what_they_hold(contracts_page):
    page = contracts_page
    _open(page)
    rows = page.locator(".contracts-table-open tbody tr")
    expect(rows).to_have_count(3)
    expect(rows.locator(".contracts-due")).to_have_text(
        ["3 days overdue", "Due tomorrow", rows.nth(2).locator(".contracts-due").inner_text()]
    )
    expect(rows.nth(0).locator(".contracts-due")).to_have_attribute("data-state", "overdue")
    expect(rows.nth(0).locator(".contracts-due")).to_have_attribute("title", _due(-3).isoformat())
    assert not rows.nth(2).locator(".contracts-due").inner_text().startswith("Due in")
    # Quantities lose their padding zeros; a real fraction stays.
    expect(rows.nth(0)).to_contain_text("600 bottles Navy Gin 700 mL")
    expect(rows.nth(1)).to_contain_text("240.5 L")
    assert "600.0000" not in page.locator("[data-contracts-root]").inner_text()
    expect(rows.locator(".contracts-status")).to_have_text(["Confirmed", "Confirmed", "Draft"])
    # The figures count open orders only.
    expect(page.locator('[data-figure="open"]')).to_have_text("3")
    expect(page.locator('[data-figure="overdue"]')).to_have_text("1")
    expect(page.locator('[data-figure="week"]')).to_have_text("1")


def test_closed_orders_wait_in_their_own_list(contracts_page):
    page = contracts_page
    _open(page)
    closed = page.locator("details.contracts-closed")
    expect(closed.locator("summary")).to_have_text("Completed and cancelled (1)")
    expect(closed.locator("tbody tr")).to_be_hidden()
    closed.locator("summary").click()
    expect(closed.locator("tbody tr")).to_contain_text("HS-4")
    expect(closed.locator(".contracts-status")).to_have_text("Cancelled")


def test_new_order_form_waits_behind_its_button_in_four_named_groups(contracts_page):
    page = contracts_page
    _open(page)
    form_card = page.locator("#contracts-new-order")
    expect(form_card).to_be_hidden()
    toggle = page.locator(".workspace-header").get_by_role("button", name="New order", exact=True)
    toggle.click()
    expect(form_card).to_be_visible()
    expect(toggle).to_have_attribute("aria-expanded", "true")
    expect(form_card.locator("legend")).to_have_text(
        ["Customer and reference", "Product and quantity", "Materials and specification", "Duty and status"]
    )
    # Only active customers can take a new order.
    options = form_card.locator('[name="customer_id"] option').all_inner_texts()
    assert "Harbour Spirits Co." in options and "Old Mill Brewing" not in options
    form_card.get_by_role("button", name="Close", exact=True).click()
    expect(form_card).to_be_hidden()
    expect(toggle).to_be_focused()


def test_creating_an_order_from_the_form_opens_it(contracts_page):
    page = contracts_page
    _open(page)
    page.locator(".workspace-header").get_by_role("button", name="New order", exact=True).click()
    form = page.locator("#contracts-new-order form")
    form.locator('[name="customer_id"]').select_option(label="Harbour Spirits Co.")
    form.get_by_label("Order reference").fill("HS-9")
    form.get_by_label("Due date").fill(_due(10).isoformat())
    form.get_by_label("Product", exact=True).fill("Pink Gin 700 mL")
    form.get_by_label("Quantity").fill("120")
    form.get_by_label("Unit").fill("bottles")
    form.locator('[name="line.materials_source"]').select_option("producer")
    form.locator('[name="duty_responsibility"]').select_option("producer_licensee")
    form.get_by_role("button", name="Create order", exact=True).click()
    page.wait_for_url("**/core/contracts/*")
    expect(page.locator("body")).to_contain_text("HS-9")


def test_customers_list_their_state_and_edit_behind_a_disclosure(contracts_page):
    page = contracts_page
    _open(page)
    customers = page.get_by_role("region", name="Contract customers", exact=True)
    rows = customers.locator(".contracts-customer")
    expect(rows).to_have_count(2)
    expect(rows.nth(0)).to_contain_text("Harbour Spirits Co.")
    expect(rows.nth(0)).to_contain_text("3 open orders")
    expect(rows.nth(1).locator(".contracts-status")).to_have_text("Not taking new orders")
    expect(customers.get_by_label("Name").first).to_be_hidden()
    rows.nth(0).locator("summary").click()
    expect(rows.nth(0).get_by_label("Name")).to_have_value("Harbour Spirits Co.")
    expect(page.get_by_role("heading", name="New contract customer")).to_be_hidden()
    customers.get_by_role("button", name="Add customer", exact=True).first.click()
    expect(page.get_by_role("heading", name="New contract customer")).to_be_visible()


def test_page_loads_again_after_leaving_and_returning(contracts_page):
    page = contracts_page
    _open(page)
    page.evaluate("window.__contractsSentinel = true")
    page.get_by_role("link", name="Customer raw materials").click()
    expect(page.get_by_role("heading", name="Customer materials", exact=True)).to_be_visible()
    page.go_back()
    expect(page.locator('[data-figure="overdue"]')).to_have_text("1")
    expect(page.locator(".contracts-table-open .contracts-due").first).to_have_text("3 days overdue")


# CONCEPT ONLY — delete with the preview switch and the two layouts not chosen.
@pytest.mark.parametrize("style", ["1", "2", "3"])
@pytest.mark.parametrize("width", [390, 1024, 1440, 1920])
def test_concepts_fit_every_width(contracts_page, style, width):
    page = contracts_page
    page.set_viewport_size({"width": width, "height": 900})
    _open(page, style)
    expect(page.locator("[data-contracts-root]")).to_have_attribute("data-contracts-style", style)
    expect(page.get_by_role("heading", name="Orders", exact=True)).to_be_visible()
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1")


# CONCEPT ONLY
def test_each_concept_arranges_orders_and_customers_its_own_way(contracts_page):
    page = contracts_page
    _open(page, "1")
    expect(page.get_by_role("region", name="At a glance", exact=True)).to_be_visible()
    expect(page.locator("[data-contracts-brief]")).to_be_hidden()
    page.get_by_role("button", name="2 · Tabs", exact=True).click()
    expect(page.locator("[data-contracts-brief]")).to_have_text("3 open orders: 1 overdue, 1 due this week.")
    expect(page.get_by_role("region", name="Contract customers", exact=True)).to_be_hidden()
    page.get_by_role("tab", name="Customers").click()
    expect(page.get_by_role("region", name="Contract customers", exact=True)).to_be_visible()
    expect(page.get_by_role("region", name="Orders", exact=True)).to_be_hidden()
    page.get_by_role("button", name="3 · By customer", exact=True).click()
    expect(page.get_by_role("region", name="Orders for Harbour Spirits Co.")).to_be_visible()
    expect(page.locator(".contracts-table-open")).to_be_hidden()
