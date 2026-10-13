"""Plan 7.3a: the demand workspace on a phone.

A browser test, so it lives under tests/e2e, whose conftest checks that chromium is
installed and skips with a reason when it isn't.
"""

from urllib.parse import urlsplit

import pytest

from tests.features.planning.test_demand import demand_clients, demand_world  # noqa: F401 -- fixture re-export
from tests.test_compliant_routes import flask_app  # noqa: F401 -- fixture re-export

pytestmark = pytest.mark.e2e


def test_phone_workspace_creates_and_cancels_demand_without_overflow(demand_clients, browser):  # noqa: F811
    client, _, output_id = demand_clients[0]
    page = browser.new_page(viewport={"width": 390, "height": 844})

    def proxy(route):
        request = route.request
        parsed = urlsplit(request.url)
        if parsed.netloc != "planner.test":
            route.abort()
            return
        response = client.open(
            parsed.path + ("?" + parsed.query if parsed.query else ""),
            method=request.method,
            data=request.post_data,
            headers={"Content-Type": request.headers.get("content-type", "application/json")},
        )
        route.fulfill(status=response.status_code, body=response.data, headers={"Content-Type": response.content_type})

    page.route("**/*", proxy)
    try:
        page.goto("https://planner.test/core/planner")
        page.locator('[data-output-select] option[value="' + str(output_id) + '"]').wait_for(state="attached")
        # The form sits behind the page's primary action, so the demand itself is the first thing shown.
        assert not page.locator('[name="reference"]').is_visible()
        page.get_by_role("button", name="Add demand", exact=True).first.click()
        page.locator('[name="reference"]').fill("Phone order <script>alert(1)</script>")
        page.locator('[name="source_output_id"]').select_option(str(output_id))
        page.locator('[name="quantity"]').fill("600")
        page.locator('[name="due_date"]').fill("2026-10-10")
        page.get_by_role("button", name="Save demand", exact=True).click()
        page.get_by_role("heading", name="Phone order <script>alert(1)</script>").wait_for()
        assert not page.locator('[name="reference"]').is_visible()
        assert page.locator("[data-demand-list] script").count() == 0
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
        assert page.locator("[data-planning-root] input, [data-planning-root] select").evaluate_all(
            "elements => elements.every(el => { const r = el.getBoundingClientRect(); "
            "return r.left >= 0 && r.right <= window.innerWidth; })"
        )
        page.get_by_role("button", name="Cancel demand").click()
        # A cancelled demand leaves the open list for the closed one, labelled in words.
        page.locator("[data-closed] > summary").click()
        closed = page.locator("[data-closed-list] .planner-row")
        closed.get_by_text("Cancelled", exact=True).wait_for()
        assert closed.locator(".planner-due").get_attribute("title") == "2026-10-10"
        assert page.locator("[data-demand-list] .planner-row").count() == 0
        assert page.get_by_role("button", name="Cancel demand").count() == 0
    finally:
        page.close()
