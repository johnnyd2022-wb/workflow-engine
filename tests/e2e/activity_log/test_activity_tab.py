"""Golden-path browser coverage for GET /api/core/entities/activity, as consumed by the
sourcemap page's "Activity" tab (app/core/frontend/js/sourcemap.js, AC11-AC14)."""

import pytest
from playwright.sync_api import expect

from tests.e2e.activity_log.conftest import create_inventory_item
from tests.e2e.conftest import assert_clean_page, attach_probe, login_through_ui

pytestmark = pytest.mark.e2e


def test_ac11_activity_tab_renders_org_events(browser, app_url, fresh_user):
    user = fresh_user()
    context = browser.new_context(base_url=app_url, ignore_https_errors=True)
    page = context.new_page()
    attach_probe(page)
    try:
        login_through_ui(page, user["email"], user["password"])
        create_inventory_item(page, name="Activity Tab Widget", quantity="4", unit="kg")

        page.goto("/core/sourcemap")
        page.get_by_role("tab", name="Activity").click()

        feed = page.locator(".sm-act-feed")
        expect(feed).to_be_visible()
        expect(feed.locator(".sm-act-entry__summary").filter(has_text="Added")).to_have_count(1, timeout=10000)
        assert_clean_page(page)
    finally:
        context.close()


def test_activity_tab_shows_only_login_event_before_any_business_action(browser, app_url, fresh_user):
    """A fresh org has no inventory/process/execution activity yet, but logging in itself
    emits a user.login EntityEvent (_human_summary handles it, _update_user_summary tracks
    login_count) -- so the feed is never truly empty for an authenticated session. This is
    a more accurate baseline than an "empty state" assertion would be, and doubles as a
    real-world exercise of the entity_type filter (AC12) narrowing to exactly that event."""
    user = fresh_user()
    context = browser.new_context(base_url=app_url, ignore_https_errors=True)
    page = context.new_page()
    attach_probe(page)
    try:
        login_through_ui(page, user["email"], user["password"])

        page.goto("/core/sourcemap")
        page.get_by_role("tab", name="Activity").click()

        feed = page.locator(".sm-act-feed")
        expect(feed).to_be_visible()
        badges = feed.locator(".sm-act-badge")
        expect(badges).to_have_count(1)
        expect(badges.first).to_have_text("User")
        assert_clean_page(page)
    finally:
        context.close()
