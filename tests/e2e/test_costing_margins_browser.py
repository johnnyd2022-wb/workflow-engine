"""Margins report behaviour in a real browser with a controlled report response."""

from __future__ import annotations

import pytest
from playwright.sync_api import expect

from app.core.db.models.user import UserRole
from tests.e2e.conftest import login_through_ui

pytestmark = pytest.mark.e2e

PAGE = "/core/costing/margins"


@pytest.fixture
def margins_user(fresh_user, page, db):
    user = fresh_user(UserRole.ADMIN)
    from app.core.db.repositories.feature_subscription_repo import FeatureSubscriptionRepository

    FeatureSubscriptionRepository(db).grant(user["org_id"], "costing")
    db.commit()
    login_through_ui(page, user["email"], user["password"])
    return user


def _report():
    return {
        "from": "2026-01",
        "to": "2026-02",
        "currency": "AUD",
        "rows": [
            {
                "product": "Limoncello",
                "month": "2026-01",
                "units": 4,
                "revenue": 100,
                "cost": 30,
                "duty_tracked": True,
                "duty": 12,
                "margin": 58,
                "margin_percent": 58,
                "average_cost_per_unit": 7.5,
                "cost_status": "estimated",
                "lines": [
                    {
                        "reference": "INV-0101",
                        "sold_on": "2026-01-14",
                        "units": "4",
                        "revenue": "100.00",
                        "unbatched_units": "1",
                        "unbatched_status": "unknown",
                        "batches": [
                            {
                                "name": "Limoncello",
                                "batch": "L-07",
                                "units": "2",
                                "unit_cost": "7.50",
                                "status": "actual",
                            },
                            {
                                "name": "Limoncello",
                                "batch": "L-08",
                                "units": "1",
                                "unit_cost": "8.00",
                                "status": "estimated",
                            },
                        ],
                    }
                ],
            },
            {
                "product": "Limoncello",
                "month": "2026-02",
                "units": 3,
                "revenue": 80,
                "cost": 24,
                "duty_tracked": True,
                "duty": None,
                "margin": None,
                "margin_percent": None,
                "average_cost_per_unit": 8,
                "cost_status": "actual",
                "lines": [],
            },
        ],
    }


def test_margins_currency_completeness_reload_accordion_and_boosted_return(margins_user, page, app_url):
    responses = []

    def margins_response(route):
        responses.append(route.request.url)
        if "from=2026-03" in route.request.url:
            route.fulfill(status=503, json={"error": "Report unavailable"})
        else:
            route.fulfill(json=_report())

    page.route("**/api/core/costing/margins**", margins_response)
    page.goto(app_url + PAGE)
    root = page.locator("[data-margins-root][aria-busy='false']")
    root.wait_for()
    assert "from=2026-01" in page.url and "to=2026-02" in page.url, "the range shown is in the address"

    expect(page.locator("[data-margins-summary]")).to_contain_text("A$180.00")
    expect(page.locator("[data-margins-summary]")).to_contain_text("Complete for 1 of 2 months")
    expect(page.locator("[data-margins-summary]")).to_contain_text("—")
    expect(page.locator("[data-margins-list]")).to_contain_text("Margin —")
    expect(page.locator("[data-margins-list]")).to_contain_text("Complete for 1 of 2 months")

    product = page.get_by_role("button", name="Limoncello")
    product.focus()
    page.keyboard.press("Enter")
    expect(product).to_have_attribute("aria-expanded", "true")
    month = page.get_by_role("button", name="Jan 2026")
    month.focus()
    page.keyboard.press("Space")
    expect(month).to_have_attribute("aria-expanded", "true")
    expect(page.locator(".mg-sale-lines")).to_have_count(1)
    sale = page.locator(".mg-sale__batches")
    expect(sale).to_contain_text("Batch L-07: 2 at A$7.50 ·")
    expect(sale).to_contain_text("Batch L-08: 1 at A$8.00 (estimated)")
    expect(sale).to_contain_text("1 not matched to a batch — no cost for this product yet")

    page.evaluate("""() => {
      const link = document.createElement('a');
      link.href = '/core/inventory/view';
      link.id = '__margins_boost_probe';
      document.querySelector('#page-content').prepend(link);
      window.htmx.process(link);
      link.click();
    }""")
    page.wait_for_url("**/core/inventory/view")
    page.go_back()
    page.locator("[data-margins-root][aria-busy='false']").wait_for()
    expect(page.locator("[data-margins-summary]")).to_contain_text("A$180.00")

    page.locator("#mg-from").fill("2026-03")
    page.locator("#mg-to").fill("2026-03")
    page.evaluate("""() => {
      const realFetch = window.fetch.bind(window);
      window.fetch = (url, options) => String(url).includes('from=2026-03')
        ? new Promise((resolve) => setTimeout(() => resolve(realFetch(url, options)), 500))
        : realFetch(url, options);
    }""")
    page.get_by_role("button", name="Show").click()
    expect(page.locator("[data-margins-loading]")).to_be_visible()
    expect(page.locator("[data-margins-summary]")).to_be_hidden()
    expect(page.locator("[data-margins-list]")).to_be_empty()
    expect(page.locator("[data-margins-error]")).to_have_text("Report unavailable")
    expect(page.locator("[data-margins-loading]")).to_be_hidden()
    expect(page.locator("[data-margins-summary]")).to_be_hidden()
    expect(page.locator("[data-margins-note]")).to_be_hidden()
    expect(page.locator("[data-margins-list]")).to_be_empty()
    expect(page.locator("[data-margins-empty]")).to_be_hidden()

    assert len(responses) >= 3


def test_a_month_with_any_unknown_figure_is_left_out_of_the_range_total(margins_user, page, app_url):
    """Review r4: two products in January, one with no usable revenue: January's revenue is left out
    of the total entirely (not $100 of it), and the summary says so."""

    def row(product, revenue):
        return {
            "product": product,
            "month": "2026-01",
            "units": 1,
            "revenue": revenue,
            "cost": 10,
            "duty_tracked": False,
            "duty": None,
            "margin": None if revenue is None else 90,
            "margin_percent": None,
            "average_cost_per_unit": 10,
            "cost_status": "actual",
            "lines": [],
        }

    body = {"from": "2026-01", "to": "2026-01", "currency": "NZD", "rows": [row("Gin", 100), row("Limoncello", None)]}
    page.route("**/api/core/costing/margins**", lambda route: route.fulfill(json=body))
    page.goto(app_url + PAGE)
    page.locator("[data-margins-root][aria-busy='false']").wait_for()
    summary = page.locator("[data-margins-summary]")
    expect(summary).to_contain_text("Complete for 0 of 1 months")
    expect(summary).not_to_contain_text("$100.00")


def test_a_slow_report_never_rewrites_the_page_navigated_to(margins_user, page, app_url):
    """Review r4: the default range is written to the address only while Margins is still showing."""
    import time

    def slow(route):
        time.sleep(1.5)
        route.fulfill(json=_report())

    page.route("**/api/core/costing/margins**", slow)
    page.goto(app_url + PAGE)
    page.evaluate("""() => {
      const link = document.createElement('a');
      link.href = '/core/inventory/view';
      document.querySelector('#page-content').prepend(link);
      window.htmx.process(link);
      link.click();
    }""")
    page.wait_for_url("**/core/inventory/view")
    page.wait_for_timeout(2500)
    assert "from=" not in page.url and page.url.endswith("/core/inventory/view")
