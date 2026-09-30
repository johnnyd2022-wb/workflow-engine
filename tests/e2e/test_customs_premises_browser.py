"""Plan 7.1c: the Customs premises register on a phone.

A browser test, so it lives under tests/e2e, whose conftest checks that chromium is
installed and skips with a reason when it isn't.
"""

from urllib.parse import urlsplit

import pytest

from tests.test_compliant_routes import flask_app  # noqa: F401 -- fixture re-export
from tests.test_customs_premises import clients, licence_data, world  # noqa: F401 -- fixture re-export

pytestmark = pytest.mark.e2e


def test_phone_licence_and_area_forms_render_safe_text_and_fit(clients, browser):  # noqa: F811
    _, client, _, _ = clients
    page = browser.new_page(viewport={"width": 390, "height": 844})

    def proxy(route):
        request = route.request
        parsed = urlsplit(request.url)
        if parsed.netloc != "premises.test":
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
        page.goto("https://premises.test/compliant/nz-alcohol/premises")
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
        area = page.locator("[data-coverage-form]")
        area.locator('[name="licence_id"]').select_option(index=1)
        area.locator('[name="site_id"]').select_option(index=1)
        area.locator('[name="valid_from"]').fill("2026-01-01")
        area.locator('[name="evidence_reference"]').fill("Approved main area plan")
        area.get_by_role("button", name="Assign area").click()
        page.locator("[data-coverage]").get_by_text("Approved main area plan").wait_for()
        assert page.locator("[data-premises-root] input, [data-premises-root] select").evaluate_all(
            "elements => elements.every(el => { const r = el.getBoundingClientRect(); "
            "return r.left >= 0 && r.right <= window.innerWidth; })"
        )
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    finally:
        page.close()
