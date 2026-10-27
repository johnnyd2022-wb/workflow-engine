"""GL-U03: a stock count whose save is interrupted keeps the number typed; saving again records it.

A count is a PUT to its line, so a retry overwrites rather than adds: it can't be counted twice.
"""

import pytest
from playwright.sync_api import expect

from tests.e2e.source_to_sale.conftest import BATCH, PRODUCT

pytestmark = pytest.mark.e2e


@pytest.mark.parametrize("how", ["offline", "signed-out"])
def test_an_interrupted_count_keeps_the_number_and_a_retry_saves_it(alcohol_scenario, how):
    page = alcohol_scenario["page"]
    page.goto("/core/stocktake")
    page.get_by_role("button", name="Customs is here").click()
    line = page.locator(".st-line", has_text=BATCH)
    expect(line).to_be_visible()
    counted = line.get_by_role("spinbutton", name=f"Counted {PRODUCT} {BATCH}")
    counted.fill("43")

    def fail(route):
        if route.request.method != "PUT":
            return route.continue_()
        if how == "offline":
            return route.abort("internetdisconnected")
        return route.fulfill(status=401, content_type="application/json", body='{"error": "Session expired"}')

    page.route("**/api/core/stocktakes/**", fail)
    line.get_by_role("button", name="Save", exact=True).click()
    page.wait_for_timeout(600)
    expect(counted).to_have_value("43")
    expect(line).not_to_contain_text("Difference to resolve")  # nothing claims it saved

    page.unroute("**/api/core/stocktakes/**")
    line.get_by_role("button", name="Save", exact=True).click()
    expect(line).to_contain_text("Difference to resolve")
    page.reload()  # the count was stored, not just shown
    expect(page.locator(".st-line", has_text=BATCH)).to_contain_text("Difference to resolve")
