"""Costs page material prices in a browser, including boosted re-entry."""

from __future__ import annotations

import pytest
from playwright.sync_api import expect

from tests.e2e.conftest import login_through_ui

pytestmark = pytest.mark.e2e

PAGE = "/core/costing/costs"


@pytest.fixture
def costs_page(fresh_user, page, app_url, db):
    from app.core.db.models.user import UserRole
    from app.core.db.repositories.feature_subscription_repo import FeatureSubscriptionRepository

    user = fresh_user(UserRole.ADMIN)
    FeatureSubscriptionRepository(db).grant(user["org_id"], "costing")
    db.commit()
    login_through_ui(page, user["email"], user["password"])
    return page, app_url


def _mock_costs(page, materials):
    history_calls = []
    materials_calls = []

    def mocked(route):
        url = route.request.url
        if url.endswith("/readiness"):
            route.fulfill(json={"products": []})
        elif url.endswith("/me"):
            route.fulfill(json={"enabled": True, "can_view": True, "can_manage": True})
        elif url.endswith("/materials"):
            materials_calls.append(url)
            route.fulfill(json={"materials": materials})
        elif "/materials/" in url and url.endswith("/history"):
            name = url.split("/materials/", 1)[1].split("/history", 1)[0]
            history_calls.append(name)
            route.fulfill(
                json={
                    "unit": "kg",
                    "from": "2026-10",
                    "to": "2026-11",
                    "too_large": False,
                    "months": [
                        {
                            "month": "2026-10",
                            "average_unit_cost": "0.000012",
                            "priced_quantity": "2",
                            "purchases": 0,
                            "amount": "0.000024",
                            "min_unit_price": "0.000012",
                            "max_unit_price": "0.000012",
                            "unconverted": 0,
                        },
                        {
                            "month": "2026-11",
                            "average_unit_cost": "0.00002",
                            "priced_quantity": "3",
                            "purchases": 1,
                            "amount": "0.00006",
                            "min_unit_price": "0.00002",
                            "max_unit_price": "0.00002",
                            "unconverted": 0,
                        },
                    ],
                }
            )
        else:
            route.continue_()

    page.route("**/api/core/costing/**", mocked)
    return history_calls, materials_calls


def test_material_prices_render_and_expand_with_accessible_unique_ids(costs_page):
    page, app_url = costs_page
    rows = [
        {"name": "A/B", "unit": "kg", "latest_unit_price": "0.000012", "latest_date": "2026-11-10"},
        {"name": "A-B", "unit": "kg", "latest_unit_price": "2.500000", "latest_date": "2026-11-10"},
        {"name": "日本語", "unit": "kg", "latest_unit_price": None, "latest_reason": "other_units"},
        {"name": "Huge History", "unit": "kg", "latest_unit_price": None, "latest_reason": "too_large"},
    ]
    calls, _materials_calls = _mock_costs(page, rows)
    page.goto(app_url + PAGE)
    expect(page.locator("[data-costs-root][aria-busy='false']")).to_be_visible()
    expect(page.locator("[data-prices]")).to_be_visible()
    expect(page.locator("[data-prices-list] .co-row")).to_have_count(4)
    expect(page.locator(".co-price__value").first).to_have_text("<$0.0001 / kg")
    expect(page.locator(".co-price__when").filter(has_text="other units")).to_have_count(1)
    expect(page.locator(".co-price__when").filter(has_text="too large")).to_have_count(1)

    controls = page.locator("[data-prices-list] .co-row__head")
    control_ids = [controls.nth(i).get_attribute("aria-controls") for i in range(4)]
    assert len(set(control_ids)) == 4
    for i, detail_id in enumerate(control_ids):
        assert page.locator(f"#{detail_id}").count() == 1
        assert controls.nth(i).get_attribute("aria-expanded") == "false"

    controls.first.click()
    expect(controls.first).to_have_attribute("aria-expanded", "true")
    detail = page.locator(f"#{control_ids[0]}")
    expect(detail).to_be_visible()
    expect(detail.locator(".co-trend")).to_contain_text("<$0.0001")
    expect(detail.locator(".co-months")).to_contain_text("Quantity priced")
    expect(detail.locator(".co-months")).not_to_contain_text("Bought")
    assert len(calls) == 1


