"""GL-C04: Help and contact from any page, with the reference support needs.

Runs under the real CSP (strict_csp_page): the menu item, dialog and help.js need no inline
script or eval.
"""

import os
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

import pytest
from playwright.sync_api import expect

from tests.e2e.conftest import assert_clean_page

pytestmark = pytest.mark.e2e


def _open_help(page):
    page.get_by_role("button", name="Account menu").click()
    page.get_by_role("menuitem", name="Help and contact").click()
    dialog = page.locator("#bize-help")
    expect(dialog).to_be_visible()
    return dialog


def _mail_query(dialog) -> dict:
    href = dialog.locator("#bize-help-mail").get_attribute("href")
    assert href.startswith("mailto:support@biz-e.app?")
    return {k: unquote(v[0]) for k, v in parse_qs(urlsplit(href).query).items()}


@pytest.mark.parametrize("width", [1440, 390])
def test_help_shows_this_pages_reference_and_a_ready_to_send_email(strict_csp_page, width):
    page = strict_csp_page
    page.set_viewport_size({"width": width, "height": 900})
    response = page.goto("/core/settings")
    expected = response.headers["x-request-id"].replace("-", "")[:8].lower()

    dialog = _open_help(page)
    expect(dialog.get_by_test_id("help-reference")).to_have_text(expected)
    expect(dialog.locator("#bize-help-page")).to_contain_text("(/core/settings)")
    mail = _mail_query(dialog)
    assert mail["subject"] == f"biz-e help (ref {expected})"
    assert f"Reference: {expected}" in mail["body"] and "Page: " in mail["body"]
    expect(dialog.locator("#bize-help-error-row")).to_be_hidden()

    page.keyboard.press("Escape")
    expect(dialog).to_be_hidden()
    expect(page.get_by_role("button", name="Account menu")).to_be_focused()
    assert_clean_page(page)


def test_the_reference_follows_a_boosted_navigation(strict_csp_page):
    page = strict_csp_page
    page.goto("/core/settings")
    first = page.locator('meta[name="request-reference"]').get_attribute("content")
    # Another Settings tab: a boosted navigation swaps only #page-content, so the <meta> in <head>
    # keeps the first page's reference and help.js must take the new one from the response.
    other = page.get_by_role("tablist", name="Settings pages").locator("[role=tab]:not([aria-selected=true])").first
    target = other.get_attribute("href")
    with page.expect_response(lambda r: r.url.endswith(target) and r.request.method == "GET") as nav:
        other.click()
    page.wait_for_url(f"**{target}")
    after = nav.value.headers["x-request-id"].replace("-", "")[:8].lower()
    assert after != first

    dialog = _open_help(page)
    expect(dialog.get_by_test_id("help-reference")).to_have_text(after)
    assert_clean_page(page)


def test_a_boosted_missing_page_shows_its_error_reference(strict_csp_page):
    page = strict_csp_page
    page.goto("/core/settings")
    console_before = set(page.probe.console_errors)
    page.evaluate("""() => {
      const link = document.createElement('a');
      link.id = 'missing-page-probe';
      link.href = '/core/boosted-page-that-does-not-exist';
      link.textContent = 'Missing page';
      document.querySelector('#page-content').append(link);
      window.htmx.process(link);
    }""")

    with page.expect_response(
        lambda response: response.url.endswith("/core/boosted-page-that-does-not-exist")
    ) as failed:
        page.locator("#missing-page-probe").click()
    response = failed.value
    assert response.status == 404
    reference = response.headers["x-request-id"].replace("-", "")[:8].lower()

    expect(page.locator("#notification-modal")).to_be_visible()
    expect(page.locator("#notification-title")).to_have_text("Page not found")
    expect(page.locator("#notification-message")).to_contain_text(f"Reference: {reference}")
    # A failed boosted response must leave the current screen usable and not inject its full page.
    expect(page.locator("#page-content")).to_contain_text("Settings")
    page.locator("#missing-page-probe").evaluate("link => link.remove()")

    screenshot_dir = os.environ.get("BOOSTED_ERROR_SHOTS_DIR")
    if screenshot_dir:
        destination = Path(screenshot_dir)
        destination.mkdir(parents=True, exist_ok=True)
        for name, width, theme in (
            ("desktop-light", 1440, "light"),
            ("phone-light", 390, "light"),
            ("desktop-dark", 1440, "dark"),
            ("phone-dark", 390, "dark"),
        ):
            page.set_viewport_size({"width": width, "height": 900 if width > 480 else 844})
            page.evaluate("theme => document.documentElement.setAttribute('data-spa-theme', theme)", theme)
            page.wait_for_timeout(120)
            page.screenshot(path=str(destination / f"boosted-error-{name}.png"), full_page=True)

    page.get_by_role("button", name="Account menu", exact=True).click()
    page.get_by_role("menuitem", name="Help and contact").click()
    dialog = page.locator("#bize-help")
    expect(dialog.locator("#bize-help-error-row")).to_be_visible()
    expect(dialog.get_by_test_id("help-last-error")).to_contain_text(f"{reference} (404")
    # HTMX logs this intentional non-2xx response as a console diagnostic; no other client
    # errors or transport failures should be introduced by the handler.
    assert set(page.probe.console_errors) - console_before == {
        "Response Status Error Code 404 from /core/boosted-page-that-does-not-exist"
    }
    assert not page.probe.failed_requests and not page.probe.server_errors


