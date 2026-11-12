"""Live-cogs 8.1f-3b AC128: the batch card's duty line, run in a real browser (spec Q6)."""

from __future__ import annotations

from uuid import UUID

import pytest

from app.core.db.models.user import UserRole
from tests.e2e.conftest import login_through_ui

pytestmark = pytest.mark.e2e


def test_ac128_duty_line_says_not_tracked_not_worked_out_or_the_figures(fresh_user, page, app_url, db):
    from app.core.db.repositories.feature_subscription_repo import FeatureSubscriptionRepository

    user = fresh_user(UserRole.ADMIN)
    FeatureSubscriptionRepository(db).grant(UUID(user["org_id"]), "costing")
    db.commit()
    login_through_ui(page, user["email"], user["password"])
    page.goto(app_url + "/core/costing/costs")
    page.locator("[data-costs-root][aria-busy='false']").wait_for()
    line = "([d, u]) => window.BizECost.dutyLine(d, u)"
    assert page.evaluate(line, [{"tracked": False}, "bottles"]) == "Duty not tracked"
    assert (
        page.evaluate(line, [{"tracked": True, "per_unit": None, "missing": "No alcohol profile"}, "bottles"])
        == "Duty not worked out — No alcohol profile"
    )
    assert (
        page.evaluate(line, [{"tracked": True, "per_unit": "4.98", "landed_per_unit": "26.98"}, "bottles"])
        == "Duty if sold today $4.98 · landed $26.98 per bottle"
    )
    assert page.evaluate(line, [None, "bottles"]) is None
