"""Pack size on Add Inventory: filled from the name, editable, sent with the lot, read by the cost hint."""

from __future__ import annotations

import re
from uuid import UUID

import pytest
from playwright.sync_api import expect

from app.core.db.models.user import UserRole
from tests.costing_helpers import lot as make_lot
from tests.costing_helpers import price
from tests.e2e.conftest import login_through_ui
from tests.e2e.test_costing_purchases_browser import _org_with_purchases

pytestmark = pytest.mark.e2e


@pytest.fixture
def manager(fresh_user, page, db):
    from app.core.db.repositories.feature_subscription_repo import FeatureSubscriptionRepository

    user = fresh_user(UserRole.ADMIN)
    FeatureSubscriptionRepository(db).grant(UUID(user["org_id"]), "costing")
    db.commit()
    login_through_ui(page, user["email"], user["password"])
    return user


def _lot(db, org_id, name):
    from app.core.db.models.inventory_item import InventoryItem

    db.expire_all()
    return db.query(InventoryItem).filter(InventoryItem.org_id == UUID(org_id), InventoryItem.name == name).one()


def test_manual_form_fills_the_pack_from_the_name_and_saves_it(manager, page, app_url, db):
    page.goto(app_url + "/core/inventory/add/manual")
    pack = page.locator("#inventory-pack")
    pack.wait_for(state="attached")
    page.locator("#add-inventory-unit").select_option("kg")
    expect(pack).to_be_hidden()  # measured stock has no pack
    page.locator("#add-inventory-unit").select_option("units")
    page.locator("#add-inventory-name").fill("Tonic 24 x 200ml")
    expect(pack).to_have_value("24 × 200 mL")
    expect(page.locator("#inventory-pack-hint")).to_have_text(
        "One unit = 24 × 200 mL. Workflows can take single ones or mL."
    )
    page.locator("#add-inventory-quantity").fill("2")
    page.locator("#cost-total-paid").fill("96")
    expect(page.locator("#cost-total-paid-hint")).to_have_text(
        "= $48.00 per unit · $2.00 each of 24 · $10.00 per litre"
    )
    # an edit wins over the name, and the hint follows it
    pack.fill("6 x 700 mL")
    expect(page.locator("#cost-total-paid-hint")).to_have_text("= $48.00 per unit · $8.00 each of 6 · $11.43 per litre")
    page.locator("#add-inventory-name").fill("Tonic mixed case")
    expect(pack).to_have_value("6 x 700 mL")
    page.locator("#add-inv-manual-submit-btn").click()
    page.wait_for_url(lambda url: "/inventory/add" not in url, timeout=10_000)  # saved: the app moves on
    lot = _lot(db, manager["org_id"], "Tonic mixed case")
    assert lot.extra_data["pack"] == {"count": 6, "size": "700", "size_unit": "ml"}


def test_an_unreadable_pack_stops_the_save(manager, page, app_url, db):
    from app.core.db.models.inventory_item import InventoryItem

    page.goto(app_url + "/core/inventory/add/manual")
    page.locator("#add-inventory-unit").select_option("units")
    page.locator("#add-inventory-name").fill("Limes")
    page.locator("#add-inventory-quantity").fill("3")
    page.locator("#inventory-pack").fill("a few")
    expect(page.locator("#inventory-pack-hint")).to_have_text("Write it like 24 × 200 mL, 700 mL, 25 kg or 500 pcs")
    page.locator("#add-inv-manual-submit-btn").click()
    expect(page.locator("#inventory-pack")).to_be_focused()
    db.expire_all()
    assert db.query(InventoryItem).filter(InventoryItem.org_id == UUID(manager["org_id"])).count() == 0


def test_a_count_with_no_size_is_a_pack_and_prices_each_item(manager, page, app_url, db):
    """A box of 500 labels: typed as "500 pcs", priced $0.10 a label, stored with no size."""
    page.goto(app_url + "/core/inventory/add/manual")
    page.locator("#add-inventory-unit").select_option("units")
    page.locator("#add-inventory-name").fill("Front labels")
    page.locator("#add-inventory-quantity").fill("2")
    page.locator("#inventory-pack").fill("500 pcs")
    expect(page.locator("#inventory-pack-hint")).to_have_text("One unit = 500. Workflows can take single ones.")
    page.locator("#cost-total-paid").fill("100")
    expect(page.locator("#cost-total-paid-hint")).to_have_text("= $50.00 per unit · $0.10 each of 500")
    page.locator("#add-inv-manual-submit-btn").click()
    page.wait_for_url(lambda url: "/inventory/add" not in url, timeout=10_000)
    assert _lot(db, manager["org_id"], "Front labels").extra_data["pack"] == {"count": 500}


