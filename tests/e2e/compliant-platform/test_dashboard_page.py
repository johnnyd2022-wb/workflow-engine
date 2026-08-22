"""AC: `GET /compliant` -- requires auth, renders compliant/dashboard.html
(.agents/specs/compliant-platform.md, "Dashboard page")."""

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
    """Logged-in GET /compliant renders the real template: hero copy, the one-minute
    setup form, and the record form are all present, and the page is not silently broken
    (no console errors, no failed requests, no 5xx)."""
    page = admin_page
    response = page.goto("/compliant")
    assert response is not None and response.status == 200

    expect(page.locator("[data-compliant-root]")).to_be_visible()
    expect(page.get_by_role("heading", name="Run your business. Know what needs proving.")).to_be_visible()
    expect(page.locator("[data-profile-form]")).to_be_visible()
    expect(page.locator("[data-record-form]")).to_be_visible()
    expect(page.locator("[data-product-form]")).to_be_visible()

    assert_clean_page(page)
