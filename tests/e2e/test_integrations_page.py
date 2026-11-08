"""Integrations in a browser: one status load, a failed Xero connection explained, disconnect asked
in the page, and the page's fit.

Requests are routed into the Flask test client, and Xero is faked (see test_crm_contact_sync_ui).
"""

from __future__ import annotations

import pytest
from playwright.sync_api import expect

from tests.e2e.test_crm_contact_sync_ui import client, sales_page, xero  # noqa: F401 -- fixture re-export
from tests.test_crm import db, org, user  # noqa: F401 -- fixture re-export
from tests.test_crm_contact_sync import _connect

pytestmark = pytest.mark.e2e

PAGE = "https://crm.test/core/integrations"
READY = ".ig-page[aria-busy='false']"


def _open(page, width=1440, query=""):
    page.set_viewport_size({"width": width, "height": 900})
    page.goto(PAGE + ("?" + query.lstrip("?&") if query else ""))
    page.locator(READY).wait_for()


def test_the_xero_status_loads_once(xero, sales_page):  # noqa: F811
    # x-init="init()" on top of Alpine's own init() call asked for the status twice.
    calls = []
    sales_page.on("request", lambda r: calls.append(r.url) if r.url.endswith("/api/crm/xero/status") else None)
    _open(sales_page)
    sales_page.wait_for_load_state("networkidle")
    assert len(calls) == 1, calls


def test_a_failed_connection_says_why(xero, sales_page, client):  # noqa: F811
    # The OAuth routes sent errors to Sales settings, which never read ?error=.
    response = client.get("/crm/xero/select-tenant")
    assert response.status_code == 302 and response.headers["Location"].endswith("/core/integrations")
    _open(sales_page, query="&error=xero_access_denied")
    expect(sales_page.get_by_role("alert")).to_contain_text(
        "Xero wasn't given access. Try again and choose Allow access in Xero."
    )


def test_disconnect_is_asked_in_the_page(xero, sales_page, db, org):  # noqa: F811
    _connect(db, org.id)
    _open(sales_page)
    expect(sales_page.locator("[data-integration='xero'] .ig-state")).to_have_text("Connected")
    sales_page.get_by_role("button", name="Disconnect").click()
    dialog = sales_page.get_by_role("dialog", name="Disconnect Xero?")
    expect(dialog).to_be_visible()
    dialog.get_by_role("button", name="Cancel").click()
    expect(dialog).to_be_hidden()
    expect(sales_page.locator("[data-integration='xero'] .ig-state")).to_have_text("Connected")


@pytest.mark.parametrize("width", [390, 1440, 1920], ids=["phone", "laptop", "wall"])
def test_the_page_fits_without_sideways_scroll(xero, sales_page, width):  # noqa: F811
    _open(sales_page, width=width)
    assert sales_page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    expect(sales_page.locator("[data-integration='xero']")).to_be_visible()
    expect(sales_page.get_by_role("link", name="Connect Xero")).to_be_visible()
