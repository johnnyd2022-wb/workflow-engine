"""The Licensing page in a browser: the four answers up front, dialogs instead of browser
prompts, the log, and the page's fit at phone, laptop and wall widths."""

from datetime import date, timedelta
from urllib.parse import urlsplit

import pytest
from playwright.sync_api import expect

from tests.test_licensing import _licence, flask_app, world  # noqa: F401

pytestmark = pytest.mark.e2e

HOST = "licensing.test"
PAGE = f"https://{HOST}/compliant/nz-alcohol/licensing"
READY = "[data-licensing-root][aria-busy='false']"
PHONE = {"width": 390, "height": 844}
LAPTOP = {"width": 1440, "height": 900}
WALL = {"width": 1920, "height": 1080}


def _open(browser, client, viewport=LAPTOP, query=""):
    """The page served by the test client through a route, so no live server is needed."""
    page = browser.new_page(viewport=viewport)

    def proxy(route):
        request = route.request
        parsed = urlsplit(request.url)
        if parsed.netloc != HOST:
            route.abort()
            return
        path = parsed.path + (f"?{parsed.query}" if parsed.query else "")
        response = client.open(
            path,
            method=request.method,
            data=request.post_data,
            headers={"Content-Type": request.headers.get("content-type", "application/json")},
        )
        route.fulfill(status=response.status_code, body=response.data, headers={"Content-Type": response.content_type})

    page.route("**/*", proxy)
    # A browser prompt here is a defect: dates and names are asked for in the page.
    page.native_dialogs = []
    page.on("dialog", lambda d: (page.native_dialogs.append(d.message), d.dismiss()))
    page.goto(PAGE + query)
    page.locator(READY).wait_for()
    return page


def _fact(page, label):
    return page.locator(".lic-fact", has_text=label).locator(".lic-fact__value")


def test_the_first_screen_answers_licence_managers_checks_and_log(world, browser):  # noqa: F811
    _licence(world["client"])  # expires in 70 days: the last day to file is about six weeks out
    page = _open(browser, world["client"])
    try:
        expect(_fact(page, "Licence")).to_have_text("Renewal due")
        expect(_fact(page, "Certified managers")).to_have_text("None current")
        expect(_fact(page, "Checks with proof")).to_contain_text("of 8 current")
        expect(_fact(page, "Incident and refusal log")).to_have_text("Nothing logged")
        expect(page.locator(".licensing-card .lic-status")).to_have_text("Renewal due")
    finally:
        page.close()


def test_renewal_lodged_asks_for_the_date_in_the_page_not_a_browser_prompt(world, browser):  # noqa: F811
    _licence(world["client"])
    page = _open(browser, world["client"])
    try:
        page.locator(".licensing-card").get_by_role("button", name="Renewal lodged").click()
        ask = page.locator("[data-lic-dialog='ask']")
        expect(ask).to_be_visible()
        lodged = (date.today() - timedelta(days=1)).isoformat()
        ask.locator("input").fill(lodged)
        ask.get_by_role("button", name="Save").click()
        expect(ask).to_be_hidden()
        expect(page.locator(".licensing-card .lic-status")).to_have_text(f"Renewal lodged {lodged}")
        expect(page.locator(".licensing-card").get_by_role("button", name="Renewal granted")).to_be_visible()
        assert page.native_dialogs == []
    finally:
        page.close()


def test_logging_a_refusal_from_the_header_adds_it_to_the_log(world, browser):  # noqa: F811
    page = _open(browser, world["client"])
    try:
        page.get_by_role("button", name="Log a refusal or incident").click()
        form = page.locator("[data-log-form]")
        form.locator("textarea[name='description']").fill("No ID at the cellar door; looked about 19.")
        form.get_by_role("button", name="Add to the log").click()
        expect(page.locator("[data-lic-dialog='log']")).to_be_hidden()
        expect(page.locator(".lic-row--log")).to_have_count(1)
        expect(page.locator(".lic-row--log")).to_contain_text("looked about 19")
        expect(_fact(page, "Incident and refusal log")).to_have_text("1 entry")
    finally:
        page.close()


def test_the_log_shows_the_latest_five_then_all_on_request(world, browser):  # noqa: F811
    client = world["client"]
    for n in range(7):
        client.post("/api/compliant/licensing/log", json={"kind": "id_refusal", "description": f"Refusal {n}"})
    page = _open(browser, client)
    try:
        expect(page.locator(".lic-row--log")).to_have_count(5)
        page.get_by_role("button", name="Show all 7 entries").click()
        expect(page.locator(".lic-row--log")).to_have_count(7)
    finally:
        page.close()


@pytest.mark.parametrize("viewport", [PHONE, LAPTOP, WALL], ids=["phone", "laptop", "wall"])
def test_the_page_fits_without_sideways_scroll(world, browser, viewport):  # noqa: F811
    client = world["client"]
    _licence(client)
    client.post("/api/compliant/licensing/log", json={"kind": "incident", "description": "A broken bottle."})
    page = _open(browser, client, viewport=viewport)
    try:
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        for region in ("#lic-licences", "#lic-managers", "#lic-checks", "#lic-log"):
            expect(page.locator(region)).to_be_visible()
        expect(page.locator("[data-style-pick]")).to_have_count(0)
    finally:
        page.close()
