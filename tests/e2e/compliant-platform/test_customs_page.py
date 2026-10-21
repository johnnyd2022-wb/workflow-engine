"""Customs page: the excise entry for each period, in Trade Single Window order."""

from __future__ import annotations

import re
import uuid
from datetime import date, timedelta
from decimal import Decimal

import pytest
from playwright.sync_api import expect

from tests.e2e.conftest import assert_clean_page, attach_probe, login_through_ui

pytestmark = pytest.mark.e2e

PAGE = "/compliant/nz-alcohol/customs"
GIN = "E2E Wildflower Gin"


def _months_back(n: int) -> date:
    today = date.today()
    serial = today.year * 12 + today.month - 1 - n
    return date(serial // 12, serial % 12 + 1, 1)


@pytest.fixture()
def excise_org(fresh_user):
    """An NZ Alcohol org with reminders from two months back and gin sold in that month."""
    from app.core.db import db_session
    from app.core.db.models.inventory_item import InventoryType
    from app.core.db.models.user import UserRole
    from app.core.db.repositories.feature_subscription_repo import FeatureSubscriptionRepository
    from app.core.db.repositories.inventory_repo import InventoryRepository
    from app.features.compliant.models import ComplianceProfile
    from app.features.compliant.models.alcohol_product_profile import AlcoholProductProfile
    from app.features.crm.models.sales_fifo_allocation import SalesFifoAllocation
    from app.features.crm.models.xero_invoice import XeroInvoice

    user = fresh_user(UserRole.ADMIN)
    org_id = uuid.UUID(user["org_id"])
    db = db_session()
    FeatureSubscriptionRepository(db).grant(org_id, "compliant")
    db.add(
        ComplianceProfile(
            org_id=org_id,
            enabled=True,
            settings={
                "alcohol_product_types": ["spirits"],
                "excise_frequency": "monthly",
                "excise_tracking_from": _months_back(2).isoformat(),
            },
        )
    )
    db.add(
        AlcoholProductProfile(
            org_id=org_id,
            inventory_name=GIN,
            product_type="spirits",
            pack_volume_ml=Decimal("700"),
            excise_category="gin",
        )
    )
    lot = InventoryRepository(db).create_inventory_item(
        org_id=org_id,
        name=GIN,
        quantity="100",
        unit="bottles",
        inventory_type=InventoryType.FINAL_PRODUCT.value,
        supplier_batch_number="VAT44",
        extra_data={"abv_percent": "44"},
    )
    sold_on = _months_back(2) + timedelta(days=9)
    invoice = XeroInvoice(
        org_id=org_id,
        xero_invoice_id=f"inv-{uuid.uuid4()}",
        xero_tenant_id="e2e",
        invoice_type="ACCREC",
        status="AUTHORISED",
        invoice_number="INV-E2E-1",
        date=sold_on,
    )
    db.add(invoice)
    db.flush()
    db.add(
        SalesFifoAllocation(
            org_id=org_id,
            xero_invoice_id=invoice.xero_invoice_id,
            xero_line_key="l1",
            inventory_item_id=lot.id,
            product_name=GIN,
            quantity=Decimal("50"),
            unit="bottles",
        )
    )
    db.commit()
    return user


def _open(browser, app_url, user, viewport=None, query="", path=PAGE, ready="[data-excise-draft] .customs-entry-head"):
    context = browser.new_context(
        base_url=app_url, ignore_https_errors=True, viewport=viewport or {"width": 1440, "height": 900}
    )
    page = context.new_page()
    attach_probe(page)
    login_through_ui(page, user["email"], user["password"])
    page.goto(path + query)
    page.locator(ready).first.wait_for()
    return page


def test_lands_on_the_oldest_unlodged_period_with_the_customs_entry(browser, app_url, excise_org):
    page = _open(browser, app_url, excise_org)
    label = _months_back(2).strftime("%B %Y")
    expect(page.locator(".customs-entry-head h3")).to_have_text(label)
    expect(page.locator(".customs-entry-head .customs-status")).to_contain_text("Overdue")
    # 50 x 0.7 L = 35 L; x 44% = 15.4 LAL; levy 35 L x the cents rate; GST on the levy only.
    row = page.locator(".customs-entry-table tbody tr").first
    expect(row).to_contain_text("99.45.35A")
    expect(row.locator("td[data-label='Units sold']")).to_have_text("50 bottles")
    expect(row).to_contain_text("35.000")
    expect(row).to_contain_text("15.400")
    expect(page.locator(".customs-tile--total .customs-tile__value")).to_have_text(re.compile(r"^\$1,1\d\d\.\d\d$"))
    expect(page.locator("[data-tsw-link]")).to_have_attribute(
        "href", "https://www.tsw.govt.nz/external/application/login/app.html"
    )
    # Records for Customs sit folded at the bottom; setup lives on its own pages.
    expect(page.locator("[data-customs-records]")).not_to_have_attribute("open", "")
    expect(page.locator("[data-excise-products]")).to_have_count(0)
    assert_clean_page(page)
    page.context.close()


def test_the_month_picker_shows_three_months_then_earlier(browser, app_url, excise_org):
    page = _open(browser, app_url, excise_org)
    boxes = page.locator("[data-excise-periods] .excise-period:not(.excise-period--more)")
    expect(boxes).to_have_count(3)
    expect(boxes.first).to_contain_text(date.today().strftime("%b %Y"))
    earlier = page.locator("[data-periods-earlier]")
    expect(earlier).to_have_attribute("aria-expanded", "false")
    earlier.click()
    expect(earlier).to_have_attribute("aria-expanded", "true")
    # Every older month here is from before reminders began: they stay folded until asked for.
    untracked = page.locator(".excise-period--untracked-toggle")
    expect(untracked).to_contain_text("9 earlier months")
    untracked.click()
    expect(page.locator("[data-excise-periods] .excise-period:not(.excise-period--more)")).to_have_count(12)
    earlier.click()
    expect(boxes).to_have_count(3)
    page.context.close()


def test_recording_a_period_as_lodged_locks_it_and_files_the_record(browser, app_url, excise_org):
    page = _open(browser, app_url, excise_org)
    page.locator("#excise-entry-ref").fill("EX-E2E-1")
    page.get_by_role("button", name="Record as lodged").click()
    expect(page.locator(".customs-entry-head .customs-status--lodged")).to_be_visible()
    expect(page.locator(".excise-period--active")).to_contain_text("Lodged")
    expect(page.locator("#excise-entry-ref")).to_have_count(0)
    # The lodgement is its own evidence: the "entry lodged" check is current without typing.
    page.locator("[data-customs-records] > summary").click()
    lodged = page.locator(".customs-control", has_text="entry lodged")
    expect(lodged.locator(".customs-chip")).to_have_text("Current")
    expect(page.locator(".customs-record").first).to_contain_text("Ref EX-E2E-1")
    assert_clean_page(page)
    page.context.close()


def test_a_period_link_opens_that_period(browser, app_url, excise_org):
    start = _months_back(1)
    page = _open(browser, app_url, excise_org, query=f"?period={start.isoformat()}")
    expect(page.locator(".customs-entry-head h3")).to_have_text(start.strftime("%B %Y"))
    page.context.close()


def test_records_open_as_one_card_per_customs_check(browser, app_url, excise_org):
    page = _open(browser, app_url, excise_org)
    page.locator("[data-customs-records] > summary").click()
    expect(page.locator(".customs-control")).to_have_count(5)
    page.get_by_role("button", name="Add evidence for Movement evidence kept").click()
    expect(page.locator("[data-record-form]")).to_be_visible()
    expect(page.locator("[data-control-select]")).to_have_value("movement-evidence")
    assert_clean_page(page)
    page.context.close()


def test_settings_shows_lodging_limits_and_saves_the_stocktake_schedule(browser, app_url, excise_org):
    page = _open(browser, app_url, excise_org, path=PAGE + "/settings", ready="[data-lodging-eligibility]:not(:empty)")
    # The fixture org has no workflow, so there is no final product to set up yet.
    expect(page.locator("[data-excise-products]")).to_contain_text("No products yet")
    expect(page.locator("[data-lodging-eligibility]")).to_contain_text("Duty over the last 12 months")
    expect(page.locator("#excise-frequency")).to_have_value("monthly")
    page.locator("#customs-stocktake-frequency").select_option("quarterly")
    with page.expect_response(lambda r: r.url.endswith("/api/compliant/nz-alcohol/excise/position")):
        page.locator("[data-stocktake-settings]").get_by_role("button", name="Save").click()
    expect(page.locator("[data-stocktake-next]")).to_contain_text("No stocktake yet")
    page.reload()
    page.locator("[data-lodging-eligibility]:not(:empty)").wait_for()
    expect(page.locator("#customs-stocktake-frequency")).to_have_value("quarterly")
    assert_clean_page(page)
    page.context.close()


def test_stock_moves_out_of_the_licensed_area_as_a_removal(browser, app_url, excise_org):
    page = _open(browser, app_url, excise_org, path=PAGE + "/stock", ready=".customs-place")
    expect(page.locator(".customs-place--inside")).to_contain_text("100 bottles")
    page.locator("#excise-location-name").fill("Sam's car")
    page.get_by_role("button", name="Add place").click()
    expect(page.locator("#excise-move-to option", has_text="Sam's car")).to_have_count(1)
    page.locator("#excise-move-qty").fill("6")
    page.locator("#excise-move-to").select_option(label="Sam's car (outside)")
    page.get_by_role("button", name="Move stock").click()
    expect(page.locator("[data-move-result]")).to_contain_text("removal on the entry")
    expect(page.locator(".customs-place--outside")).to_contain_text("6 bottles")
    assert_clean_page(page)
    page.context.close()


@pytest.mark.parametrize(
    "viewport",
    [{"width": 390, "height": 844}, {"width": 1440, "height": 900}, {"width": 1920, "height": 1080}],
    ids=["phone", "laptop", "wall"],
)
def test_the_entry_page_fits_each_width(browser, app_url, excise_org, viewport):
    """Tiles to copy from on a laptop; on a phone the same four figures read as a list."""
    page = _open(browser, app_url, excise_org, viewport=viewport)
    phone = viewport["width"] < 721
    expect(page.locator(".customs-summary" if phone else ".customs-tiles")).to_be_visible()
    expect(page.locator(".customs-tiles" if phone else ".customs-summary")).to_be_hidden()
    for region in ("[data-excise-periods]", "[data-excise-draft]", "[data-customs-position]", "[data-customs-records]"):
        expect(page.locator(region)).to_have_count(1)
    expect(page.get_by_role("button", name="Record as lodged")).to_be_visible()
    overflow = page.evaluate("() => document.scrollingElement.scrollWidth - document.scrollingElement.clientWidth")
    assert overflow <= 1, f"scrolls sideways by {overflow}px at {viewport['width']}px"
    page.context.close()


@pytest.mark.parametrize(
    ("path", "ready"), [("/stock", ".customs-place"), ("/settings", "[data-lodging-eligibility]:not(:empty)")]
)
def test_stock_and_settings_fit_a_phone(browser, app_url, excise_org, path, ready):
    page = _open(browser, app_url, excise_org, viewport={"width": 390, "height": 844}, path=PAGE + path, ready=ready)
    overflow = page.evaluate("() => document.scrollingElement.scrollWidth - document.scrollingElement.clientWidth")
    assert overflow <= 1, f"{path} scrolls sideways by {overflow}px on a phone"
    assert_clean_page(page)
    page.context.close()
