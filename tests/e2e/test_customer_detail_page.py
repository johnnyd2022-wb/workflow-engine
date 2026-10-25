"""A customer's page in a browser: one load, the header and facts, actions from the header, the
tabbed sections, and the page at phone, laptop and wall widths.

Requests are routed into the Flask test client (see test_crm_contact_sync_ui), and Xero is faked.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from playwright.sync_api import expect

from app.features.crm.models.xero_contact import XeroContact
from tests.e2e.test_crm_contact_sync_ui import client, sales_page, xero  # noqa: F401 -- fixture re-export
from tests.test_crm import db, org, user  # noqa: F401 -- fixture re-export

pytestmark = pytest.mark.e2e

READY = ".customer-page[aria-busy='false']"


@pytest.fixture()
def customer(db, org):  # noqa: F811
    contact = XeroContact(
        org_id=org.id,
        name="Kererū Botanicals",
        source="bize",
        first_name="Aroha",
        last_name="Wilson",
        email_address="aroha@kereru.example",
        phone_number="021 555 0199",
        contact_status="ACTIVE",
    )
    db.add(contact)
    db.commit()
    return contact


def _open(page, contact, width=1440):
    page.set_viewport_size({"width": width, "height": 900})
    page.goto(f"https://crm.test/crm/customers/{contact.id}")
    page.locator(READY).wait_for()


def _task(client, contact, title, days):  # noqa: F811
    due = (date.today() + timedelta(days=days)).isoformat()
    response = client.post("/api/crm/tasks", json={"title": title, "contact_id": str(contact.id), "due_date": due})
    assert response.status_code == 201, response.data


def test_the_customer_loads_once(xero, sales_page, customer):  # noqa: F811
    # x-init="init()" on top of Alpine's own init() call fetched the customer twice.
    calls = []
    sales_page.on("request", lambda r: calls.append(r.url) if f"/api/crm/customers/{customer.id}" in r.url else None)
    _open(sales_page, customer)
    sales_page.wait_for_load_state("networkidle")
    assert sum(url.endswith(f"/api/crm/customers/{customer.id}") for url in calls) == 1, calls


def test_the_header_says_who_and_what_is_next(xero, sales_page, client, customer):  # noqa: F811
    _task(client, customer, "Send the summer price list", 1)
    _open(sales_page, customer)
    expect(sales_page.get_by_role("heading", level=1)).to_have_text("Kererū Botanicals")
    expect(sales_page.locator(".crm-customer-meta")).to_contain_text("Aroha Wilson")
    expect(sales_page.locator(".crm-customer-meta")).to_contain_text("aroha@kereru.example")
    tasks = sales_page.locator(".cd-fact", has_text="Open tasks")
    expect(tasks.locator(".cd-fact__value")).to_have_text("1")
    expect(tasks.locator(".cd-fact__note")).to_have_text("Next: Send the summer price list · tomorrow")
    expect(sales_page.locator(".cd-fact", has_text="Last order").locator(".cd-fact__value")).to_have_text("None yet")


def test_new_task_opens_from_the_header_on_any_tab(xero, sales_page, customer):  # noqa: F811
    _open(sales_page, customer)
    sales_page.get_by_label("Customer sections").get_by_role("tab", name="Notes").click()
    sales_page.locator("[data-cd-new-task]").click()
    expect(sales_page.locator(".crm-task-sheet-overlay").filter(has_text="New Customer Task")).to_be_visible()


@pytest.mark.parametrize("width", [390, 1440, 1920], ids=["phone", "laptop", "wall"])
def test_the_page_fits_without_sideways_scroll(xero, sales_page, client, customer, width):  # noqa: F811
    _task(client, customer, "Send the summer price list", 1)
    _open(sales_page, customer, width=width)
    assert sales_page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    expect(sales_page.locator("[data-contact-details]")).to_be_visible()
    expect(sales_page.locator(".cd-tabs")).to_be_visible()
    expect(sales_page.locator(".cd-style-pick")).to_have_count(0)
