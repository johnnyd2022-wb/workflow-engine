"""GL-U02a: a role="tab" row works from the keyboard, as the ARIA tabs pattern says.

One shared script (app/ui/shared/tabs-keyboard.js) handles every tab row: the customer page's
in-page tabs (buttons, which switch as focus moves) and the section tabs (links to other pages,
which only move focus until Enter). Requests are routed into the Flask test client.
"""

from __future__ import annotations

from playwright.sync_api import expect

from tests.e2e.test_crm_contact_sync_ui import client, sales_page, xero  # noqa: F401 -- fixture re-export
from tests.e2e.test_customer_detail_page import _open, customer  # noqa: F401 -- fixture re-export
from tests.test_crm import db, org, user  # noqa: F401 -- fixture re-export

STOPS = "(sel) => [...document.querySelectorAll(sel + ' [role=tab]')].filter(t => t.tabIndex === 0).map(t => t.textContent.trim())"


def test_customer_tabs_move_with_the_arrow_keys_and_show_their_panel(xero, sales_page, customer):  # noqa: F811
    _open(sales_page, customer)
    tabs = sales_page.get_by_label("Customer sections")
    overview = tabs.get_by_role("tab", name="Overview")
    overview.focus()
    sales_page.keyboard.press("ArrowRight")
    invoices = tabs.get_by_role("tab", name="Invoices")
    expect(invoices).to_be_focused()
    expect(invoices).to_have_attribute("aria-selected", "true")
    expect(sales_page.get_by_role("tabpanel", name="Invoices")).to_be_visible()
    sales_page.keyboard.press("End")
    expect(tabs.get_by_role("tab", name="Tasks")).to_be_focused()
    sales_page.keyboard.press("ArrowRight")  # wraps round
    expect(overview).to_be_focused()
    expect(overview).to_have_attribute("aria-selected", "true")
    # The row is one Tab stop: the selected tab.
    assert sales_page.evaluate(STOPS, "[aria-label='Customer sections']") == ["Overview"]


def test_section_tabs_move_focus_without_leaving_the_page(xero, sales_page, customer):  # noqa: F811
    _open(sales_page, customer)
    row = sales_page.locator(".section-tabs [role=tablist]")
    current = row.get_by_role("tab", selected=True)
    url = sales_page.url
    current.focus()
    sales_page.keyboard.press("ArrowRight")
    focused = sales_page.evaluate("document.activeElement.textContent.trim()")
    assert focused != current.text_content().strip()
    assert sales_page.url == url, "an arrow key must not navigate"
    href = sales_page.evaluate("document.activeElement.getAttribute('href')")
    sales_page.keyboard.press("Enter")
    sales_page.wait_for_url("**" + href)
