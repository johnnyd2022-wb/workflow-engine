"""Live-cogs 8.1f-3c: the rules editor's "Record these automatically" switch, in a real browser."""

from __future__ import annotations

from uuid import UUID

import pytest
from playwright.sync_api import expect

from app.core.db.models.user import UserRole
from tests.e2e.conftest import login_through_ui

pytestmark = pytest.mark.e2e


def _rules(db, org_id):
    from app.features.costing.models import PurchaseRule

    db.expire_all()
    return db.query(PurchaseRule).filter(PurchaseRule.org_id == org_id).all()


def test_a_rule_saved_with_the_switch_on_records_automatically(fresh_user, page, app_url, db):
    from app.core.db.repositories.feature_subscription_repo import FeatureSubscriptionRepository

    user = fresh_user(UserRole.ADMIN)
    org_id = UUID(user["org_id"])
    FeatureSubscriptionRepository(db).grant(org_id, "costing")
    db.commit()
    login_through_ui(page, user["email"], user["password"])
    page.goto(app_url + "/core/costing/rules")
    page.get_by_role("button", name="Add a rule").first.click()
    dialog = page.locator("[data-rules-dialog]")
    expect(dialog).to_be_visible()
    dialog.locator("[name=payee_pattern]").fill("Moore Wilson")
    dialog.get_by_role("button", name="Add an item").click()
    row = dialog.locator(".ru-row").first
    row.locator("[name=name]").fill("Juniper berries")
    row.locator("[name=unit]").select_option("kg")
    row.locator("[name=share_kind]").select_option("rest")
    row.locator("[name=quantity_mode]").select_option("from_price")
    row.locator("[name=unit_price]").fill("48.90")
    dialog.locator("[data-rules-auto]").check()
    dialog.get_by_role("button", name="Save rule").click()
    expect(page.locator(".ru-rule__auto")).to_have_text("Records new purchases automatically")
    (rule,) = _rules(db, org_id)
    assert rule.auto_record is True

    # Editing keeps it; unticking turns it off.
    page.locator(".ru-rule").get_by_role("button", name="Edit").click()
    expect(dialog.locator("[data-rules-auto]")).to_be_checked()
    dialog.locator("[data-rules-auto]").uncheck()
    dialog.get_by_role("button", name="Save rule").click()
    expect(page.locator(".ru-rule__auto")).to_have_count(0)
    (rule,) = _rules(db, org_id)
    assert rule.auto_record is False
