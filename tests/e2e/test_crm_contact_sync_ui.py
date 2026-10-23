"""Adding a customer in Biz-E, editing one with the Xero warning, and the Sales-wide default.

The browser talks to an in-process app (Playwright routes every request into the Flask test
client) so Xero can be faked at the XeroAPIClient boundary, the same FakeXero the unit tests
use. No request ever leaves for a real Xero tenant.
"""

from __future__ import annotations

import os
from urllib.parse import urlsplit

import pytest
from playwright.sync_api import expect

from app.features.crm.models.xero_contact import XeroContact
from tests import test_crm as crm_fixtures
from tests.test_crm_contact_sync import FakeXero, _connect, _xero_contact

pytestmark = pytest.mark.e2e

db = crm_fixtures.db
org = crm_fixtures.org
user = crm_fixtures.user
SHOTS = os.environ.get("CRM_SHOTS_DIR")


@pytest.fixture()
def xero(monkeypatch):
    fake = FakeXero().install(monkeypatch)
    yield fake
    assert fake.unfaked == [], "the app reached for Xero somewhere this test did not fake"


@pytest.fixture()
def client(user):
    """A signed-in test client. Unlike tests/test_crm.py's app_client it holds no app context
    open: Playwright calls the proxy from its own greenlet, and each request pushes its own."""
    from app.api.app_factory import create_app

    flask_app = create_app()
    flask_app.config.update(TESTING=True, WTF_CSRF_ENABLED=False)
    test_client = flask_app.test_client()
    test_client.environ_base["wsgi.url_scheme"] = "https"
    test_client.environ_base["HTTP_X_FORWARDED_PROTO"] = "https"
    response = test_client.post("/auth/login", json={"email": user.email, "password": "TestPass123!"})
    assert response.status_code in (200, 201), response.data
    return test_client


@pytest.fixture()
def sales_page(client, browser):
    page = browser.new_page(viewport={"width": 1440, "height": 900})
    jar = {}

    def proxy(route):
        request = route.request
        parsed = urlsplit(request.url)
        if parsed.netloc != "crm.test":
            route.abort()
            return
        headers = {"Content-Type": request.headers.get("content-type", "application/json")}
        for name in ("x-csrftoken", "hx-request", "hx-boosted", "hx-current-url"):
            if request.headers.get(name):
                headers[name] = request.headers[name]
        response = client.open(
            parsed.path + ("?" + parsed.query if parsed.query else ""),
            method=request.method,
            data=request.post_data,
            headers=headers,
        )
        jar["last"] = response.status_code
        route.fulfill(
            status=response.status_code,
            body=response.data,
            headers={
                k: v for k, v in response.headers.items() if k.lower() in ("content-type", "location", "hx-redirect")
            },
        )

    page.route("**/*", proxy)
    yield page
    page.close()


def _shot(page, name):
    if SHOTS:
        page.screenshot(path=os.path.join(SHOTS, name + ".png"), full_page=True)


def test_add_a_customer_that_stays_in_bize(xero, sales_page, db, org):
    page = sales_page
    _connect(db, org.id)
    page.goto("https://crm.test/crm/customers")
    page.get_by_role("button", name="New customer").click()
    dialog = page.get_by_role("dialog", name="New customer")
    expect(dialog).to_be_visible()
    # The Sales default is off, so the box starts unticked and the button says what happens.
    expect(dialog.get_by_role("checkbox")).not_to_be_checked()
    dialog.get_by_label("Customer or business name").fill("Kererū Botanicals")
    dialog.get_by_label("Phone").fill("021 555 0199")
    _shot(page, "new-customer")
    dialog.get_by_role("button", name="Save customer").click()

    page.locator("[data-xero-sync]").wait_for()
    expect(page.locator("[data-xero-state]")).to_have_text("Only in Biz-E")
    expect(page.locator("[data-xero-sync-choice]")).to_have_value("default")
    assert xero.created == []
    _shot(page, "bize-only-customer")

    # Edits to a customer that stays in Biz-E save without a Xero warning.
    page.get_by_role("button", name="Edit details").click()
    page.get_by_label("Email").fill("hello@kereru.example")
    page.locator("[data-edit-form]").get_by_role("button", name="Save").click()
    expect(page.locator("[data-xero-warning]")).to_be_hidden()
    expect(page.locator(".crm-customer-meta")).to_contain_text("hello@kereru.example")
    assert xero.updated == [] and xero.created == []

    # Turning sync on for this customer sends it.
    page.locator("[data-xero-sync-choice]").select_option("on")
    expect(page.locator("[data-xero-state]")).to_contain_text("In Xero")
    assert [fields["name"] for fields, _ in xero.created] == ["Kererū Botanicals"]


