"""Food registration entry and scoped verification navigation on a phone."""

from urllib.parse import urlsplit

import pytest

from tests.test_compliant_routes import flask_app  # noqa: F401
from tests.test_food_registrations import clients, registration_data  # noqa: F401

pytestmark = pytest.mark.e2e


def test_phone_registration_scope_and_verification_context(clients, browser):  # noqa: F811
    _, client, _, _ = clients
    page = browser.new_page(viewport={"width": 390, "height": 844})

    def proxy(route):
        req = route.request
        parts = urlsplit(req.url)
        if parts.netloc != "food.test":
            route.abort()
            return
        path = parts.path + ("?" + parts.query if parts.query else "")
        response = client.open(
            path,
            method=req.method,
            data=req.post_data,
            headers={"Content-Type": req.headers.get("content-type", "application/json")},
        )
        route.fulfill(status=response.status_code, body=response.data, headers={"Content-Type": response.content_type})

    page.route("**/*", proxy)
    try:
        page.goto("https://food.test/compliant/nz-alcohol/food-registrations")
        form = page.locator("[data-food-registration-form]")
        for name, value in registration_data(name="Registration <img src=x>").items():
            if value is None:
                continue
            if name in {"programme", "registered_as"}:
                form.locator(f'[name="{name}"]').select_option(value)
            else:
                form.locator(f'[name="{name}"]').fill(value)
        form.get_by_role("button", name="Record registration").click()
        page.get_by_role("heading", name="NP-123 · Registration <img src=x>").wait_for()
        assert page.locator("[data-food-registration-list] img").count() == 0
        scope = page.locator("[data-food-scope-form]")
        scope.locator('[name="registration_id"]').select_option(index=1)
        scope.locator('[name="site_id"]').select_option(index=1)
        scope.locator('[name="activity"]').select_option("storage")
        scope.locator('[name="evidence_reference"]').fill("Scope schedule")
        scope.get_by_role("button", name="Record scope").click()
        page.locator("[data-food-scope-list]").get_by_text(
            "Registration <img src=x> · Scope schedule", exact=True
        ).wait_for()
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        page.get_by_role("link", name="Open verification history").click()
        page.locator("[data-verification-root]").wait_for()
        page.wait_for_function("document.querySelector('[data-verification-root]').dataset.registrationId !== ''")
        page.get_by_text("Initial verification due", exact=False).wait_for()
        assert page.locator("[data-verification-registration-select]").input_value()
        assert page.locator("[data-verification-registration]").is_hidden()
    finally:
        page.close()
