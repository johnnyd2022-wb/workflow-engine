"""Task settings in a browser: one load, a Save per section, a failed load that hides the settings,
and the page's fit.

Requests are routed into the Flask test client (see test_crm_contact_sync_ui).
"""

from __future__ import annotations

import pytest
from playwright.sync_api import expect

from tests.e2e.test_crm_contact_sync_ui import client, sales_page  # noqa: F401 -- fixture re-export
from tests.test_crm import db, org, user  # noqa: F401 -- fixture re-export

pytestmark = pytest.mark.e2e

PAGE = "https://crm.test/core/tasks/configuration"
READY = ".task-settings[aria-busy='false']"


def _open(page, width=1440):
    page.set_viewport_size({"width": width, "height": 900})
    page.goto(f"{PAGE}")
    page.locator(READY).wait_for()


def test_the_settings_load_once(sales_page):  # noqa: F811
    # x-init="init()" on top of Alpine's own init() call loaded them twice.
    calls = []
    sales_page.on("request", lambda r: calls.append(r.url) if r.url.endswith("/api/core/tasks/configuration") else None)
    _open(sales_page)
    sales_page.wait_for_load_state("networkidle")
    assert len(calls) == 1, calls


def test_a_section_saves_only_itself(sales_page, client):  # noqa: F811
    _open(sales_page)
    sales_page.locator("#ts-due-value").fill("3")
    sales_page.locator("#ts-archive-value").fill("2")
    sales_page.locator("#archive").get_by_role("button", name="Save").click()
    expect(sales_page.locator("#archive .ts-saved")).to_have_text("Saved.")
    saved = client.get("/api/core/tasks/configuration").get_json()
    assert (saved["done_archive_value"], saved["notification_lead_value"]) == (2, 7)
    expect(sales_page.locator("#ts-due-value")).to_have_value("3")


def test_settings_that_did_not_load_cannot_be_saved_over(sales_page):  # noqa: F811
    # The form kept its defaults after a failed load, and saving them overwrote the real settings.
    sales_page.route(
        "**/api/core/tasks/configuration",
        lambda route: route.fulfill(status=503, json={"error": "Task settings could not load."}),
    )
    _open(sales_page)
    expect(sales_page.get_by_role("alert")).to_contain_text("Task settings could not load.")
    expect(sales_page.locator("#due")).to_be_hidden()
    sales_page.unroute("**/api/core/tasks/configuration")
    sales_page.get_by_role("button", name="Try again").click()
    expect(sales_page.locator("#due")).to_be_visible()


@pytest.mark.parametrize("width", [390, 1440, 1920], ids=["phone", "laptop", "wall"])
def test_the_page_fits_without_sideways_scroll(sales_page, width):  # noqa: F811
    _open(sales_page, width=width)
    assert sales_page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    expect(sales_page.locator("#due")).to_be_visible()
    expect(sales_page.locator("#archive")).to_be_visible()
