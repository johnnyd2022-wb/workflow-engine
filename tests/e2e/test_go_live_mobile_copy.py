"""Go-live instructions stay concise on phones without hiding stock-count rules."""

import os
from pathlib import Path

import pytest
from playwright.sync_api import expect

from tests.e2e.test_crm_contact_sync_ui import client, sales_page  # noqa: F401 -- fixture re-export
from tests.test_crm import db, org, user  # noqa: F401 -- fixture re-export

pytestmark = pytest.mark.e2e


def test_go_live_phone_copy_and_disclosures(sales_page):  # noqa: F811
    sales_page.set_viewport_size({"width": 390, "height": 844})
    sales_page.goto("https://crm.test/core/go-live")
    expect(sales_page.get_by_role("heading", name="Go live")).to_be_visible()
    count = sales_page.locator('[data-gl-step="count"]')
    expect(count.locator(".gl-hint.gl-mobile").first).to_contain_text("Count whole bottles")
    expect(count.locator(".gl-hint.gl-mobile").first).to_contain_text("Dates can stay blank")
    for step, summary, full in (
        ("date", "What about earlier sales?", "opening stock count already reflects them"),
        ("sales", "How are sales matched?", "oldest batch first"),
    ):
        section = sales_page.locator(f'[data-gl-step="{step}"]')
        expect(section.locator(".gl-desktop")).to_be_hidden()
        details = section.locator("details")
        expect(details.locator("p")).to_be_hidden()
        details.get_by_text(summary).click()
        expect(details.locator("p")).to_contain_text(full)
        details.get_by_text(summary).click()
    assert sales_page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    if folder := os.environ.get("MOBILE_COPY_SHOTS_DIR"):
        Path(folder).mkdir(parents=True, exist_ok=True)
        sales_page.screenshot(path=str(Path(folder) / "go-live-phone.png"), full_page=True)
        sales_page.evaluate("document.documentElement.setAttribute('data-spa-theme', 'dark')")
        sales_page.screenshot(path=str(Path(folder) / "go-live-phone-dark.png"), full_page=True)
        sales_page.evaluate("document.documentElement.setAttribute('data-spa-theme', 'light')")
    sales_page.set_viewport_size({"width": 1440, "height": 900})
    expect(sales_page.locator('[data-gl-step="count"] .gl-hint.gl-desktop').first).to_be_visible()
    expect(sales_page.locator('[data-gl-step="sales"] .gl-mobile')).to_be_hidden()
    if folder := os.environ.get("MOBILE_COPY_SHOTS_DIR"):
        sales_page.screenshot(path=str(Path(folder) / "go-live-desktop.png"), full_page=True)
