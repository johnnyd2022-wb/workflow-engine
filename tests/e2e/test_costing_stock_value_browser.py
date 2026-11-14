"""Costs page stock value, snapshots and the Xero bridge in a browser (live-cogs 8.1g, AC147)."""

from __future__ import annotations

import pytest
from playwright.sync_api import expect

from tests.e2e.conftest import login_through_ui

pytestmark = pytest.mark.e2e

PAGE = "/core/costing/costs"
CATEGORIES = {
    k: {"value": v, "lots": 1}
    for k, v in (("raw", "125.0000"), ("in_production", "15.0000"), ("wip", "30.0000"), ("finished", "120.0000"))
}
SPLIT = {"actual": "230.0000", "estimated": "60.0000", "partial": "0.0000"}
HEADER = {
    "kind": "month_end",
    "as_of_date": "2026-10-31",
    "cutoff_at": "2026-11-01T00:00:00+13:00",
    "taken_at": "2026-11-02T01:00:00+00:00",
    "trigger": "costing_read",
    "automatic": True,
    "quantity_basis": "exact",
    "previous_id": None,
    "total": "290.0000",
    "complete": False,
    "unknown_lots": 1,
    "partial_lots": 0,
    "lot_count": 6,
    "categories": {k: {"value": v["value"]} for k, v in CATEGORIES.items()},
    "split": SPLIT,
}


@pytest.fixture
def costs_page(fresh_user, page, app_url, db):
    from app.core.db.models.user import UserRole
    from app.core.db.repositories.feature_subscription_repo import FeatureSubscriptionRepository

    user = fresh_user(UserRole.ADMIN)
    FeatureSubscriptionRepository(db).grant(user["org_id"], "costing")
    db.commit()
    login_through_ui(page, user["email"], user["password"])
    return page, app_url


def _mock(page, *, can_manage=True):
    snapshots = [{**HEADER, "id": "snap-2"}, {**HEADER, "id": "snap-1", "as_of_date": "2026-09-30"}]

    def mocked(route):
        url = route.request.url.split("?")[0]
        if url.endswith("/me"):
            route.fulfill(json={"enabled": True, "can_view": True, "can_manage": can_manage})
        elif url.endswith("/readiness") or url.endswith("/materials"):
            route.fulfill(json={"products": [], "materials": []})
        elif url.endswith("/stock-value"):
            route.fulfill(
                json={
                    "total": "290.0000",
                    "complete": False,
                    "unknown_lots": 1,
                    "partial_lots": 0,
                    "lot_count": 6,
                    "categories": CATEGORIES,
                    "split": SPLIT,
                    "lines": [],
                }
            )
        elif url.endswith("/stock-value/snapshots"):
            route.fulfill(json={"snapshots": snapshots})
        elif "/stock-value/snapshots/" in url:
            route.fulfill(json={**HEADER, "id": "snap-2", "lines": [], "changes_since_close": {"delta": "0.0000"}})
        elif url.endswith("/bridge"):
            route.fulfill(
                json={
                    "state": "ok",
                    "period": {"from": "2026-10-01", "to": "2026-10-31"},
                    "roll_forward": {
                        "opening": "50.0000",
                        "purchases": "80.0000",
                        "closing": "109.0000",
                        "cost_left": "21.0000",
                        "components": {
                            "cogs": "12.0000",
                            "wastage": "3.0000",
                            "samples": "3.0000",
                            "variance": "3.0000",
                            "production_loss": "0.0000",
                            "estimate_changes": "0.0000",
                            "other": "0.0000",
                        },
                        "rounding": "0.0000",
                        "balanced": True,
                    },
                    "xero": {"state": "not_connected"},
                    "tie_out": None,
                    "duty": {"tracked": False, "xero_total": None, "computed": None},
                    "overhead": {"xero_total": None},
                }
            )
        else:
            route.continue_()

    page.route("**/api/core/costing/**", mocked)


def test_stock_value_shows_a_floor_snapshots_and_the_bridge_without_sideways_scroll(costs_page):
    page, app_url = costs_page
    page.set_viewport_size({"width": 375, "height": 800})
    _mock(page)
    page.goto(app_url + PAGE)
    section = page.locator("[data-stock]")
    expect(section).to_be_visible()
    # Uncosted stock makes the total a floor, never a precise figure with a $0 for the unknown.
    expect(section.locator(".co-stock__amount")).to_have_text("At least $290.00")
    expect(section).to_contain_text("1 lot has no cost yet")
    expect(section.get_by_role("button", name="Take a snapshot")).to_be_visible()
    expect(section.locator("[data-stock-list] > li")).to_have_count(2)

    section.locator("[data-stock-list] > li").first.get_by_role("button").first.click()
    expect(section.get_by_role("link", name="Download CSV for your accountant")).to_be_visible()
    section.get_by_role("button", name="Compare with Xero").first.click()
    expect(section).to_contain_text("Cost that left stock")
    expect(section).to_contain_text("$21.00")
    expect(section).to_contain_text("Xero isn’t connected")
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
