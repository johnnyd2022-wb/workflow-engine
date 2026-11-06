"""GL-C04: Help and contact from any page, with the reference support needs.

Runs under the real CSP (strict_csp_page): the menu item, dialog and help.js need no inline
script or eval.
"""

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
