"""Settings concepts keep every real control reachable and account load failures explicit."""

import pytest
from playwright.sync_api import expect

from tests.e2e.test_workspace_overviews import _page
from tests.e2e.test_workspace_overviews import workspace_user as _workspace_user

pytestmark = pytest.mark.e2e

workspace_user = _workspace_user


def _category(page, style, name):
    if style == "3":
        group = page.locator(f'[data-settings-group="{name}"]')
        if not group.evaluate("element => element.open"):
            group.locator("summary").click()
    else:
        page.locator(f'[data-settings-link="{name}"]').click()


# CONCEPT ONLY — retain the winning widths and remove losing cases after selection.
@pytest.mark.parametrize("style", ["1", "2", "3"])
@pytest.mark.parametrize("width", [390, 1024, 1440, 1920])
def test_concepts_keep_all_settings_reachable(browser, app_url, workspace_user, style, width):
    context, page = _page(browser, app_url, workspace_user, width)
    try:
        page.goto(f"/core/settings?style={style}")
        expect(page.locator(".settings-overview")).to_have_attribute("data-settings-style", style)
        expect(page.get_by_role("heading", level=1)).to_have_text("Settings")
        expect(page.get_by_label("First Name", exact=True)).to_be_enabled()
        for category, heading in [
            ("account", "Account information"),
            ("organisation", "Manage sites"),
            ("security", "Two-factor authentication"),
            ("preferences", "Appearance"),
        ]:
            _category(page, style, category)
            expect(page.get_by_role("heading", name=heading, exact=True)).to_be_visible()
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1")
        _category(page, style, "organisation")
        expect(page.get_by_role("link", name="View sites", exact=True)).to_have_attribute("href", "/core/sites")
        expect(page.get_by_role("link", name="Manage people", exact=True)).to_have_attribute("href", "/core/people")
    finally:
        context.close()


def test_profile_load_failure_disables_editing_until_retry(browser, app_url, workspace_user):
    context, page = _page(browser, app_url, workspace_user, 1440)
    try:
        page.route("**/auth/settings", lambda route: route.fulfill(status=503, json={"error": "unavailable"}))
        page.goto("/core/settings")
        expect(page.get_by_role("status").filter(has_text="Your account could not load")).to_be_visible()
        for label in ["First Name", "Last Name", "Email", "Phone Number"]:
            expect(page.get_by_label(label, exact=True)).to_be_disabled()
        expect(page.get_by_role("button", name="Save Changes", exact=True)).to_be_disabled()
        page.unroute("**/auth/settings")
        page.get_by_role("button", name="Retry account load", exact=True).click()
        expect(page.get_by_label("Email", exact=True)).to_have_value(workspace_user["email"])
        expect(page.get_by_role("button", name="Save Changes", exact=True)).to_be_enabled()
        expect(page.locator("#settings-load-status")).to_be_hidden()
    finally:
        context.close()


def test_notification_controls_are_explicitly_unavailable(browser, app_url, workspace_user):
    context, page = _page(browser, app_url, workspace_user, 1440)
    try:
        page.goto("/core/settings")
        expect(page.get_by_text("Notification preferences are not available yet.", exact=False)).to_be_visible()
        for name in ["Email Notifications", "Compliance Alerts", "Weekly Reports"]:
            expect(page.get_by_role("checkbox", name=name, exact=True)).to_be_disabled()
            expect(page.get_by_role("checkbox", name=name, exact=True)).not_to_be_checked()
        expect(page.get_by_role("checkbox", name="Dark mode", exact=True)).to_be_enabled()
    finally:
        context.close()


def test_concept_switch_preserves_draft_and_boosted_return(browser, app_url, workspace_user):
    context, page = _page(browser, app_url, workspace_user, 1440)
    try:
        page.goto("/core/settings?style=1")
        expect(page.get_by_label("First Name", exact=True)).to_be_enabled()
        page.get_by_label("First Name", exact=True).fill("Unsaved draft")
        page.get_by_role("button", name="2 · Settings desk", exact=True).click()
        _category(page, "2", "security")
        expect(page.get_by_label("First Name", exact=True)).to_be_hidden()
        _category(page, "2", "account")
        page.get_by_role("button", name="3 · Register", exact=True).click()
        expect(page.get_by_label("First Name", exact=True)).to_have_value("Unsaved draft")
        page.evaluate("window.__settingsNavigationSentinel = true")
        page.get_by_role("link", name="Home", exact=True).first.click()
        page.get_by_role("heading", name="Home", exact=True).wait_for()
        page.get_by_role("link", name="Settings", exact=True).first.click()
        expect(page.locator(".settings-overview")).to_have_attribute("data-settings-style", "3")
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
            expect(page.get_by_role("heading", name="Home", exact=True)).to_be_visible()
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
        expect(page.get_by_role("heading", name="Home", exact=True)).to_be_visible()
        assert page.evaluate("window.__settingsPendingSignal.aborted")
    finally:
        context.close()