def test_price_rows_keep_aria_controls_unique_for_similar_names(costs_page):
    page, app_url = costs_page
    _mock_costs(
        page,
        [
            {"name": "A/B", "unit": "kg", "latest_unit_price": "1", "latest_date": "2026-11-10"},
            {"name": "A-B", "unit": "kg", "latest_unit_price": "2", "latest_date": "2026-11-10"},
            {"name": "日本語", "unit": "kg", "latest_unit_price": "3", "latest_date": "2026-11-10"},
        ],
    )
    page.goto(app_url + PAGE)
    expect(page.locator("[data-prices-list] .co-row")).to_have_count(3)
    controls = page.locator("[data-prices-list] .co-row__head")
    ids = [controls.nth(i).get_attribute("aria-controls") for i in range(3)]
    assert len(set(ids)) == 3
    assert all(page.locator(f"#{detail_id}").count() == 1 for detail_id in ids)


def test_price_history_labels_priced_quantity_not_purchases(costs_page):
    page, app_url = costs_page
    _mock_costs(
        page,
        [{"name": "Manually priced", "unit": "kg", "latest_unit_price": "1", "latest_date": "2026-11-10"}],
    )
    page.goto(app_url + PAGE)
    expect(page.locator("[data-prices-list] .co-row")).to_have_count(1)
    page.locator("[data-prices-list] .co-row__head").click()
    table = page.locator(".co-months")
    expect(table).to_contain_text("Quantity priced")
    detail = page.locator("[data-prices-list] .co-row__detail")
    expect(detail).not_to_contain_text("ought")  # neither "Bought" nor "bought" anywhere in it


def test_unavailable_latest_price_explains_each_reason(costs_page):
    page, app_url = costs_page
    _mock_costs(
        page,
        [
            {"name": "Other units", "unit": "kg", "latest_unit_price": None, "latest_reason": "other_units"},
            {"name": "Huge History", "unit": "kg", "latest_unit_price": None, "latest_reason": "too_large"},
        ],
    )
    page.goto(app_url + PAGE)
    expect(page.locator("[data-prices-list] .co-row")).to_have_count(2)
    expect(page.locator(".co-price__when").filter(has_text="Price is in other units")).to_have_count(1)
    expect(page.locator(".co-price__when").filter(has_text="History too large to calculate")).to_have_count(1)


@pytest.mark.parametrize(
    ("materials", "state", "message"),
    [([], "[data-prices-empty]", "No material prices yet"), (None, "[data-prices-error]", "Prices couldn’t load")],
)
def test_material_price_empty_and_error_states_are_visible(costs_page, materials, state, message):
    page, app_url = costs_page

    def mocked(route):
        if route.request.url.endswith("/readiness"):
            route.fulfill(json={"products": []})
        elif route.request.url.endswith("/me"):
            route.fulfill(json={})
        elif route.request.url.endswith("/materials"):
            if materials is None:
                route.fulfill(status=503, json={"error": "Service unavailable"})
            else:
                route.fulfill(json={"materials": materials})
        else:
            route.continue_()

    page.route("**/api/core/costing/**", mocked)
    page.goto(app_url + PAGE)
    expect(page.locator("[data-costs-root][aria-busy='false']")).to_be_visible()
    expect(page.locator("[data-prices]")).to_be_visible()
    state_locator = page.locator(state)
    expect(state_locator).to_be_visible()
    expect(state_locator).to_contain_text(message)
    if materials is None:
        expect(state_locator).to_have_attribute("role", "alert")
        expect(state_locator).to_have_attribute("aria-live", "assertive")


def test_prices_rebind_after_boosted_navigation_away_and_back(costs_page):
    page, app_url = costs_page
    _history_calls, materials_calls = _mock_costs(
        page,
        [{"name": "Coriander", "unit": "kg", "latest_unit_price": "1.25", "latest_date": "2026-11-10"}],
    )
    page.goto(app_url + PAGE)
    expect(page.locator("[data-prices-list] .co-row")).to_have_count(1)

    page.evaluate(
        """() => {
          const a = document.createElement('a'); a.href = '/core/inventory/view'; a.textContent = 'Inventory';
          document.querySelector('#page-content').prepend(a); window.htmx.process(a); a.click();
        }"""
    )
    page.wait_for_url("**/core/inventory/view")
    page.evaluate(
        """() => {
          const a = document.createElement('a'); a.href = '/core/costing/costs'; a.textContent = 'Costs';
          document.querySelector('#page-content').prepend(a); window.htmx.process(a); a.click();
        }"""
    )
    page.wait_for_url("**/core/costing/costs")
    expect(page.locator("[data-prices-list] .co-row")).to_have_count(1)
    assert page.locator("[data-costs-root]").get_attribute("data-bound") == "1"
    assert len(materials_calls) >= 2, "the prices endpoint should be requested on both boosted arrivals"


