"""Settings concepts keep every real control reachable and account load failures explicit."""

import re
from uuid import UUID

import pytest
from playwright.sync_api import expect

from tests.e2e.test_workspace_overviews import _page
from tests.e2e.test_workspace_overviews import workspace_user as _workspace_user
from tests.factories import grant_multi_site

pytestmark = pytest.mark.e2e

workspace_user = _workspace_user


def _expect_home(page):
    expect(page.locator("[data-dashboard-root] #dashboard-page-title")).to_have_text(
        re.compile(r"^E2E Fresh Org [0-9a-f]{8}$")
    )


def _category(page, name):
    page.locator(f'[data-settings-link="{name}"]').click()


@pytest.mark.parametrize("width", [390, 1024, 1440, 1920])
def test_every_setting_is_reachable_one_category_at_a_time(browser, app_url, workspace_user, width, db):
    grant_multi_site(db, UUID(workspace_user["org_id"]))
    context, page = _page(browser, app_url, workspace_user, width)
    try:
        page.goto("/core/settings")
        expect(page.get_by_role("heading", level=1)).to_have_text("Settings")
        expect(page.get_by_label("First name", exact=True)).to_be_enabled()
        for category, heading in [
            ("account", "Account information"),
            ("security", "Two-factor authentication"),
            ("preferences", "Appearance"),
        ]:
            _category(page, category)
            expect(page.get_by_role("heading", name=heading, exact=True)).to_be_visible()
            # Only the chosen category is on screen.
            expect(page.locator("[data-settings-group]:visible")).to_have_count(1)
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1")
        # Sites and people moved from an Organisation category to the Settings tab row (plan 2.5).
        tabs = page.get_by_role("tablist", name="Settings pages")
        expect(tabs.get_by_role("tab", name="Sites", exact=True)).to_have_attribute("href", "/core/sites")
        expect(tabs.get_by_role("tab", name="People", exact=True)).to_have_attribute("href", "/core/people")
    finally:
        context.close()


def test_sites_tab_is_hidden_without_subscription(browser, app_url, workspace_user):
    context, page = _page(browser, app_url, workspace_user, 1440)
    try:
        page.goto("/core/settings")
        tabs = page.get_by_role("tablist", name="Settings pages")
        expect(tabs.get_by_role("tab", name="Sites", exact=True)).to_have_count(0)
        expect(tabs.get_by_role("tab", name="People", exact=True)).to_be_visible()
    finally:
        context.close()


def test_settings_has_no_layout_preview_left(browser, app_url, workspace_user):
    """The chooser and the two layouts not picked are gone; an old remembered choice changes nothing."""
    context, page = _page(browser, app_url, workspace_user, 1440)
    try:
        page.goto("/core/settings")
        page.evaluate('sessionStorage.setItem("settings-design-style", "3")')
        page.goto("/core/settings?style=1")
        expect(page.get_by_role("group", name="Settings design concepts")).to_have_count(0)
        expect(page.locator("[data-style-pick]")).to_have_count(0)
        expect(page.locator(".settings-overview details")).to_have_count(0)
        expect(page.locator("[data-settings-group]:visible")).to_have_count(1)
        expect(page.get_by_role("heading", name="Account information", exact=True)).to_be_visible()
    finally:
        context.close()


def test_profile_load_failure_disables_editing_until_retry(browser, app_url, workspace_user):
    context, page = _page(browser, app_url, workspace_user, 1440)
    try:
        page.route("**/auth/settings", lambda route: route.fulfill(status=503, json={"error": "unavailable"}))
        page.goto("/core/settings")
        expect(page.get_by_role("status").filter(has_text="Your account could not load")).to_be_visible()
        for label in ["First name", "Last name", "Email", "Phone number"]:
            expect(page.get_by_label(label, exact=True)).to_be_disabled()
        expect(page.get_by_role("button", name="Save changes", exact=True)).to_be_disabled()
        page.unroute("**/auth/settings")
        page.get_by_role("button", name="Retry account load", exact=True).click()
        expect(page.get_by_label("Email", exact=True)).to_have_value(workspace_user["email"])
        expect(page.get_by_role("button", name="Save changes", exact=True)).to_be_enabled()
        expect(page.locator("#settings-load-status")).to_be_hidden()
    finally:
        context.close()


def test_switches_that_never_saved_anything_are_gone(browser, app_url, workspace_user):
    """The three notification switches had no save behaviour; a control that does nothing is not shown."""
    context, page = _page(browser, app_url, workspace_user, 1440)
    try:
        page.goto("/core/settings#settings-preferences")
        expect(page.get_by_role("heading", name="Appearance", exact=True)).to_be_visible()
        expect(page.get_by_role("checkbox", name="Dark mode", exact=True)).to_be_enabled()
        for name in ["Email Notifications", "Compliance Alerts", "Weekly Reports"]:
            expect(page.get_by_role("checkbox", name=name, exact=True)).to_have_count(0)
        expect(page.locator(".settings-overview input:disabled:visible")).to_have_count(0)
    finally:
        context.close()