def test_a_boosted_server_error_shows_its_error_reference(strict_csp_page):
    page = strict_csp_page
    page.goto("/core/settings")
    console_before = set(page.probe.console_errors)
    request_id = "deadbeef-1111-4222-8333-444455556666"
    path = "/core/boosted-page-server-error"
    page.route(
        f"**{path}",
        lambda route: route.fulfill(
            status=500,
            headers={"X-Request-ID": request_id, "Content-Type": "text/html"},
            body="<main><h1>Something went wrong on our side</h1><p>Internal detail must not be exposed.</p></main>",
        ),
    )
    page.evaluate(
        """path => {
      const link = document.createElement('a');
      link.id = 'server-error-probe';
      link.href = path;
      link.textContent = 'Server error';
      document.querySelector('#page-content').append(link);
      window.htmx.process(link);
    }""",
        path,
    )

    with page.expect_response(lambda response: response.url.endswith(path)) as failed:
        page.locator("#server-error-probe").click()
    assert failed.value.status == 500
    expect(page.locator("#notification-modal")).to_be_visible()
    expect(page.locator("#notification-title")).to_have_text("Page could not load")
    expect(page.locator("#notification-message")).to_contain_text("Reference: deadbeef")
    expect(page.locator("#notification-message")).not_to_contain_text("Internal detail")

    page.get_by_role("button", name="Account menu", exact=True).click()
    page.get_by_role("menuitem", name="Help and contact").click()
    dialog = page.locator("#bize-help")
    expect(dialog.locator("#bize-help-error-row")).to_be_visible()
    expect(dialog.get_by_test_id("help-last-error")).to_contain_text("deadbeef (500")
    assert set(page.probe.console_errors) - console_before == {f"Response Status Error Code 500 from {path}"}
    assert not page.probe.failed_requests
    assert page.probe.server_errors == [f"500 GET {failed.value.url}"]


def test_a_boosted_forbidden_page_shows_no_access_copy_and_reference(strict_csp_page):
    page = strict_csp_page
    page.goto("/core/settings")
    console_before = set(page.probe.console_errors)
    request_id = "403403ab-1111-4222-8333-444455556666"
    path = "/core/boosted-page-forbidden"
    page.route(
        f"**{path}",
        lambda route: route.fulfill(
            status=403,
            headers={"X-Request-ID": request_id, "Content-Type": "text/html"},
            body="<main><h1>Forbidden</h1><p>Internal authorization detail.</p></main>",
        ),
    )
    page.evaluate(
        """path => {
      const link = document.createElement('a');
      link.id = 'forbidden-page-probe';
      link.href = path;
      link.textContent = 'Forbidden page';
      document.querySelector('#page-content').append(link);
      window.htmx.process(link);
    }""",
        path,
    )

    with page.expect_response(lambda response: response.url.endswith(path)) as failed:
        page.locator("#forbidden-page-probe").click()
    assert failed.value.status == 403
    expect(page.locator("#notification-modal")).to_be_visible()
    expect(page.locator("#notification-title")).to_have_text("No access to that page")
    expect(page.locator("#notification-message")).to_contain_text(
        "Your role can't open that page. Ask an admin if you need it."
    )
    expect(page.locator("#notification-message")).to_contain_text("Reference: 403403ab")
    expect(page.locator("#notification-message")).not_to_contain_text("Internal authorization detail")
    expect(page.locator("#page-content")).to_contain_text("Settings")
    page.locator("#forbidden-page-probe").evaluate("link => link.remove()")

    screenshot_dir = os.environ.get("BOOSTED_403_SHOTS_DIR")
    if screenshot_dir:
        destination = Path(screenshot_dir)
        destination.mkdir(parents=True, exist_ok=True)
        for name, width, theme in (
            ("desktop-light", 1440, "light"),
            ("phone-light", 390, "light"),
            ("desktop-dark", 1440, "dark"),
            ("phone-dark", 390, "dark"),
        ):
            page.set_viewport_size({"width": width, "height": 900 if width > 480 else 844})
            page.evaluate("theme => document.documentElement.setAttribute('data-spa-theme', theme)", theme)
            page.wait_for_timeout(400)
            page.screenshot(path=str(destination / f"boosted-403-{name}.png"), full_page=True)

    page.get_by_role("button", name="Account menu", exact=True).click()
    page.get_by_role("menuitem", name="Help and contact").click()
    dialog = page.locator("#bize-help")
    expect(dialog.locator("#bize-help-error-row")).to_be_visible()
    expect(dialog.get_by_test_id("help-last-error")).to_contain_text("403403ab (403")
    assert set(page.probe.console_errors) - console_before == {f"Response Status Error Code 403 from {path}"}
    assert not page.probe.failed_requests and not page.probe.server_errors


def test_a_request_that_failed_on_the_server_is_offered_as_the_reference(strict_csp_page):
    page = strict_csp_page
    page.goto("/core/settings")
    page.route(
        "**/api/core/help-probe",
        lambda route: route.fulfill(
            status=500,
            headers={"X-Request-ID": "deadbeef-1111-4222-8333-444455556666", "Content-Type": "application/json"},
            body='{"error": "Something went wrong on our side", "reference": "deadbeef"}',
        ),
    )
    page.evaluate("() => fetch('/api/core/help-probe').then(r => r.status)")

    dialog = _open_help(page)
    expect(dialog.get_by_test_id("help-last-error")).to_contain_text("deadbeef (500")
    mail = _mail_query(dialog)
    assert mail["subject"] == "biz-e help (ref deadbeef)"
    assert "Last error: deadbeef (500 on /api/core/help-probe)" in mail["body"]
