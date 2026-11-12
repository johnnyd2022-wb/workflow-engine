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


def test_without_stock_permission_the_switch_only_turns_automation_off(fresh_user, page, app_url, db):
    """Review r4/r5: a costs.manage user without inventory.adjust never sees an automation control
    that would fail: no switch on a new rule, untick-only on an automatic one, no 'Switch on' back."""
    from uuid import uuid4

    from app.core.db.models.org_role import OrgRole
    from app.core.db.models.user import User
    from app.core.db.repositories.feature_subscription_repo import FeatureSubscriptionRepository
    from app.features.costing import rules

    user = fresh_user(UserRole.MEMBER)
    org_id = UUID(user["org_id"])
    FeatureSubscriptionRepository(db).grant(org_id, "costing")
    role = OrgRole(
        id=uuid4(),
        org_id=org_id,
        name="Costs only",
        base_role="member",
        permissions=["costs.view", "costs.manage", "inventory.view", "production.view"],
    )
    db.add(role)
    db.flush()
    db.query(User).filter(User.id == UUID(user["user_id"])).update({"custom_role_id": role.id})
    row = {
        "name": "Juniper berries",
        "inventory_type": "raw_material",
        "unit": "kg",
        "share": "rest",
        "quantity_mode": "from_price",
        "unit_price": "48.90",
    }
    rules.create(
        db, org_id, {"payee_pattern": "Moore Wilson", "treatment": "stock", "auto_record": True, "template": [row]}
    )
    db.commit()

    try:
        login_through_ui(page, user["email"], user["password"])
        page.goto(app_url + "/core/costing/rules")
        dialog = page.locator("[data-rules-dialog]")
        page.get_by_role("button", name="Add a rule").first.click()
        expect(dialog.locator(".ru-auto")).to_be_hidden()
        dialog.get_by_role("button", name="Cancel").click()

        page.locator(".ru-rule").get_by_role("button", name="Edit").click()
        expect(dialog.locator(".ru-auto")).to_be_visible()
        dialog.locator("[data-rules-auto]").uncheck()
        dialog.get_by_role("button", name="Save rule").click()
        expect(page.locator(".ru-rule__auto")).to_have_count(0)
        (saved,) = _rules(db, org_id)
        assert saved.auto_record is False
    finally:  # the fixture's purge can't drop a role a user still points at
        db.rollback()
        db.query(User).filter(User.id == UUID(user["user_id"])).update({"custom_role_id": None})
        db.commit()
