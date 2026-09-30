"""Explicit-site licence assignment on a phone browser."""

from urllib.parse import urlsplit

import pytest

from tests.test_licensing import _licence, flask_app, world  # noqa: F401
from tests.test_site_licensing import extra_site

pytestmark = pytest.mark.e2e


def test_phone_assigns_site_and_displays_hostile_name_as_text(world, browser):  # noqa: F811
    client = world["client"]
    old = _licence(client).get_json()["licences"][0]
    site = extra_site(world)
    page = browser.new_page(viewport={"width": 390, "height": 844})

    def proxy(route):
        request = route.request
        parsed = urlsplit(request.url)
        if parsed.netloc != "licensing.test":
            route.abort()
            return
        response = client.open(
            parsed.path,
            method=request.method,
            data=request.post_data,
            headers={"Content-Type": request.headers.get("content-type", "application/json")},
        )
        route.fulfill(status=response.status_code, body=response.data, headers={"Content-Type": response.content_type})

    page.route("**/*", proxy)
    try:
        page.goto("https://licensing.test/compliant/nz-alcohol/licensing")
        page.get_by_label("Site for " + old["licence_number"]).select_option(str(site.id))
        page.get_by_role("button", name="Assign site").click()
        page.locator(".licensing-card dd").get_by_text(site.name, exact=True).wait_for()
        assert page.locator(".licensing-card img").count() == 0
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    finally:
        page.close()
