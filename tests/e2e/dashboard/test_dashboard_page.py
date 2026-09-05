"""AC1/AC2: the `/core/dashboard` shell page.

The unauthenticated-redirect half of AC1 is already proven by
`tests/e2e/test_smoke.py::test_logged_out_user_cannot_reach_dashboard`, and the page
renders clean while logged in is already proven by
`tests/e2e/test_pages_render.py::test_core_page_renders_clean` (parametrised over
`/core/dashboard`). Neither of those asserts the `active_page="dashboard"` template arg
actually reaches the DOM, or that a failed summary fetch degrades to the documented
`data-dashboard-error` state rather than a blank page -- those are this file's gap-fill.
"""

import pytest
from playwright.sync_api import Page, expect

from tests.e2e.conftest import assert_clean_page

pytestmark = pytest.mark.e2e


def test_ac1_dashboard_page_highlights_active_nav(logged_in_page: Page):
    page = logged_in_page
    response = page.goto("/core/dashboard")
    assert response is not None and response.status == 200
    page.wait_for_load_state("networkidle")

    active_link = page.locator('a.nav-link.active[href="/core/dashboard"]')
    expect(active_link).to_be_visible()
    assert_clean_page(page)


def test_dashboard_landing_fires_one_summary_call_and_stays_clean(logged_in_page: Page):
    """dashboard.js inits from both DOMContentLoaded and htmx:afterSettle; the landing
    load must still make exactly one /api/core/dashboard/summary call and log no console
    errors (a boosted-nav race previously aborted the fetch -> `TypeError: Failed to
    fetch`). The control-tower cards must use that one response rather than adding a
    Compliant overview waterfall."""
    page = logged_in_page
    calls: list[str] = []
    compliant_calls: list[str] = []
    page.on(
        "request",
        lambda r: calls.append(r.url) if r.method == "GET" and "/api/core/dashboard/summary" in r.url else None,
    )
    page.on(
        "request",
        lambda r: compliant_calls.append(r.url) if r.method == "GET" and "/api/compliant/" in r.url else None,
    )

    page.goto("/core/dashboard")
    page.wait_for_load_state("networkidle")

    assert len(calls) == 1, f"expected exactly one dashboard/summary call, got {len(calls)}: {calls}"
    assert compliant_calls == [], f"dashboard must not add a Compliant overview request: {compliant_calls}"
    expect(page.locator("[data-dashboard-error]")).to_be_hidden()
    assert_clean_page(page)


def test_dashboard_distinguishes_the_control_tower_from_workspaces(logged_in_page: Page):
    """Dashboard starts with the cross-business queue, then routes work to its home."""
    page = logged_in_page
    page.goto("/core/dashboard")
    page.wait_for_load_state("networkidle")

    expect(page.locator("#dashboard-attention-title")).to_have_text("Needs attention")
    expect(page.locator("#dashboard-workspaces-title")).to_have_text("Choose a workspace")
    expect(page.locator('a.dash-workspace-card[href="/core"]')).to_be_visible()
    expect(page.locator('a.dash-workspace-card[href="/crm"]')).to_be_visible()
    expect(page.locator("[data-dashboard-core-summary]")).not_to_contain_text("Loading")
    expect(page.locator("[data-dashboard-crm-summary]")).not_to_contain_text("Loading")

    hierarchy = page.evaluate("""
        () => {
            const attention = document.querySelector('#dashboard-attention-title');
            const workspaces = document.querySelector('#dashboard-workspaces-title');
            return Boolean(attention && workspaces &&
                (attention.compareDocumentPosition(workspaces) & Node.DOCUMENT_POSITION_FOLLOWING));
        }
    """)
    assert hierarchy, "the action queue must appear before workspace and trend context"
    assert_clean_page(page)


def test_ac2_dashboard_shows_inline_error_when_summary_fetch_fails(logged_in_page: Page):
    """A failed client-side fetch of /api/core/dashboard/summary must surface
    `data-dashboard-error` rather than leave the page blank or throw uncaught."""
    page = logged_in_page
    page.route(
        "**/api/core/dashboard/summary*",
        lambda route: route.fulfill(status=500, content_type="application/json", body='{"error": "boom"}'),
    )

    page.goto("/core/dashboard")
    page.wait_for_load_state("networkidle")

    error_el = page.locator("[data-dashboard-error]")
    expect(error_el).to_be_visible()
    expect(error_el).to_contain_text("Could not load dashboard summary")

    # The loading indicator must not be left spinning forever once the error is shown.
    loading_el = page.locator("[data-dashboard-loading]")
    if loading_el.count() > 0:
        expect(loading_el).to_be_hidden()