def test_the_lot_panel_breaks_a_cases_price_into_bottles_and_litres(manager, page, app_url, db):
    org_id = UUID(manager["org_id"])
    tonic = make_lot(
        db, org_id, "Tonic cases", 2, "cases", extra_data={"pack": {"count": 24, "size": "200", "size_unit": "ml"}}
    )
    price(db, org_id, tonic.id, 96, 2)
    db.commit()
    page.goto(app_url + "/core/inventory/view")
    page.get_by_role("row", name=re.compile("Tonic cases")).get_by_role("button", name="Tonic cases").click()
    panel = page.get_by_role("dialog", name="Tonic cases")
    facts = panel.locator(".cost-facts")
    expect(facts).to_contain_text("Pack")
    expect(facts.locator(".cost-facts__row", has_text="Pack")).to_contain_text("24 × 200 mL")
    expect(facts.locator(".cost-facts__row", has_text="Each")).to_contain_text("$2.00 (1 of 24)")
    expect(facts.locator(".cost-facts__row", has_text="Per litre")).to_contain_text("$10.00")


def test_the_record_dialog_takes_a_pack_and_stores_it_on_the_lot(manager, page, app_url, db):
    org_id = UUID(manager["org_id"])
    _org_with_purchases(db, org_id, ["96"])
    page.goto(app_url + "/core/costing/purchases")
    page.locator("[data-purchases-root][aria-busy='false']").wait_for()
    page.locator(".pu-card").first.get_by_role("button", name="Record stock").click()
    dialog = page.locator("[data-purchases-dialog]")
    expect(dialog).to_be_visible()
    dialog.get_by_label("What").fill("Tonic 24 x 200mL")
    dialog.get_by_label("Quantity").fill("2")
    dialog.get_by_label("Unit").fill("cases")
    dialog.get_by_label("Pack size").fill("a few")
    dialog.locator("[data-dialog-save]").click()
    expect(dialog.locator("[data-dialog-error]")).to_contain_text("Pack size must look like")
    dialog.get_by_label("Pack size").fill("24 x 200 mL")
    dialog.locator("[data-dialog-save]").click()
    expect(dialog).to_be_hidden()
    assert _lot(db, manager["org_id"], "Tonic 24 x 200mL").extra_data["pack"] == {
        "count": 24,
        "size": "200",
        "size_unit": "ml",
    }


def test_the_pack_field_does_not_scroll_a_phone_sideways(manager, page, app_url, db):
    """375px: the manual form with the pack field open, and the record dialog as a bottom sheet."""
    page.set_viewport_size({"width": 375, "height": 844})
    page.goto(app_url + "/core/inventory/add/manual")
    page.locator("#add-inventory-unit").select_option("units")
    page.locator("#add-inventory-name").fill("Tonic 24 x 200ml with a rather long name to push the layout about")
    page.locator("#add-inventory-quantity").fill("2")
    page.locator("#cost-total-paid").fill("96")
    expect(page.locator("#inventory-pack")).to_be_visible()
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth"), "form scrolls sideways"

    _org_with_purchases(db, UUID(manager["org_id"]), ["96"])
    page.goto(app_url + "/core/costing/purchases")
    page.locator("[data-purchases-root][aria-busy='false']").wait_for()
    page.locator(".pu-card").first.get_by_role("button", name="Record stock").click()
    dialog = page.locator("[data-purchases-dialog]")
    expect(dialog.get_by_label("Pack size")).to_be_visible()
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth"), "dialog scrolls sideways"
    # it slides up over 0.22s; wait for it to settle before judging where it rests
    page.wait_for_function(
        "() => { const r = document.querySelector('[data-purchases-dialog]').getBoundingClientRect();"
        " return Math.abs(r.bottom - window.innerHeight) <= 1; }",
        timeout=3000,
    )
