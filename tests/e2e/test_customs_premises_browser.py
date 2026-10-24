"""Plan 7.1c: the Customs premises register in a browser.

A browser test, so it lives under tests/e2e, whose conftest checks that chromium is
installed and skips with a reason when it isn't.
"""

from datetime import date, timedelta
from urllib.parse import urlsplit

import pytest
from playwright.sync_api import expect

from tests.test_compliant_routes import flask_app  # noqa: F401 -- fixture re-export
from tests.test_customs_premises import clients, licence_data, world  # noqa: F401 -- fixture re-export

pytestmark = pytest.mark.e2e

HOST = "premises.test"
READY = "[data-premises-root][aria-busy='false']"


def _open(browser, client, width=390, query=""):
    page = browser.new_page(viewport={"width": width, "height": 844})

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
    page.goto(f"https://{HOST}/compliant/nz-alcohol/premises{query}")
    page.locator(READY).wait_for()
    return page


def _site_id(client):
    return client.get("/api/compliant/nz-alcohol/premises").get_json()["sites"][0]["id"]


def _cover(client, licence, **changes):
    body = {
        "licence_id": licence["id"],
        "site_id": _site_id(client),
        "location_id": None,
        "valid_from": licence["valid_from"],
        "valid_until": licence["valid_until"],
        "evidence_reference": "Plan",
        **changes,
    }
    assert client.post("/api/compliant/nz-alcohol/cca-coverage", json=body).status_code == 201


def test_phone_licence_and_area_forms_render_safe_text_and_fit(clients, browser):  # noqa: F811
    _, client, _, _ = clients
    page = _open(browser, client)
    try:
        # Both forms open in dialogs from the header now, instead of sitting above the register.
        page.get_by_role("button", name="Register a licence").click()
        form = page.locator("[data-licence-form]")
        for name, value in licence_data(name="Distillery <img src=x onerror=alert(1)>").items():
            if value is None:
                continue
            if name == "kind":
                form.locator(f'[name="{name}"]').select_option(value)
            else:
                form.locator(f'[name="{name}"]').fill(value)
        form.get_by_role("button", name="Register licence").click()
        page.get_by_role("heading", name="CCA-123 · Distillery <img src=x onerror=alert(1)>").wait_for()
        assert page.locator("[data-licences] img").count() == 0
        page.get_by_role("button", name="Assign an area").click()
        area = page.locator("[data-coverage-form]")
        area.locator('[name="licence_id"]').select_option(index=1)
        area.locator('[name="site_id"]').select_option(index=1)
        area.locator('[name="valid_from"]').fill("2026-01-01")
        area.locator('[name="evidence_reference"]').fill("Approved main area plan")
        area.get_by_role("button", name="Assign area").click()
        page.locator("[data-licences]").get_by_text("Approved main area plan").wait_for()
        assert page.locator("[data-premises-root] dialog[open]").count() == 0
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    finally:
        page.close()


def test_a_refused_area_shows_its_reason_inside_the_dialog(clients, browser):  # noqa: F811
    _, client, _, _ = clients
    client.post("/api/compliant/nz-alcohol/cca-licences", json=licence_data())
    page = _open(browser, client, width=1440)
    try:
        page.get_by_role("button", name="Assign an area").click()
        area = page.locator("[data-coverage-form]")
        area.locator('[name="licence_id"]').select_option(index=1)
        area.locator('[name="site_id"]').select_option(index=1)
        area.locator('[name="valid_from"]').fill("2020-01-01")  # before the licence starts
        area.locator('[name="evidence_reference"]').fill("Plan")
        area.get_by_role("button", name="Assign area").click()
        expect(area.locator("[data-form-error]")).to_contain_text("within the licence's valid dates")
        expect(page.locator("[data-prem-dialog='coverage']")).to_be_visible()
    finally:
        page.close()


def test_the_summary_and_areas_say_what_is_licensed_today(clients, browser):  # noqa: F811
    _, client, _, _ = clients
    today = date.today()
    licence = client.post(
        "/api/compliant/nz-alcohol/cca-licences",
        json=licence_data(
            valid_from=(today - timedelta(days=30)).isoformat(), valid_until=(today + timedelta(days=20)).isoformat()
        ),
    ).get_json()
    _cover(client, licence)
    page = _open(browser, client, width=1440, query="?style=2")
    try:
        expect(page.locator("[data-prem-summary]")).to_have_text(
            "1 area licensed under 1 current licence · CCA-123 ends in 20 days"
        )
        expect(page.locator(".prem-row--area .prem-status")).to_have_text(["Licensed · ends in 20 days"])
    finally:
        page.close()


# CONCEPT ONLY: deleted with the two layouts not picked.
@pytest.mark.parametrize("style", ["1", "2", "3"])
@pytest.mark.parametrize("width", [390, 1440, 1920], ids=["phone", "laptop", "wall"])
def test_each_layout_fits_without_sideways_scroll(clients, browser, style, width):  # noqa: F811
    _, client, _, _ = clients
    _cover(client, client.post("/api/compliant/nz-alcohol/cca-licences", json=licence_data()).get_json())
    page = _open(browser, client, width=width, query=f"?style={style}")
    try:
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
        region = {"1": ".prem-licences-card", "2": ".prem-areas-card", "3": ".prem-timeline-card"}[style]
        expect(page.locator(region)).to_be_visible()
        expect(page.locator(".prem-licences-card")).to_be_visible()
    finally:
        page.close()
