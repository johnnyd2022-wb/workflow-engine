"""AC147: Costs page stock value, closed months and the bridge, at phone and desktop width."""

from __future__ import annotations

import pytest
from playwright.sync_api import expect

from tests.e2e.conftest import login_through_ui

pytestmark = pytest.mark.e2e

PAGE = "/core/costing/costs"

NOW = {
    "as_of": "2026-11-14T01:00:00+00:00",
    "currency": "NZD",
    "total": "290.0000",
    "complete": False,
    "unknown_lots": 1,
    "partial_lots": 0,
    "lot_count": 6,
    "categories": {
        "raw": {"value": "125.0000", "lots": 3},
        "in_production": {"value": "15.0000", "lots": 0},
        "wip": {"value": "30.0000", "lots": 1},
        "finished": {"value": "120.0000", "lots": 1},
    },
    "split": {"actual": "230.0000", "estimated": "60.0000", "partial": "0.0000"},
    "lines": [
        {"kind": "lot", "name": "Mystery with a very long name " * 3, "value": None, "status": "unknown"},
    ],
}


def _snap(id_, as_of, total):
    return {
        "id": id_,
        "kind": "month_end",
        "as_of_date": as_of,
        "taken_at": as_of + "T01:00:00+00:00",
        "automatic": True,
        "quantity_basis": "exact",
        "total": total,
        "complete": True,
        "unknown_lots": 0,
        "partial_lots": 0,
        "categories": {k: {"value": "10.0000"} for k in ("raw", "in_production", "wip", "finished")},
    }


NEW = _snap("22222222-2222-2222-2222-222222222222", "2026-10-31", "250.0000")
OLD = _snap("11111111-1111-1111-1111-111111111111", "2026-09-30", "200.0000")


def _mock(page, *, can_manage=True):
    state = {"taken": 0}

    def mocked(route):
        url = route.request.url
        method = route.request.method
        if url.endswith("/readiness"):
            route.fulfill(json={"products": []})
        elif url.endswith("/me"):
            route.fulfill(json={"enabled": True, "can_view": True, "can_manage": can_manage})
        elif url.endswith("/materials"):
            route.fulfill(json={"materials": []})
        elif url.endswith("/stock-value/snapshot") and method == "POST":
            state["taken"] += 1
            route.fulfill(status=201, json=NEW)
        elif url.endswith("/stock-value/snapshots"):
            route.fulfill(json={"snapshots": [NEW, OLD]})
        elif "/stock-value/snapshots/" in url:
            route.fulfill(
                json={
                    **NEW,
                    "changes_since_close": {"delta": "12.0000", "total_now": "262.0000", "total_then": "250.0000"},
                }
            )
        elif url.endswith("/stock-value"):
            route.fulfill(json=NOW)
        elif "/bridge" in url:
            route.fulfill(
                json={
                    "state": "ok",
                    "period": {"from": "2026-10-01", "to": "2026-10-31"},
                    "xero": {"state": "not_connected"},
                    "tie_out": None,
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
                    "changes_since_close": {"delta": "0.0000"},
                    "duty": {"tracked": False, "xero_total": None, "computed": None},
                    "overhead": {"xero_total": None},
                }
            )
        else:
            route.continue_()

    page.route("**/api/core/costing/**", mocked)
    return state


@pytest.fixture
def costs_page(fresh_user, page, app_url, db):
    from app.core.db.models.user import UserRole
    from app.core.db.repositories.feature_subscription_repo import FeatureSubscriptionRepository

    user = fresh_user(UserRole.ADMIN)
    FeatureSubscriptionRepository(db).grant(user["org_id"], "costing")
    db.commit()
    login_through_ui(page, user["email"], user["password"])
    return page, app_url


@pytest.mark.parametrize("size", [(375, 800), (1440, 900)], ids=["phone", "desktop"])
def test_stock_value_closed_months_and_bridge_render_without_sideways_scroll(costs_page, size):
    page, app_url = costs_page
    page.set_viewport_size({"width": size[0], "height": size[1]})
    state = _mock(page)
    page.goto(app_url + PAGE)
    now = page.locator("[data-stock-now]")
    expect(now).to_contain_text("At least $290.00")
    expect(now).to_contain_text("1 lot has no cost")  # the floor is explained, never a quiet $0
    expect(page.locator("[data-stock-list]")).to_contain_text("$250.00")

    page.locator("[data-stock-list] .co-snap__head").first.click()
    detail = page.locator("[data-stock-list] .co-snap__detail").first
    expect(detail).to_contain_text("Changes since close")
    expect(detail.get_by_role("link", name="Download CSV for your accountant")).to_have_attribute(
        "href", f"/api/core/costing/stock-value/snapshots/{NEW['id']}/export.csv"
    )
    detail.get_by_role("button", name="Compare with Xero").click()
    expect(detail).to_contain_text("Xero isn’t connected")
    expect(detail).to_contain_text("Cost that left stock")

    page.locator("[data-stock-snapshot]").click()
    expect(page.locator("[data-stock-snapshot]")).to_be_enabled()
    assert state["taken"] == 1
    overflow = page.evaluate("document.documentElement.scrollWidth - document.documentElement.clientWidth")
    assert overflow <= 0, f"page scrolls sideways by {overflow}px"
