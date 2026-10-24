"""Compliance settings in a browser: a Save per section that saves only that section, keys set
elsewhere kept, the Licensing tab following the licence, a failed load that hides the settings,
and (CONCEPT ONLY) each layout's fit.

Requests are routed into the Flask test client (see test_customs_premises_browser).
"""

from urllib.parse import urlsplit

import pytest
from playwright.sync_api import expect

from tests.test_compliant_routes import flask_app  # noqa: F401 -- fixture re-export
from tests.test_customs_premises import clients  # noqa: F401 -- fixture re-export

pytestmark = pytest.mark.e2e

HOST = "settings.test"
READY = "[data-compliant-configuration-root][aria-busy='false']"
PROFILE = {
    "enabled": True,
    "industry_module": "nz_alcohol",
    "settings": {
        "alcohol_product_types": ["spirits"],
        "food_control_programme": "np3",
        "np3_check_review_intervals": {"allergen-management": 3},
    },
}


def _open(browser, client, width=1440, style="1"):
    page = browser.new_page(viewport={"width": width, "height": 900})

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
    page.goto(f"https://{HOST}/compliant/nz-alcohol/configuration?style={style}")
    page.locator(READY).wait_for()
    return page


def _set_up(client):
    assert client.put("/api/compliant/profile", json=PROFILE).status_code == 200


def _settings(client):
    return client.get("/api/compliant/overview").get_json()["profile"]["settings"]


def test_a_section_saves_only_itself_and_keeps_what_others_set(clients, browser):  # noqa: F811
    # The page was one form with one Save, so every save sent every field on it.
    _, client, _, _ = clients
    _set_up(client)
    page = _open(browser, client)
    try:
        page.locator("#licence input[name='liquor_licence_reference']").fill("LIQ/OFF/2026/114")
        evidence = page.locator("#evidence")
        evidence.locator("input[name='require_core_source_refs']").check()
        evidence.get_by_role("button", name="Save").click()
        expect(evidence.locator("[data-cs-saved]")).to_have_text("Saved.")
        settings = _settings(client)
        assert settings["require_core_source_refs"] is True
        assert not settings.get("liquor_licence_reference")
        # A check's own review interval, set on its page, survives.
        assert settings["np3_check_review_intervals"] == {"allergen-management": 3}
        expect(page.locator("#licence input[name='liquor_licence_reference']")).to_have_value("LIQ/OFF/2026/114")
    finally:
        page.close()


def test_choosing_a_licence_shows_the_licensing_tab(clients, browser):  # noqa: F811
    _, client, _, _ = clients
    _set_up(client)
    page = _open(browser, client)
    try:
        tab = page.locator("[data-section-tab='licensing']")
        expect(tab).to_be_hidden()
        licence = page.locator("#licence")
        licence.get_by_label("Off-licence").check()
        licence.get_by_role("button", name="Save").click()
        expect(tab).to_be_visible()
        assert _settings(client)["liquor_licence_types"] == ["off"]
    finally:
        page.close()


def test_settings_that_did_not_load_cannot_be_saved_over(clients, browser):  # noqa: F811
    # The form stayed on screen after a failed load with compliance unticked, so one Save
    # switched Compliance off.
    _, client, _, _ = clients
    _set_up(client)
    page = _open(browser, client)
    try:
        page.route(
            "**/api/compliant/overview", lambda route: route.fulfill(status=503, json={"error": "Could not load."})
        )
        page.reload()
        page.locator(READY).wait_for()
        expect(page.get_by_role("alert").filter(has_text="Could not load.")).to_be_visible()
        expect(page.locator("#workspace")).to_be_hidden()
        page.unroute("**/api/compliant/overview")
        page.get_by_role("button", name="Try again").click()
        expect(page.locator("#workspace input[name='enabled']")).to_be_checked()
    finally:
        page.close()


def test_the_visit_section_follows_the_programme(clients, browser):  # noqa: F811
    _, client, _, _ = clients
    _set_up(client)
    page = _open(browser, client)
    try:
        expect(page.locator("#visit")).to_be_visible()
        food = page.locator("#food-safety")
        food.locator("#cs-programme").select_option("none")
        expect(food.locator("#cs-review-interval")).to_be_hidden()
        food.get_by_role("button", name="Save").click()
        expect(page.locator("#visit")).to_be_hidden()
        expect(page.locator("[data-section-tab='np3']")).to_be_hidden()
    finally:
        page.close()


# CONCEPT ONLY: the rest are deleted with the two layouts not picked.
def test_read_first_shows_the_value_and_changes_it_in_place(clients, browser):  # noqa: F811
    _, client, _, _ = clients
    _set_up(client)
    page = _open(browser, client, style="3")
    try:
        products = page.locator("#products")
        expect(products.locator(".cs-read")).to_contain_text("Spirits")
        products.get_by_role("button", name="Change what leaves your site").click()
        products.get_by_label("Beer").check()
        products.get_by_role("button", name="Save").click()
        expect(products.locator(".cs-read")).to_contain_text("Spirits, Beer")
        expect(products.get_by_label("Beer")).to_be_hidden()
    finally:
        page.close()


def test_side_by_side_saves_every_changed_section_from_one_bar(clients, browser):  # noqa: F811
    _, client, _, _ = clients
    _set_up(client)
    page = _open(browser, client, style="2")
    try:
        bar = page.get_by_role("region", name="Unsaved changes")
        expect(bar).to_be_hidden()
        page.locator("#products").get_by_label("Cider").check()
        page.locator("#evidence input[name='require_core_source_refs']").check()
        expect(bar).to_contain_text("Unsaved changes to what leaves your site and evidence records")
        bar.get_by_role("button", name="Save changes").click()
        expect(bar).to_be_hidden()
        settings = _settings(client)
        assert (settings["alcohol_product_types"], settings["require_core_source_refs"]) == (["cider", "spirits"], True)
    finally:
        page.close()


@pytest.mark.parametrize("style", ["1", "2", "3"])
@pytest.mark.parametrize("width", [390, 1440, 1920], ids=["phone", "laptop", "wall"])
def test_each_layout_fits_without_sideways_scroll(clients, browser, style, width):  # noqa: F811
    _, client, _, _ = clients
    _set_up(client)
    page = _open(browser, client, width=width, style=style)
    try:
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
        for section in ("#workspace", "#products", "#food-safety", "#visit", "#licence", "#trade-waste", "#abv"):
            expect(page.locator(section)).to_be_visible()
    finally:
        page.close()
