"""Compliance -> Wine in a real browser (docs/wine-compliance-plan.md, W1b).

Switching wine on puts a Wine tab in the food-safety slot, the page renders without script or
Alpine errors, and the plan dialog saves the small-winemaker exemption and shows its meter.
"""

from __future__ import annotations

import pytest
from playwright.sync_api import Page, expect

from tests.e2e.conftest import csrf_headers

pytestmark = pytest.mark.e2e


def _switch_on_wine(page: Page) -> None:
    page.goto("/compliant/nz-alcohol")
    response = page.request.put(
        "/api/compliant/profile",
        data={"enabled": True, "settings": {"alcohol_product_types": ["wine"]}},
        headers=csrf_headers(page),
    )
    assert response.ok, response.text()


def test_wine_tab_page_and_exemption_plan(admin_page: Page):
    page = admin_page
    errors: list[str] = []
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    _switch_on_wine(page)

    page.goto("/compliant/nz-alcohol/wine")
    tabs = page.get_by_role("tablist", name="Compliance pages")
    expect(tabs.get_by_role("tab", name="Wine")).to_have_attribute("aria-selected", "true")
    expect(page.locator("[data-wine-root]")).to_have_attribute("aria-busy", "false")
    expect(page.get_by_role("heading", name="Wine", exact=True)).to_be_visible()
    expect(page.locator("[data-plan-chip]")).to_have_text("Not set")
    expect(page.locator("[data-wine-empty]")).to_be_visible()  # no winemaking steps yet

    page.get_by_role("button", name="Add plan details").click()  # the empty plan card offers it
    dialog = page.get_by_role("dialog", name="Your wine plan")
    dialog.get_by_text("Small winemaker exemption").click()
    dialog.get_by_label("Exemption started").fill("2026-03-01")
    dialog.get_by_role("button", name="Save plan").click()
    expect(dialog).to_be_hidden()
    expect(page.locator("[data-plan-chip]")).to_have_text("Exempt")
    expect(page.get_by_role("meter", name="Wine made in the exemption period")).to_be_visible()
    expect(page.locator("[data-plan-body]")).to_contain_text("of 20,000 L made since 1 Mar 2026")
    assert not [e for e in errors if "Alpine Expression Error" in e or "Content Security Policy" in e], errors


def test_wine_page_says_so_when_wine_is_off(admin_page: Page):
    admin_page.goto("/compliant/nz-alcohol/wine")
    expect(admin_page.locator("[data-wine-error]")).to_contain_text("Wine isn’t one of your product types")
