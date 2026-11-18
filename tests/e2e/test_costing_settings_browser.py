"""Live-cogs polish: the Costs page's "How costs are worked out" sheet, in a real browser."""

from __future__ import annotations

from uuid import UUID

import pytest
from playwright.sync_api import expect

from app.core.db.models.user import UserRole
from tests.e2e.conftest import login_through_ui

pytestmark = pytest.mark.e2e


def test_a_manager_switches_the_split_to_litres_and_back(fresh_user, page, app_url, db):
    from app.core.db.repositories.feature_subscription_repo import FeatureSubscriptionRepository
    from app.features.costing.service import get_settings

    user = fresh_user(UserRole.ADMIN)
    org_id = UUID(user["org_id"])
    FeatureSubscriptionRepository(db).grant(org_id, "costing")
    db.commit()
    login_through_ui(page, user["email"], user["password"])
    page.goto(app_url + "/core/costing/costs")
    page.locator("[data-costs-root][aria-busy='false']").wait_for()

    page.get_by_role("button", name="How costs are worked out").click()
    sheet = page.locator("[data-costs-settings]")
    expect(sheet).to_be_visible()
    expect(sheet.locator("[name=split_basis][value=quantity]")).to_be_checked()
    sheet.get_by_text("Litres", exact=True).click()
    sheet.locator("[name=use_last_known_price]").uncheck()
    with page.expect_navigation():  # saving reloads the page: every figure depends on these
        sheet.get_by_role("button", name="Save").click()
    page.locator("[data-costs-root][aria-busy='false']").wait_for()
    db.expire_all()
    assert get_settings(db, org_id) == {"use_last_known_price": False, "split_basis": "litres"}

    page.get_by_role("button", name="How costs are worked out").click()
    expect(sheet.locator("[name=split_basis][value=litres]")).to_be_checked()
    expect(sheet.locator("[name=use_last_known_price]")).not_to_be_checked()
    sheet.get_by_role("button", name="Cancel").click()
    expect(sheet).to_be_hidden()