def test_editing_a_xero_customer_warns_with_the_changes_before_sending(xero, sales_page, db, org):
    page = sales_page
    _connect(db, org.id)
    contact = _xero_contact(db, org.id)
    page.goto(f"https://crm.test/crm/customers/{contact.id}")
    page.get_by_role("button", name="Edit details").click()
    page.get_by_label("Phone").fill("04 555 0222")
    page.locator("[data-edit-form]").get_by_role("button", name="Save").click()

    warning = page.locator("[data-xero-warning]")
    expect(warning).to_be_visible()
    expect(warning).to_contain_text("This also updates Harbour Spirits Co. in Fake Tenant")
    expect(warning.get_by_role("listitem")).to_have_text(["Phone: 04 555 0100 → 04 555 0222"])
    assert xero.updated == []  # nothing leaves until the warning is accepted
    _shot(page, "xero-warning")

    warning.get_by_role("button", name="Back to editing").click()
    expect(page.get_by_label("Phone")).to_have_value("04 555 0222")
    page.locator("[data-edit-form]").get_by_role("button", name="Save").click()
    page.get_by_role("button", name="Save and update Xero").click()
    expect(page.locator("[role=status]").filter(has_text="Saved and sent to Xero.")).to_be_visible()
    assert xero.updated == [(contact.xero_contact_id, {"phone_number": "04 555 0222", "name": "Harbour Spirits Co."})]
    db.refresh(contact)
    assert contact.phone_number == "04 555 0222"


def test_a_failed_send_shows_why_and_try_again_sends_it(xero, sales_page, db, org):
    page = sales_page
    _connect(db, org.id)
    contact = _xero_contact(db, org.id)
    xero.fail_with = RuntimeError("connection reset")
    page.goto(f"https://crm.test/crm/customers/{contact.id}")
    page.get_by_role("button", name="Edit details").click()
    page.get_by_label("Phone").fill("04 555 0333")
    page.locator("[data-edit-form]").get_by_role("button", name="Save").click()
    page.get_by_role("button", name="Save and update Xero").click()
    expect(page.locator("[data-xero-state]")).to_contain_text("Not sent to Xero")
    _shot(page, "send-failed")

    xero.fail_with = None
    page.locator("[data-retry-xero]").click()
    expect(page.locator("[data-xero-state]")).to_contain_text("In Xero")
    assert xero.updated[-1][1]["phone_number"] == "04 555 0333"

    page.goto("https://crm.test/crm/customers")
    row = page.locator("tbody tr").filter(has_text="Harbour Spirits Co.")
    expect(row.get_by_text("Not sent to Xero")).to_be_hidden()


def test_the_sales_default_sends_waiting_customers(xero, sales_page, db, org):
    page = sales_page
    _connect(db, org.id)
    db.add(XeroContact(org_id=org.id, source="bize", name="Waiting Ltd", is_customer=True, is_supplier=False))
    db.commit()
    page.goto("https://crm.test/crm/customers")
    expect(page.locator("tbody tr").filter(has_text="Waiting Ltd").get_by_text("Biz-E only")).to_be_visible()
    _shot(page, "customers-list")

    page.goto("https://crm.test/crm/configuration")
    toggle = page.locator("[data-sync-default]")
    toggle.check()
    expect(page.locator("[data-sync-default-result]")).to_have_text("On. 1 waiting customer sent to Xero.")
    _shot(page, "settings")
    assert [fields["name"] for fields, _ in xero.created] == ["Waiting Ltd"]

    page.goto("https://crm.test/crm/customers")
    page.get_by_role("button", name="New customer").click()
    expect(page.get_by_role("dialog", name="New customer").get_by_role("checkbox")).to_be_checked()


def test_editing_an_address_shows_it_in_the_warning_and_sends_both(xero, sales_page, db, org):
    from tests.test_crm_contact_sync import XERO_ADDRESSES

    page = sales_page
    _connect(db, org.id)
    contact = _xero_contact(db, org.id, addresses=XERO_ADDRESSES)
    page.goto(f"https://crm.test/crm/customers/{contact.id}")
    expect(page.locator('[data-address="POBOX"]')).to_have_text("PO Box 12, Wellington, 6140, New Zealand")
    page.get_by_role("button", name="Edit details").click()
    page.locator("#edit-POBOX-line1").fill("PO Box 99")
    page.locator("[data-edit-form]").get_by_role("button", name="Save").click()
    warning = page.locator("[data-xero-warning]")
    expect(warning.get_by_role("listitem")).to_have_text(
        ["Postal address: PO Box 12, Wellington, 6140, New Zealand → PO Box 99, Wellington, 6140, New Zealand"]
    )
    _shot(page, "address-warning")
    page.get_by_role("button", name="Save and update Xero").click()
    expect(page.locator('[data-address="POBOX"]')).to_have_text("PO Box 99, Wellington, 6140, New Zealand")
    postal, street = xero.updated[-1][1]["addresses"]
    assert postal["line1"] == "PO Box 99" and postal["line3"] == "Level 2"
    assert street["line1"] == "1 Wharf St"

    # "Same as postal" copies the postal address into the street fields.
    page.get_by_role("button", name="Edit details").click()
    page.get_by_role("button", name="Street address is the same as postal").click()
    expect(page.locator("#edit-STREET-line1")).to_have_value("PO Box 99")
    _shot(page, "address-edit")
