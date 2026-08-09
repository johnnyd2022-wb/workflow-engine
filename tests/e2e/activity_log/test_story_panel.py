"""Golden-path browser coverage for GET /api/core/entities/<type>/<id>/story, as consumed
by the inventory item's "Audit history" panel (app/core/frontend/inventory/view.html) --
the one real frontend caller of this route (AC1-AC6)."""

import re

import pytest
from playwright.sync_api import expect

from tests.e2e.activity_log.conftest import create_inventory_item
from tests.e2e.conftest import assert_clean_page, attach_probe, login_through_ui

pytestmark = pytest.mark.e2e


def test_ac5_audit_history_panel_renders_created_event(browser, app_url, fresh_user):
    user = fresh_user()
    context = browser.new_context(base_url=app_url, ignore_https_errors=True)
    page = context.new_page()
    attach_probe(page)
    try:
        login_through_ui(page, user["email"], user["password"])
        create_inventory_item(page, name="Story Panel Widget", quantity="6", unit="kg")

        page.goto("/core/inventory/view")
        row = page.get_by_role("row", name=re.compile("Story Panel Widget"))
        expect(row).to_be_visible()

        toggle = row.get_by_text("Audit history")
        toggle.click()

        timeline = row.locator(".inv-audit-timeline")
        expect(timeline).to_be_visible()
        expect(timeline).to_contain_text("Added")
        expect(timeline).to_contain_text("kg")
        assert_clean_page(page)
    finally:
        context.close()


def test_ac3_audit_history_panel_shows_exactly_the_creation_event_for_a_fresh_item(browser, app_url, fresh_user):
    """A brand-new item's story is never truly empty -- creation itself is the one event.
    The panel's "no history" empty state is for a different case entirely (zero events),
    which nothing in this suite reaches; this test instead locks in AC3's total/events
    shape for the single-event case, exercised from the UI."""
    user = fresh_user()
    context = browser.new_context(base_url=app_url, ignore_https_errors=True)
    page = context.new_page()
    attach_probe(page)
    try:
        login_through_ui(page, user["email"], user["password"])
        create_inventory_item(page, name="Freshly Created Widget", quantity="1", unit="kg")

        page.goto("/core/inventory/view")
        row = page.get_by_role("row", name=re.compile("Freshly Created Widget"))
        row.get_by_text("Audit history").click()

        timeline = row.locator(".inv-audit-timeline")
        expect(timeline).to_be_visible()
        expect(timeline.locator(".inv-audit-timeline__item")).to_have_count(1)
        assert_clean_page(page)
    finally:
        context.close()
