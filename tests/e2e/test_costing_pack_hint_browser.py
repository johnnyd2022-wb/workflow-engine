"""Live-cost polish: the Total paid hint gives a bulk price when the stock's name carries a pack size."""

from __future__ import annotations

from uuid import UUID

import pytest
from playwright.sync_api import expect

from app.core.db.models.user import UserRole
from tests.e2e.conftest import login_through_ui

pytestmark = pytest.mark.e2e


@pytest.fixture
def manager(fresh_user, page, db):
    from app.core.db.repositories.feature_subscription_repo import FeatureSubscriptionRepository

    user = fresh_user(UserRole.ADMIN)
    FeatureSubscriptionRepository(db).grant(UUID(user["org_id"]), "costing")
    db.commit()
    login_through_ui(page, user["email"], user["password"])
    return user


@pytest.mark.parametrize(
    ("amount", "quantity", "unit", "name", "says"),
    [
        ("828", "600", "bottles", "Glass bottle 700 mL", "= $1.38 per bottle · $1.97 per litre"),
        ("100", "4", "bags", "Juniper 25 kg bag", "= $25.00 per bag · $1.00 per kg"),
        ("12", "4", "units", "Cork stopper 500g", "= $3.00 per unit · $6.00 per kg"),
        ("90", "2", "kg", "Juniper berries", "= $45.00 per kg"),
        ("30", "10", "bottles", "Tonic", "= $3.00 per bottle"),
        ("50", "2", "L", "Spirit 96% 1L", "= $25.00 per L"),
    ],
)
def test_the_hint_reads_per_unit_and_per_bulk_when_the_name_has_a_size(
    manager, page, app_url, amount, quantity, unit, name, says
):
    page.goto(app_url + "/core/costing/costs")
    page.locator("[data-costs-root][aria-busy='false']").wait_for()
    got = page.evaluate(
        "([a, q, u, n]) => window.BizECost.packHint(Number(a), Number(q), u, n)", [amount, quantity, unit, name]
    )
    assert got == says


def test_the_manual_form_updates_as_the_name_changes(manager, page, app_url):
    page.goto(app_url + "/core/inventory/add/manual")
    paid = page.locator("#cost-total-paid")
    paid.wait_for()
    unit = page.locator("#add-inventory-unit")
    page.locator("#add-inventory-name").fill("Glass bottle")
    unit.select_option("units")  # the manual form counts bought bottles as units
    page.locator("#add-inventory-quantity").fill("600")
    paid.fill("828")
    hint = page.locator("#cost-total-paid-hint")
    expect(hint).to_have_text("= $1.38 per unit")
    page.locator("#add-inventory-name").fill("Glass bottle 700 mL")
    expect(hint).to_have_text("= $1.38 per unit · $1.97 per litre")
