"""Raising an invoice from a customer's page: the New Invoice form, in a browser.

Closes the "Customer / invoice CRUD (e2e)" deferral in .agents/reports/e2e/coverage-index.md.
Customers made in Biz-E are covered by test_crm_contact_sync_ui.py; this covers the other
write path, the form that sends an invoice to Xero. tests/test_crm.py::TestCRMInvoiceCreation
covers the service. What only a browser shows is the form itself: that what a person types
is what reaches Xero, that choosing Authorised really sends AUTHORISED, and that a refusal
is read out rather than swallowed.

Same harness as test_crm_contact_sync_ui.py: Playwright routes every request into the Flask
test client, and Xero is faked at the XeroAPIClient boundary. Opening the form also asks Xero
for the customer's payment terms, so that is faked too, and the fixture fails any test in
which the app builds a Xero API client the fake did not answer: nothing here may reach
api.xero.com, even with a placeholder token.
"""

from __future__ import annotations

import re
from types import SimpleNamespace
from uuid import uuid4

import pytest
from playwright.sync_api import expect

from app.features.crm.services import xero_api_client as xero_api_client_module
from tests import test_crm as crm_fixtures
from tests.e2e import test_crm_contact_sync_ui as contact_sync_ui
from tests.test_crm import _xero_bad_request
from tests.test_crm_contact_sync import _connect, _xero_contact
from tests.test_xero_sync_service import _xero_invoice

pytestmark = pytest.mark.e2e

db = crm_fixtures.db
org = crm_fixtures.org
user = crm_fixtures.user
client = contact_sync_ui.client
sales_page = contact_sync_ui.sales_page


class FakeXeroInvoices:
    """Stands in for Xero's invoices API.

    Xero answers a create with the invoice it made, and the app pulls it back on the sync it
    runs straight afterwards, so the invoice a test sees listed is built from what the form
    sent, not from anything the test hard-codes.
    """

    def __init__(self):
        self.created: list[dict] = []
        self.fail_with: Exception | None = None
        self.unfaked: list[str] = []
        self._xero_invoices: list[SimpleNamespace] = []

    def install(self, monkeypatch):
        fake = self

        def create_invoice(_client, **sent):
            if fake.fail_with:
                raise fake.fail_with
            fake.created.append(sent)
            invoice = _xero_invoice(f"xero-inv-{uuid4()}", f"INV-{len(fake.created):04d}")
            total = sum(line["quantity"] * line["unit_amount"] for line in sent["line_items"])
            invoice.contact = SimpleNamespace(contact_id=sent["contact_xero_id"])
            invoice.status = sent["status"]
            invoice.date, invoice.due_date = sent["invoice_date"], sent["due_date"]
            invoice.sub_total = invoice.total = invoice.amount_due = total
            invoice.total_tax = 0
            invoice.line_items = [
                SimpleNamespace(
                    line_item_id=f"{invoice.invoice_id}-{n}",
                    description=line["description"],
                    item_code=line["item_code"],
                    quantity=line["quantity"],
                    unit_amount=line["unit_amount"],
                    line_amount=line["quantity"] * line["unit_amount"],
                    account_code="200",
                    tax_type="OUTPUT2",
                    tax_amount=0,
                    discount_rate=None,
                    tracking=None,
                )
                for n, line in enumerate(sent["line_items"])
            ]
            fake._xero_invoices.append(invoice)
            return invoice

        def unfaked(_client):
            # The app swallows a failed Xero call, so raising here would pass unseen.
            # Recording it is what lets the fixture fail the test afterwards.
            fake.unfaked.append("a Xero API client was built for a call the fake does not answer")
            raise AssertionError(fake.unfaked[-1])

        xero_client = xero_api_client_module.XeroAPIClient
        monkeypatch.setattr(xero_client, "create_invoice", create_invoice)
        monkeypatch.setattr(xero_client, "get_all_contacts", lambda self, **kw: [])
        monkeypatch.setattr(xero_client, "get_all_invoices", lambda self, **kw: list(fake._xero_invoices))
        monkeypatch.setattr(xero_client, "get_contact_payment_terms", lambda self, contact_xero_id: None)
        monkeypatch.setattr(xero_client, "_get_api_client", unfaked)
        return self


@pytest.fixture()
def xero_invoices(monkeypatch):
    fake = FakeXeroInvoices().install(monkeypatch)
    yield fake
    assert fake.unfaked == [], "the app reached for Xero somewhere this test did not fake"


def _open_the_invoice_form(page, contact):
    page.goto(f"https://crm.test/crm/customers/{contact.id}")
    page.get_by_role("tab", name=re.compile(r"^Invoices")).click()
    page.get_by_role("button", name="New Invoice").click()
    form = page.locator(".crm-task-sheet-overlay").filter(has_text="New Invoice")
    expect(form).to_be_visible()
    return form


def _fill_the_line(form, description, quantity, unit_price):
    # Labels here are not tied to their inputs, so the fields are found by what they are.
    form.get_by_placeholder("Type or choose product").fill(description)
    form.locator("input[type=number]").nth(0).fill(quantity)
    form.locator("input[type=number]").nth(1).fill(unit_price)


