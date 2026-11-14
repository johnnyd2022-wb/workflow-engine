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
        # review !710: thousands commas, multipacks, leading dots, ratios, unit words
        ("100", "1", "units", "Bottle 1,000 mL", "= $100.00 per unit · $100.00 per litre"),
        ("100", "1", "units", "Spirit IBC 1,000 L", "= $100.00 per unit · $0.10 per litre"),
        ("100", "1", "units", "Tonic 24 x 200ml", "= $100.00 per unit · $4.17 each of 24 · $20.83 per litre"),
        ("100", "1", "cases", "Case 6x700ml", "= $100.00 per case · $16.67 each of 6 · $23.81 per litre"),
        ("100", "1", "cases", "Gin 700ml x 6", "= $100.00 per case · $16.67 each of 6 · $23.81 per litre"),
        ("10", "1", "units", "Vodka .5L", "= $10.00 per unit · $20.00 per litre"),
        ("10", "1", "units", "Sugar syrup 650 g/L", "= $10.00 per unit"),
        ("10", "1", "units", "Oil 1,5 L", "= $10.00 per unit · $6.67 per litre"),
        ("100", "1", "kegs", "Beer 50 L", "= $100.00 per keg · $2.00 per litre"),
        ("12", "4", "each", "Label", "= $3.00 each"),
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


def test_the_barcode_form_hint_reads_the_name(manager, page, app_url):
    """Review !710: the barcode form passes the item's name too."""
    from uuid import uuid4

    page.goto(app_url + "/core/inventory/add/barcode")
    page.locator("#barcode-manual-input").fill(f"PH-{uuid4().hex[:10]}")
    page.locator("#barcode-continue-btn").click()
    page.locator("#barcode-inv-name").wait_for()
    paid = page.locator("#cost-total-paid")
    paid.wait_for()
    page.locator("#barcode-inv-name").fill("Glass bottle 700 mL")
    page.locator("#barcode-inv-unit").select_option("units")
    page.locator("#barcode-inv-quantity").fill("600")
    paid.fill("828")
    expect(page.locator("#cost-total-paid-hint")).to_have_text("= $1.38 per unit · $1.97 per litre")
