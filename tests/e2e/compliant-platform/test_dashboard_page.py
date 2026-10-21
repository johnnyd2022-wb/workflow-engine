"""Compliant index and the dedicated NZ Alcohol module page."""

from __future__ import annotations

import pytest
from playwright.sync_api import expect

from tests.e2e.conftest import assert_clean_page

pytestmark = pytest.mark.e2e


def test_dashboard_page_requires_auth(page, app_url):
    """An unauthenticated GET must not render the dashboard. The app's global 401 handler
    (app_factory.py:322-336) turns an unauthenticated page GET into a 302 to "/" rather
    than leaking the shell or returning the API's bare 401 JSON."""
    response = page.request.get("/compliant", max_redirects=0)
    assert response.status == 302, f"expected a 302 redirect, got {response.status}"
    location = response.headers.get("location", "")
    expected = f"{app_url.rstrip('/')}/"
    assert location in (expected, "/"), f"unexpected redirect target: {location!r}"


def test_dashboard_page_renders_for_logged_in_user(admin_page):
    """The index leads to a module-specific working surface without client errors."""
    page = admin_page
    response = page.goto("/compliant")
    assert response is not None and response.status == 200
    expect(page.get_by_role("heading", name="Compliance", exact=True)).to_be_visible()
    expect(page.get_by_role("link", name="Open overview")).to_be_visible()

    response = page.goto("/compliant/nz-alcohol")
    assert response is not None and response.status == 200
    expect(page.locator('link[href="/compliant/static/compliant.css"]')).to_have_count(1)
    # The overview's own script since the Compliance overview redesign (61928a7b).
    expect(page.locator('script[src="/compliant/static/compliance-overview.js"]')).to_have_count(1)
    expect(page.locator("[data-compliant-root]")).to_be_visible()
    expect(page.get_by_role("heading", name="Compliance", exact=True)).to_be_visible()
    expect(page.get_by_role("tab", name="Customs")).to_be_visible()

    response = page.goto("/compliant/nz-alcohol/customs")
    assert response is not None and response.status == 200
    # Records for Customs are folded at the bottom of the entry page, the form behind "Add a record".
    expect(page.locator("[data-record-form]")).to_be_hidden()
    page.locator("[data-customs-records] > summary").click()
    page.locator("[data-add-record] > summary").click()
    expect(page.locator("[data-record-form]")).to_be_visible()
    # Product classification moved to Customs -> Settings.
    page.locator('.customs-views a[href="/compliant/nz-alcohol/customs/settings"]').click()
    expect(page.get_by_role("heading", name="Products", exact=True)).to_be_visible()
    page.locator("[data-excise-rate-form]").locator("xpath=ancestor::details").locator("summary").click()
    expect(page.get_by_role("textbox", name="Tariff item", exact=True)).to_be_visible()

    assert_clean_page(page)
