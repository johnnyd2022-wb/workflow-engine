"""Purchases page in a real browser (live-cogs 8.1d, Codex review round 1).

Each test pins a behaviour a template-marker test can't see: one record per logical save (double
click, lost reply), exact four-decimal amounts and the blank "rest" row, out-of-order loads, an
action error that stays on screen, Xero text rendered as text, boosted re-entry, and the page for
an org with no Xero connection.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from playwright.sync_api import expect

from app.core.db.models.user import UserRole
from tests.e2e.conftest import login_through_ui

pytestmark = pytest.mark.e2e

PAGE = "/core/costing/purchases"


def _org_with_purchases(db, org_id, amounts, *, connect=True, payee="Botanical Supply Co"):
    from app.core.db.repositories.feature_subscription_repo import FeatureSubscriptionRepository
    from app.features.costing.models import CostingSettings, PurchaseLine
    from app.features.costing.purchase_sources import nz_today, sync_accounts, upsert_bank_transactions
    from app.features.crm.models.xero_tenant import XeroTenant
    from tests.test_costing_purchases import ACCOUNTS, line, txn

    FeatureSubscriptionRepository(db).grant(org_id, "costing")
    db.add(CostingSettings(org_id=org_id, start_date=nz_today()))
    tenant = f"e2e-{org_id}"
    if connect:
        db.add(XeroTenant(org_id=org_id, xero_tenant_id=tenant, xero_tenant_name="E2E", is_connected=True))
    db.flush()
    accounts = sync_accounts(db, org_id, ACCOUNTS)
    keys = []
    for amount in amounts:
        key = str(uuid4())
        keys.append(key)
        upsert_bank_transactions(
            db,
            org_id,
            [txn([line("310", amount, line_item_id=key, description="Juniper")], amounts="NoTax", payee=payee)],
            accounts=accounts,
            base_currency="NZD",
            start_date=None,
            xero_tenant_id=tenant,
        )
    db.commit()
    return [
        db.query(PurchaseLine).filter(PurchaseLine.org_id == org_id, PurchaseLine.line_key == k).one().id for k in keys
    ]


def _allocations(db, line_id):
    from app.features.costing.models import PurchaseAllocation

    db.expire_all()
    return db.query(PurchaseAllocation).filter(PurchaseAllocation.purchase_line_id == line_id).all()


@pytest.fixture
def manager(fresh_user, page, app_url):
    user = fresh_user(UserRole.ADMIN)
    login_through_ui(page, user["email"], user["password"])
    return UUID(user["org_id"])


def _open(page, app_url):
    page.goto(app_url + PAGE)
    page.locator("[data-purchases-root][aria-busy='false']").wait_for()


def _record_dialog(page):
    page.locator(".pu-card").first.get_by_role("button", name="Record stock").click()
    dialog = page.locator("[data-purchases-dialog]")
    expect(dialog).to_be_visible()
    return dialog


def test_double_click_save_records_once(manager, page, app_url, db):
    (line_id,) = _org_with_purchases(db, manager, ["40"])
    _open(page, app_url)
    dialog = _record_dialog(page)
    dialog.get_by_label("What").fill("Juniper berries")
    dialog.get_by_label("Quantity").fill("2")
    dialog.get_by_label("Unit").fill("kg")
    dialog.locator("[data-dialog-save]").dblclick()
    expect(dialog).to_be_hidden()
    assert len(_allocations(db, line_id)) == 1


def test_lost_reply_retry_replays_instead_of_recording_twice(manager, page, app_url, db):
    (line_id,) = _org_with_purchases(db, manager, ["40"])
    _open(page, app_url)
    dialog = _record_dialog(page)
    dialog.get_by_label("What").fill("Juniper berries")
    dialog.get_by_label("Quantity").fill("2")
    dialog.get_by_label("Unit").fill("kg")

    def lose_reply(route):
        route.fetch()  # the server records it...
        route.abort()  # ...and the reply never arrives

    page.route("**/record", lose_reply)
    dialog.locator("[data-dialog-save]").click()
    expect(dialog.locator("[data-dialog-error]")).to_be_visible()
    page.unroute("**/record")
    dialog.locator("[data-dialog-save]").click()
    expect(dialog).to_be_hidden()
    assert len(_allocations(db, line_id)) == 1


def test_four_decimal_amount_is_recorded_exactly(manager, page, app_url, db):
    (line_id,) = _org_with_purchases(db, manager, ["10.005"])
    _open(page, app_url)
    dialog = _record_dialog(page)
    expect(dialog.get_by_label("Amount")).to_have_value("10.005")
    dialog.get_by_label("What").fill("Orris root")
    dialog.get_by_label("Quantity").fill("1")
    dialog.get_by_label("Unit").fill("kg")
    dialog.locator("[data-dialog-save]").click()
    expect(dialog).to_be_hidden()
    (alloc,) = _allocations(db, line_id)
    assert Decimal(str(alloc.amount)) == Decimal("10.005")


def test_one_blank_amount_takes_the_exact_rest(manager, page, app_url, db):
    (line_id,) = _org_with_purchases(db, manager, ["10.005"])
    _open(page, app_url)
    dialog = _record_dialog(page)
    first = dialog.locator(".pu-row-edit").nth(0)
    first.get_by_label("What").fill("Orris root")
    first.get_by_label("Quantity").fill("1")
    first.get_by_label("Unit").fill("kg")
    first.get_by_label("Amount").fill("4")
    dialog.get_by_role("button", name="Add a row").click()
    second = dialog.locator(".pu-row-edit").nth(1)
    second.get_by_label("What").fill("Angelica")
    second.get_by_label("Quantity").fill("1")
    second.get_by_label("Unit").fill("kg")
    expect(dialog.locator("[data-dialog-sum]")).to_contain_text("blank row takes")
    dialog.locator("[data-dialog-save]").click()
    expect(dialog).to_be_hidden()
    amounts = sorted(Decimal(str(a.amount)) for a in _allocations(db, line_id))
    assert amounts == [Decimal("4"), Decimal("6.005")]


def test_a_slow_earlier_load_never_overwrites_the_tab_now_shown(manager, page, app_url, db):
    _org_with_purchases(db, manager, ["40"])
    page.add_init_script(
        """(() => {
          const real = window.fetch;
          window.fetch = (url, init) => String(url).includes('tab=to_record')
            ? new Promise((done) => setTimeout(() => done(real(url, init)), 1500))
            : real(url, init);
        })();"""
    )
    page.goto(app_url + PAGE)
    page.locator("[data-tab='recorded']").click()
    page.wait_for_timeout(2500)  # the delayed To record reply has now arrived
    expect(page.locator("[data-tab='recorded']")).to_have_attribute("aria-current", "page")
    expect(page.locator(".pu-card")).to_have_count(0)
    expect(page.locator("[data-purchases-state]")).to_have_text("Nothing here.")


def test_an_action_error_stays_on_screen(manager, page, app_url, db):
    _org_with_purchases(db, manager, ["40"])
    _open(page, app_url)
    page.route("**/skip", lambda route: route.fulfill(status=400, json={"error": "Nope, not today"}))
    page.locator(".pu-card").first.get_by_role("button", name="Skip").click()
    expect(page.locator("[data-purchases-error]")).to_have_text("Nope, not today")
    page.wait_for_timeout(500)
    expect(page.locator("[data-purchases-error]")).to_be_visible()
    expect(page.locator(".pu-card").first.get_by_role("button", name="Skip")).to_be_enabled()


def test_xero_text_is_shown_as_text(manager, page, app_url, db):
    _org_with_purchases(db, manager, ["40"], payee='<img src=x onerror="window.__pwned=1">')
    _open(page, app_url)
    expect(page.locator(".pu-payee").first).to_contain_text("<img")
    assert page.locator("[data-purchases-list] img").count() == 0
    assert page.evaluate("window.__pwned") is None


def test_boosted_navigation_away_and_back_rebinds(manager, page, app_url, db):
    _org_with_purchases(db, manager, ["40"])
    _open(page, app_url)
    page.locator("a[href='/core/inventory/view']").first.click()
    page.wait_for_url("**/core/inventory/view")
    page.go_back()
    page.locator("[data-purchases-root][aria-busy='false']").wait_for()
    expect(page.locator(".pu-card")).to_have_count(1)


def test_without_xero_the_page_explains_how_to_cost_stock(manager, page, app_url, db):
    _org_with_purchases(db, manager, [], connect=False)
    _open(page, app_url)
    expect(page.locator("[data-purchases-noxero]")).to_be_visible()
    expect(page.locator("[data-purchases-tabs]")).to_be_hidden()
    expect(page.locator("[data-purchases-noxero] a[href='/core/inventory/add']")).to_be_visible()


def test_bulk_skip_from_style_one_and_no_style_switch(manager, page, app_url, db):
    from app.features.costing.models import PurchaseLine

    first, second = _org_with_purchases(db, manager, ["40", "15"])
    _open(page, app_url)
    expect(page.locator("[data-purchases-style-pick], [data-style]")).to_have_count(0)
    page.locator(".pu-select").nth(0).check()
    page.locator(".pu-select").nth(1).check()
    expect(page.locator("[data-purchases-selected]")).to_have_text("2 selected")
    page.locator("[data-batch='skip']").click()
    expect(page.locator(".pu-card")).to_have_count(0)
    db.expire_all()
    assert {db.get(PurchaseLine, i).state for i in (first, second)} == {"skipped"}