def test_one_month_of_manual_prices_never_says_bought(costs_page):
    """Review r2: manual and free entries are prices, not purchases, in the sentence too."""
    page, app_url = costs_page
    history = {
        "name": "Hand priced",
        "unit": "kg",
        "from": "2025-12",
        "to": "2026-11",
        "months": [
            {
                "month": "2026-11",
                "unit": "kg",
                "amount": "12.00",
                "priced_quantity": "2",
                "average_unit_cost": "6.000000",
                "purchases": 0,
                "min_unit_price": "6.000000",
                "max_unit_price": "6.000000",
                "unconverted": 0,
            }
        ],
        "latest": {"unit_price": "6.000000", "date": "2026-11-10T09:00:00+13:00", "source": "manual"},
        "lots": [],
        "too_large": False,
    }
    page.route("**/api/core/costing/materials/*/history**", lambda route: route.fulfill(json=history))
    page.route(
        "**/api/core/costing/materials",
        lambda route: route.fulfill(
            json={
                "materials": [
                    {"name": "Hand priced", "unit": "kg", "latest_unit_price": "6", "latest_date": "2026-11-10"}
                ]
            }
        ),
    )
    page.goto(app_url + PAGE)
    page.locator("[data-prices-list] .co-row__head").click()
    detail = page.locator("[data-prices-list] .co-row__detail")
    expect(detail).to_contain_text("Priced in Nov 2026")
    expect(detail).not_to_contain_text("ought")


def _two_months(page, app_url, first, last, quantity="2"):
    def month(key, price):
        return {
            "month": key,
            "unit": "kg",
            "amount": "1",
            "priced_quantity": quantity,
            "average_unit_cost": price,
            "purchases": 1,
            "min_unit_price": price,
            "max_unit_price": price,
            "unconverted": 0,
        }

    history = {
        "name": "Mover",
        "unit": "kg",
        "from": "2025-12",
        "to": "2026-11",
        "months": [month("2026-10", first), month("2026-11", last)],
        "latest": {"unit_price": last, "date": "2026-11-10", "source": "purchase"},
        "lots": [],
        "too_large": False,
    }
    page.route("**/api/core/costing/materials/*/history**", lambda route: route.fulfill(json=history))
    page.route(
        "**/api/core/costing/materials",
        lambda route: route.fulfill(
            json={
                "materials": [{"name": "Mover", "unit": "kg", "latest_unit_price": last, "latest_date": "2026-11-10"}]
            }
        ),
    )
    page.goto(app_url + PAGE)
    page.locator("[data-prices-list] .co-row__head").click()
    return page.locator("[data-prices-list] .co-row__detail")


@pytest.mark.parametrize(
    ("first", "last", "says"),
    [
        ("10.000000", "10.040000", "Up 0.4% from Oct 2026 to Nov 2026"),
        ("0.000000", "5.000000", "Up from Oct 2026 to Nov 2026 ($0.00 → $5.00"),
        ("0.000000", "-2.000000", "Down from Oct 2026 to Nov 2026"),
        ("10.000000", "9.000000", "Down 10% from Oct 2026 to Nov 2026"),
        ("10.000000", "10.000000", "Steady at $10.00"),
    ],
)
def test_the_trend_sentence_follows_the_exact_prices(costs_page, first, last, says):
    page, app_url = costs_page
    expect(_two_months(page, app_url, first, last)).to_contain_text(says)


def test_the_smallest_quantity_is_not_shown_as_zero(costs_page):
    page, app_url = costs_page
    detail = _two_months(page, app_url, "1.000000", "2.000000", quantity="0.0001")
    detail.locator("summary").click()
    expect(detail.locator(".co-months")).to_contain_text("0.0001 kg")
