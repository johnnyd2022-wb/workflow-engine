"""Sales estimate explanations stay short on phone and complete on expansion."""

import os
from pathlib import Path

import pytest
from playwright.sync_api import expect

from tests.e2e.test_crm_contact_sync_ui import client, sales_page  # noqa: F401 -- fixture re-export
from tests.test_crm import db, org, user  # noqa: F401 -- fixture re-export

pytestmark = pytest.mark.e2e


def test_sales_estimate_copy_on_phone_and_desktop(monkeypatch, sales_page):  # noqa: F811
    monkeypatch.setattr("app.features.compliant.service.nz_alcohol_active", lambda *_: True)
    sales_page.route(
        "**/api/crm/excise/months",
        lambda route: route.fulfill(json={"months": [{"month": "2026-10", "complete": True, "lal": "1"}], "sources": ["Xero"], "rates_source": None}),
    )
    sales_page.route(
        "**/api/crm/excise?*",
        lambda route: route.fulfill(
            json={
                "report": {
                    "label": "October 2026",
                    "month": "2026-10",
                    "complete": True,
                    "totals": {"lal": "1", "litres": "5", "duty": "100", "levy": "5", "gst": "0.75", "customs": "105.75"},
                    "rows": [],
                    "problems": [],
                    "unmapped": {"count": 0},
                }
            }
        ),
    )
    sales_page.set_viewport_size({"width": 390, "height": 844})
    sales_page.goto("https://crm.test/crm/excise")
    expect(sales_page.locator(".ex-report")).to_be_visible()
    for area, summary, full_text in (
        (".ex-lede", "Why the figures can differ", "licensed area"),
        (".ex-foot", "See why they differ", "stock movement dates"),
    ):
        region = sales_page.locator(area)
        expect(region.locator(".ex-copy-desktop")).to_be_hidden()
        expect(region.locator(".ex-copy-mobile > p")).to_be_visible()
        detail = region.locator("details")
        expect(detail.locator("p")).to_be_hidden()
        detail.get_by_text(summary).click()
        expect(detail.locator("p")).to_contain_text(full_text)
        detail.get_by_text(summary).click()
    expect(sales_page.locator(".ex-lede .ex-copy-mobile a")).to_have_attribute("href", "/compliant/nz-alcohol/customs")
    if folder := os.environ.get("CRM_SHOTS_DIR"):
        Path(folder).mkdir(parents=True, exist_ok=True)
        sales_page.screenshot(path=str(Path(folder) / "sales-excise-phone.png"), full_page=True)
        sales_page.evaluate("document.documentElement.setAttribute('data-spa-theme', 'dark')")
        sales_page.screenshot(path=str(Path(folder) / "sales-excise-phone-dark.png"), full_page=True)
        sales_page.evaluate("document.documentElement.setAttribute('data-spa-theme', 'light')")
    sales_page.set_viewport_size({"width": 1440, "height": 900})
    expect(sales_page.locator(".ex-lede .ex-copy-desktop")).to_be_visible()
    expect(sales_page.locator(".ex-foot .ex-copy-desktop")).to_be_visible()
    expect(sales_page.locator(".ex-copy-mobile").first).to_be_hidden()
    if folder := os.environ.get("CRM_SHOTS_DIR"):
        sales_page.screenshot(path=str(Path(folder) / "sales-excise-desktop.png"), full_page=True)
