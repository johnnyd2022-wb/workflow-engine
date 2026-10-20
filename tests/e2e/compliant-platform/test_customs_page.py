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


def _open(browser, app_url, user, viewport=None, query=""):
    context = browser.new_context(
        base_url=app_url, ignore_https_errors=True, viewport=viewport or {"width": 1440, "height": 900}
    )
    page = context.new_page()
    attach_probe(page)
    login_through_ui(page, user["email"], user["password"])
    page.goto(PAGE + query)
    page.locator("[data-excise-draft] .customs-entry-head").wait_for()
    return page


def test_lands_on_the_oldest_unlodged_period_with_the_customs_entry(browser, app_url, excise_org):
    page = _open(browser, app_url, excise_org, query="?style=1")
    label = _months_back(2).strftime("%B %Y")
    expect(page.locator(".customs-entry-head h3")).to_have_text(label)
    expect(page.locator(".customs-entry-head .customs-status")).to_contain_text("Overdue")
    # 50 x 0.7 L = 35 L; x 44% = 15.4 LAL; levy 35 L x the cents rate; GST on the levy only.
    row = page.locator(".customs-entry-table tbody tr").first
    expect(row).to_contain_text("99.45.35A")
    expect(row).to_contain_text("35.000")
    expect(row).to_contain_text("15.400")
    expect(page.locator(".customs-tile--total .customs-tile__value")).to_have_text(re.compile(r"^\$1,1\d\d\.\d\d$"))
    # Months before reminders began fold into one control.
    expect(page.locator(".excise-period--more")).to_contain_text("earlier month")
    assert_clean_page(page)
    page.context.close()


def test_recording_a_period_as_lodged_locks_it(browser, app_url, excise_org):
    page = _open(browser, app_url, excise_org, query="?style=1")
    page.locator("#excise-entry-ref").fill("EX-E2E-1")
    page.get_by_role("button", name="Record as lodged").click()
    expect(page.locator(".customs-entry-head .customs-status--lodged")).to_be_visible()
    expect(page.locator(".excise-period--active")).to_contain_text("Lodged")
    expect(page.locator("#excise-entry-ref")).to_have_count(0)
    assert_clean_page(page)
    page.context.close()


def test_a_period_link_opens_that_period(browser, app_url, excise_org):
    start = _months_back(1)
    page = _open(browser, app_url, excise_org, query=f"?style=1&period={start.isoformat()}")
    expect(page.locator(".customs-entry-head h3")).to_have_text(start.strftime("%B %Y"))
    page.context.close()


# CONCEPT ONLY: the three page styles at each width; deleted with the losing styles.
@pytest.mark.parametrize("style", ["1", "2", "3"])
@pytest.mark.parametrize(
    "viewport",
    [{"width": 390, "height": 844}, {"width": 1440, "height": 900}, {"width": 1920, "height": 1080}],
    ids=["phone", "laptop", "wall"],
)
def test_concept_styles_fit_without_sideways_scroll(browser, app_url, excise_org, style, viewport):
    page = _open(browser, app_url, excise_org, viewport=viewport, query=f"?style={style}")
    expect(page.locator(f'[data-customs-style="{style}"]')).to_have_count(1)
    for region in ("[data-excise-periods]", "[data-excise-draft]", ".customs-more", "[data-record-target]"):
        expect(page.locator(region)).to_have_count(1)
    expect(page.get_by_role("button", name="Record as lodged")).to_be_visible()
    overflow = page.evaluate("() => document.scrollingElement.scrollWidth - document.scrollingElement.clientWidth")
    assert overflow <= 1, f"style {style} scrolls sideways by {overflow}px at {viewport['width']}px"
    page.context.close()