def test_each_category_has_its_own_address_and_back_returns_to_it(browser, app_url, workspace_user):
    context, page = _page(browser, app_url, workspace_user, 1440)
    try:
        page.goto("/core/settings")
        page.locator('[data-settings-link="security"]').click()
        assert page.evaluate("location.hash") == "#settings-security"
        expect(page.get_by_role("heading", name="Two-factor authentication", exact=True)).to_be_visible()
        page.locator('[data-settings-link="preferences"]').click()
        expect(page.get_by_role("heading", name="Appearance", exact=True)).to_be_visible()
        page.go_back()
        expect(page.get_by_role("heading", name="Two-factor authentication", exact=True)).to_be_visible()
        expect(page.locator('[data-settings-link="security"]')).to_have_attribute("aria-current", "page")
        # A link straight to a category opens that category.
        page.goto("/core/settings#settings-preferences")
        expect(page.get_by_role("heading", name="Appearance", exact=True)).to_be_visible()
        expect(page.get_by_role("heading", name="Account information", exact=True)).to_be_hidden()
    finally:
        context.close()


def test_settings_desk_pairs_short_fields_and_keeps_one_filled_action_per_card(browser, app_url, workspace_user):
    context, page = _page(browser, app_url, workspace_user, 1440)
    try:
        page.goto("/core/settings")
        first = page.get_by_label("First name", exact=True).bounding_box()
        last = page.get_by_label("Last name", exact=True).bounding_box()
        assert abs(first["y"] - last["y"]) < 2 and first["x"] + first["width"] <= last["x"]
        assert first["width"] < 320
        page.locator('[data-settings-link="security"]').click()
        for card in page.locator('[data-settings-group="security"] .settings-card').all():
            assert card.locator(".workspace-button--primary:visible").count() <= 1
        expect(page.get_by_role("button", name="Save session timeout", exact=True)).not_to_have_class(
            re.compile("workspace-button--primary")
        )
    finally:
        context.close()


def test_phone_admin_categories_form_two_rows_without_sideways_scroll(browser, app_url, workspace_user):
    context, page = _page(browser, app_url, workspace_user, 390)
    try:
        page.goto("/core/settings")
        links = page.locator("[data-settings-link]")
        expect(links).to_have_count(4)
        boxes = [link.bounding_box() for link in links.all()]
        assert round(boxes[0]["y"]) == round(boxes[1]["y"])
        assert round(boxes[2]["y"]) == round(boxes[3]["y"])
        assert boxes[2]["y"] >= boxes[0]["y"] + boxes[0]["height"]
        assert round(boxes[0]["x"]) == round(boxes[2]["x"])
        assert round(boxes[1]["x"]) == round(boxes[3]["x"])
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1")
    finally:
        context.close()


def test_switching_category_keeps_a_draft_and_boosted_return_reloads(browser, app_url, workspace_user):
    context, page = _page(browser, app_url, workspace_user, 1440)
    try:
        page.goto("/core/settings")
        expect(page.get_by_label("First name", exact=True)).to_be_enabled()
        page.get_by_label("First name", exact=True).fill("Unsaved draft")
        _category(page, "security")
        expect(page.get_by_label("First name", exact=True)).to_be_hidden()
        _category(page, "account")
        expect(page.get_by_label("First name", exact=True)).to_have_value("Unsaved draft")
        page.evaluate("window.__settingsNavigationSentinel = true")
        page.get_by_role("link", name="Home", exact=True).first.click()
        _expect_home(page)
        page.get_by_role("link", name="Settings", exact=True).first.click()
        expect(page.locator("[data-settings-group]:visible")).to_have_count(1)
        expect(page.get_by_label("Email", exact=True)).to_have_value(workspace_user["email"])
        assert page.evaluate("window.__settingsNavigationSentinel")
    finally:
        context.close()


def test_repeated_boosted_visits_have_one_activity_ping(browser, app_url, workspace_user):
    context, page = _page(browser, app_url, workspace_user, 1440)
    try:
        page.goto("/core/dashboard")
        page.evaluate(
            "window.__settingsClock = Date.now; window.__settingsOffset = 0; Date.now = () => window.__settingsClock() + window.__settingsOffset"
        )
        for _ in range(3):
            page.get_by_role("link", name="Settings", exact=True).first.click()
            expect(page.locator("#settings-load-status")).to_be_hidden()
            expect(page.locator('[id="2fa-status-value"]')).to_have_text("Disabled")
            pings = []

            def record(request):
                if request.url.endswith("/auth/me"):
                    pings.append(request.url)

            page.on("request", record)
            with page.expect_response(lambda response: response.url.endswith("/auth/me")):
                page.evaluate("window.__settingsOffset += 30000; document.dispatchEvent(new Event('input'))")
            page.remove_listener("request", record)
            assert len(pings) == 1
            page.get_by_role("link", name="Home", exact=True).first.click()
            _expect_home(page)
    finally:
        context.close()


def test_departure_cancels_pending_profile_load(browser, app_url, workspace_user):
    context, page = _page(browser, app_url, workspace_user, 1440)
    try:
        page.add_init_script("""
          const originalFetch = window.fetch;
          window.fetch = function(input, options) {
            if (input === '/auth/settings' && (!options?.method || options.method === 'GET')) {
              window.__settingsPendingSignal = options?.signal;
              return new Promise((resolve, reject) => {
                options?.signal?.addEventListener('abort', () => reject(new DOMException('Left page', 'AbortError')), {once:true});
              });
            }
            return originalFetch.call(this, input, options);
          };
        """)
        page.goto("/core/settings")
        expect(page.locator("#settings-load-status")).to_have_text("Loading your account…")
        page.wait_for_function("window.__settingsPendingSignal !== undefined")
        page.get_by_role("link", name="Home", exact=True).first.click()
        _expect_home(page)
        assert page.evaluate("window.__settingsPendingSignal.aborted")
    finally:
        context.close()
