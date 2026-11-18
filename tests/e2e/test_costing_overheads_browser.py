"""Live-cogs 8.1h (AC-OV18): overheads into cost, opt-in — in a real browser.

The Costs page's "How costs are worked out" sheet turns it on and the Overheads section holds the
rates; the Purchases card gains "It's freight"; the batch card and lot panel show materials and
overheads apart. Every sheet is a bottom sheet and nothing scrolls sideways at phone width.
"""

from __future__ import annotations

from uuid import UUID

import pytest
from playwright.sync_api import expect

from app.core.db.models.user import UserRole
from tests.e2e.conftest import login_through_ui
from tests.e2e.test_costing_purchases_browser import _org_with_purchases

pytestmark = pytest.mark.e2e

PHONE = {"width": 375, "height": 844}


@pytest.fixture
def manager(fresh_user, page, app_url, db):
    from app.core.db.repositories.feature_subscription_repo import FeatureSubscriptionRepository

    user = fresh_user(UserRole.ADMIN)
    org_id = UUID(user["org_id"])
    FeatureSubscriptionRepository(db).grant(org_id, "costing")
    db.commit()
    login_through_ui(page, user["email"], user["password"])
    return org_id


def _no_sideways_scroll(page):
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth + 1"), "the page scrolls sideways"


def _open_costs(page, app_url):
    page.goto(app_url + "/core/costing/costs")
    page.locator("[data-costs-root][aria-busy='false']").wait_for()


def _switch_on(db, org_id):
    from app.features.costing import service

    service.set_settings(db, org_id, include_overheads=True)
    db.commit()


def test_a_manager_turns_overheads_on_and_manages_rates_at_phone_width(manager, page, app_url, db):
    from app.features.costing import service
    from app.features.costing.models import OverheadRate

    _open_costs(page, app_url)
    expect(page.locator("[data-overheads]")).to_be_hidden()  # off: the page is what it always was

    page.get_by_role("button", name="How costs are worked out").click()
    sheet = page.locator("[data-costs-settings]")
    expect(sheet.locator("[name=include_overheads]")).not_to_be_checked()
    sheet.locator("[name=include_overheads]").check()
    with page.expect_navigation():
        sheet.get_by_role("button", name="Save").click()
    page.locator("[data-costs-root][aria-busy='false']").wait_for()
    db.expire_all()
    assert service.get_settings(db, manager).get("include_overheads") is True

    section = page.locator("[data-overheads]")
    expect(section).to_be_visible()
    expect(section.locator("[data-overheads-empty]")).to_be_visible()

    page.set_viewport_size(PHONE)
    section.get_by_role("button", name="Add a rate").click()
    rate_sheet = page.locator("[data-overheads-sheet]")
    expect(rate_sheet).to_be_visible()
    box = rate_sheet.bounding_box()
    assert box["y"] + box["height"] >= PHONE["height"] - 1, "the sheet rises from the bottom, never centred"
    rate_sheet.locator("[name=name]").fill("Rent")
    rate_sheet.locator("[name=amount]").fill("0.50")
    expect(rate_sheet.locator("[data-overheads-amount-hint]")).to_contain_text("A 200 L batch adds $100.00")
    rate_sheet.locator("[name=effective_from]").fill("2026-10-01")
    rate_sheet.get_by_role("button", name="Save").click()
    expect(rate_sheet).to_be_hidden()
    row = section.locator(".co-rate", has_text="Rent")
    expect(row).to_contain_text("$0.50 per litre")
    expect(row).to_contain_text("1 Oct 2026")
    _no_sideways_scroll(page)
    db.expire_all()
    stored = db.query(OverheadRate).filter(OverheadRate.org_id == manager).one()
    assert (stored.name, stored.basis, str(stored.amount)) == ("Rent", "per_litre", "0.500000")

    # A duplicate is refused on the field, not lost.
    section.get_by_role("button", name="Add a rate").click()
    rate_sheet.locator("[name=name]").fill("rent")
    rate_sheet.locator("[name=amount]").fill("9")
    rate_sheet.locator("[name=effective_from]").fill("2026-10-01")
    rate_sheet.get_by_role("button", name="Save").click()
    expect(rate_sheet.locator("[data-overheads-form-error]")).to_contain_text("already a rate")
    rate_sheet.get_by_role("button", name="Cancel").click()

    row.get_by_role("button", name="Edit").click()
    rate_sheet.locator("[name=amount]").fill("0.60")
    rate_sheet.get_by_text("Per batch", exact=True).click()
    rate_sheet.get_by_role("button", name="Save").click()
    expect(rate_sheet).to_be_hidden()
    expect(section.locator(".co-rate", has_text="Rent")).to_contain_text("$0.60 per batch")

    section.get_by_role("button", name="Remove").click()
    section.get_by_role("button", name="Remove", exact=True).click()
    expect(section.locator(".co-rate")).to_have_count(0)
    db.expire_all()
    assert db.query(OverheadRate).filter(OverheadRate.org_id == manager).count() == 0
    _no_sideways_scroll(page)