def _click_and_read_the_alert(page, button):
    """Click, read what the page said, and let the page finish with it.

    The alert is raised after the request fails, so the click returns before it does; waiting
    for the dialog itself is what orders the assertions after the failure. The page is not done
    when the alert is dismissed, though: the code after it (closing the form, resetting the
    button) and the framework's re-render still have to run, and an assertion made in that gap
    sees a half-updated page. Two animation frames run after both.
    """
    # A waiter alone leaves the dialog open, and an alert raised inside the click handler then
    # blocks the click for good; the listener is what dismisses it.
    page.once("dialog", lambda dialog: dialog.accept())
    with page.expect_event("dialog") as raised:
        button.click()
    page.evaluate("() => new Promise((done) => requestAnimationFrame(() => requestAnimationFrame(done)))")
    return raised.value.message


def test_a_draft_invoice_reaches_xero_as_typed_and_is_listed(sales_page, db, org, xero_invoices):
    page = sales_page
    _connect(db, org.id)
    contact = _xero_contact(db, org.id, name="Harbour Spirits Co.")

    form = _open_the_invoice_form(page, contact)
    expect(form.get_by_role("button", name="Create Draft")).to_be_visible()
    _fill_the_line(form, "Botanical gin, 700ml case", "2", "75")
    form.get_by_role("button", name="Create Draft").click()

    expect(form).to_be_hidden()
    row = page.locator(".crm-invoice-row").filter(has_text="INV-0001")
    expect(row).to_have_count(1)
    expect(row.locator(".crm-badge")).to_have_text("DRAFT")

    (sent,) = xero_invoices.created
    assert sent["status"] == "DRAFT"
    assert sent["contact_xero_id"] == contact.xero_contact_id
    assert [(line["description"], line["quantity"], line["unit_amount"]) for line in sent["line_items"]] == [
        ("Botanical gin, 700ml case", 2.0, 75.0)
    ]


def test_choosing_authorised_sends_it_authorised(sales_page, db, org, xero_invoices):
    page = sales_page
    _connect(db, org.id)
    contact = _xero_contact(db, org.id, name="Harbour Spirits Co.")

    form = _open_the_invoice_form(page, contact)
    _fill_the_line(form, "Botanical gin, 700ml case", "1", "75")
    form.locator("select.crm-form-select").first.select_option("AUTHORISED")
    # The button says what will happen before it happens.
    expect(form.get_by_role("button", name="Create Draft")).to_have_count(0)
    form.get_by_role("button", name="Create & Authorise").click()

    expect(form).to_be_hidden()
    expect(page.locator(".crm-invoice-row").filter(has_text="INV-0001").locator(".crm-badge")).to_have_text(
        "AUTHORISED"
    )
    assert [sent["status"] for sent in xero_invoices.created] == ["AUTHORISED"]


def test_a_form_with_no_line_is_stopped_before_it_reaches_xero(sales_page, db, org, xero_invoices):
    """[CONTROL] the form's own check: nothing is sent, and the person is told why."""
    page = sales_page
    _connect(db, org.id)
    contact = _xero_contact(db, org.id, name="Harbour Spirits Co.")
    posted = []
    page.on("request", lambda r: posted.append(r.url) if r.method == "POST" and r.url.endswith("/invoices") else None)

    form = _open_the_invoice_form(page, contact)
    told = _click_and_read_the_alert(page, form.get_by_role("button", name="Create Draft"))

    assert told == "At least one line item is required."
    expect(form).to_be_visible()
    # The server also refuses an empty invoice, with almost the same words, so what is
    # asserted is that the form never asked it.
    assert posted == []
    assert xero_invoices.created == []


def test_a_xero_failure_is_read_out_and_keeps_what_was_typed(sales_page, db, org, xero_invoices):
    page = sales_page
    _connect(db, org.id)
    contact = _xero_contact(db, org.id, name="Harbour Spirits Co.")
    xero_invoices.fail_with = RuntimeError("no usable reply")

    form = _open_the_invoice_form(page, contact)
    _fill_the_line(form, "Botanical gin, 700ml case", "2", "75")
    told = _click_and_read_the_alert(page, form.get_by_role("button", name="Create Draft"))

    assert told == "Xero could not be reached. Try again in a moment."
    # The form is still open with the line in it and the button is ready again, so a retry is
    # one click, not a retype. (While sending the button reads "Creating…" and is disabled.)
    expect(form).to_be_visible()
    expect(form.get_by_role("button", name="Create Draft")).to_be_enabled()
    expect(form.get_by_placeholder("Type or choose product")).to_have_value("Botanical gin, 700ml case")
    assert xero_invoices.created == []
    expect(page.locator(".crm-invoice-row")).to_have_count(0)


def test_a_xero_refusal_is_read_out_in_xeros_words(sales_page, db, org, xero_invoices):
    """Xero turning the invoice down (not unreachable) says why, and the form stays open."""
    page = sales_page
    _connect(db, org.id)
    contact = _xero_contact(db, org.id, name="Harbour Spirits Co.")
    xero_invoices.fail_with = _xero_bad_request("Account code '999' is not a valid code")

    form = _open_the_invoice_form(page, contact)
    _fill_the_line(form, "Botanical gin, 700ml case", "2", "75")
    told = _click_and_read_the_alert(page, form.get_by_role("button", name="Create Draft"))

    assert told == "Xero refused this: Account code '999' is not a valid code"
    expect(form).to_be_visible()
    assert xero_invoices.created == []