def test_a_card_can_be_marked_as_freight_only_when_overheads_are_on(manager, page, app_url, db):
    from app.features.costing.models import PurchaseLine

    (line_id,) = _org_with_purchases(db, manager, ["40"])
    page.goto(app_url + "/core/costing/purchases")
    page.locator("[data-purchases-root][aria-busy='false']").wait_for()
    card = page.locator(".pu-card").first
    expect(card.get_by_role("button", name="Not stock")).to_be_visible()
    expect(card.get_by_role("button", name="It’s freight")).to_have_count(0)  # off: nothing new on the card

    _switch_on(db, manager)
    page.reload()
    page.locator("[data-purchases-root][aria-busy='false']").wait_for()
    page.set_viewport_size(PHONE)
    card = page.locator(".pu-card").first
    _no_sideways_scroll(page)
    card.get_by_role("button", name="It’s freight").click()
    expect(page.locator(".pu-card")).to_have_count(0)  # it left To record
    db.expire_all()
    line = db.get(PurchaseLine, line_id)
    assert line.freight is True and line.state == "not_stock"

    page.locator("[data-tab=not_stock]").click()
    expect(page.locator(".pu-card").first.locator(".pu-badge", has_text="Freight")).to_be_visible()
    page.locator(".pu-card").first.get_by_role("button", name="Undo").click()
    expect(page.locator(".pu-card")).to_have_count(0)
    db.expire_all()
    assert db.get(PurchaseLine, line_id).freight is False


def test_batch_card_and_lot_panel_show_materials_and_overheads_apart(manager, page, app_url, db):
    _open_costs(page, app_url)
    page.set_viewport_size(PHONE)
    page.route(
        "**/api/core/costing/executions/e2e-overheads/cost",
        lambda route: route.fulfill(
            json={
                "status": "actual",
                "known_input_cost": "1000.0000",
                "cost_so_far": "0.0000",
                "cost_so_far_status": "actual",
                "inputs": [{"name": "Neutral spirit", "known_amount": "1000.0000"}],
                "outputs": [
                    {
                        "name": "Wildflower Gin",
                        "unit": "L",
                        "unit_cost": "5.700000",
                        "known_amount": "1140.0000",
                        "materials_unit_cost": "5.000000",
                        "overhead_unit_cost": "0.700000",
                        "overhead_amount": "140.0000",
                    }
                ],
                "overheads": {
                    "amount": "140.0000",
                    "note": None,
                    "lines": [
                        {
                            "name": "Rent",
                            "basis": "per_litre",
                            "rate": "0.50",
                            "quantity": "200.0000",
                            "amount": "100.0000",
                        },
                        {"name": "Labour", "basis": "per_batch", "rate": "40.00", "quantity": "1", "amount": "40.0000"},
                    ],
                },
            }
        ),
    )
    page.route(
        "**/api/core/costing/executions/e2e-running/cost",
        lambda route: route.fulfill(
            json={
                "status": "actual",
                "known_input_cost": "100.0000",
                "cost_so_far": "100.0000",
                "cost_so_far_status": "actual",
                "inputs": [{"name": "Neutral spirit", "known_amount": "100.0000"}],
                "outputs": [],
                "overheads": {"amount": None, "lines": [], "note": "in_progress"},
            }
        ),
    )
    page.route(
        "**/api/core/costing/executions/e2e-unknown/cost",
        lambda route: route.fulfill(
            json={
                "status": "partial",
                "known_input_cost": "90.0000",
                "cost_so_far": "0.0000",
                "cost_so_far_status": "actual",
                "missing": [],
                "warnings": ["overhead_litres_unknown"],
                "inputs": [{"name": "Neutral spirit", "known_amount": "90.0000"}],
                "outputs": [{"name": "Gin", "unit": "bottles", "unit_cost": None, "known_unit_cost": "13.000000"}],
                "overheads": {
                    "amount": "40.0000",
                    "note": "litres_unknown",
                    "lines": [
                        {"name": "Labour", "basis": "per_batch", "rate": "40.00", "quantity": "1", "amount": "40.0000"}
                    ],
                },
            }
        ),
    )
    page.route(
        "**/api/core/costing/lots/e2e-lot/cost",
        lambda route: route.fulfill(
            json={
                "inventory_item_id": "e2e-lot",
                "name": "Juniper berries",
                "unit": "kg",
                "unit_cost": "90.000000",
                "known_unit_cost": "90.000000",
                "status": "actual",
                "source": "purchase",
                "priced_quantity": "2.0000",
                "unpriced_quantity": "0.0000",
                "missing": [],
                "warnings": [],
                "entries": [],
                "editable": False,
                "materials_unit_cost": "75.000000",
                "overhead_unit_cost": "15.000000",
            }
        ),
    )
    page.evaluate(
        """() => {
          for (const id of ['e2e-overheads', 'e2e-running', 'e2e-unknown']) {
            const mount = document.createElement('div');
            mount.setAttribute('data-card-test', id);
            document.body.appendChild(mount);
            window.BizECost.batchCard(id, mount);
          }
          const lotMount = document.createElement('div');
          lotMount.setAttribute('data-lot-test', '');
          document.body.appendChild(lotMount);
          window.BizECost.lotPanel('e2e-lot', lotMount);
        }"""
    )
    done = page.locator("[data-card-test=e2e-overheads] .cost-card")
    expect(done).to_contain_text("Materials")
    expect(done.locator(".cost-card__figures")).to_contain_text("$140.00")
    expect(done).to_contain_text("$5.00 materials + $0.70 overheads")
    expect(done).to_contain_text("Rent — 200 L × $0.50 per litre")
    expect(done).to_contain_text("Labour — $40.00 per batch")
    expect(page.locator("[data-card-test=e2e-running] .cost-card")).to_contain_text(
        "Overheads are added when the batch is complete."
    )
    unknown = page.locator("[data-card-test=e2e-unknown] .cost-card")
    expect(unknown).to_contain_text("Overheads per litre not worked out")
    expect(unknown).to_contain_text("bottle size")
    expect(page.locator("[data-lot-test] .cost-panel")).to_contain_text("$75.00 materials · $15.00 overheads per kg")
    _no_sideways_scroll(page)
