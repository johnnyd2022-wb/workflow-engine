"""Customs → Transfers (GL-P08): sales to another business's CCA, recorded as Customs' movement
register asks (when it left, who carried it, the receipt), and the CCAs you send to."""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from decimal import Decimal

import pytest
from playwright.sync_api import expect

from tests.e2e.conftest import assert_clean_page, attach_probe, login_through_ui

pytestmark = pytest.mark.e2e

TRANSFERS = "/compliant/nz-alcohol/customs/transfers"
READY = "[data-customs-transfers-root][aria-busy='false']"


@pytest.fixture()
def customs_org(fresh_user):
    from app.core.db import db_session
    from app.core.db.models.user import UserRole
    from app.core.db.repositories.feature_subscription_repo import FeatureSubscriptionRepository
    from app.features.compliant.models import ComplianceProfile

    user = fresh_user(UserRole.ADMIN)
    org_id = uuid.UUID(user["org_id"])
    db = db_session()
    FeatureSubscriptionRepository(db).grant(org_id, "compliant")
    db.add(ComplianceProfile(org_id=org_id, enabled=True, settings={"alcohol_product_types": ["spirits"]}))
    db.commit()
    return user


@pytest.fixture()
def duty_free_sale(customs_org):
    """A duty free shop linked to its customer, and one sale to it with no movement recorded."""
    from app.core.db import db_session
    from app.core.db.models.inventory_item import InventoryType
    from app.core.db.repositories.inventory_repo import InventoryRepository
    from app.features.compliant.models.cca_transfers import CcaDestination
    from app.features.crm.models.sales_fifo_allocation import SalesFifoAllocation
    from app.features.crm.models.xero_contact import XeroContact
    from app.features.crm.models.xero_invoice import XeroInvoice

    org_id = uuid.UUID(customs_org["org_id"])
    db = db_session()
    lot = InventoryRepository(db).create_inventory_item(
        org_id=org_id, name="Dry Gin 700 mL", quantity="200", unit="bottles",
        inventory_type=InventoryType.FINAL_PRODUCT.value,
    )  # fmt: skip
    shop = XeroContact(org_id=org_id, xero_contact_id=f"c-{uuid.uuid4()}", name="Airport Duty Free Ltd")
    db.add_all([shop, XeroContact(org_id=org_id, xero_contact_id=f"c-{uuid.uuid4()}", name="Corner Bottle Store")])
    db.flush()
    db.add(CcaDestination(org_id=org_id, name="Auckland Airport duty free", cca_code="DF-AKL-01",
                          address="Ray Emery Drive, Auckland Airport", kind="duty_free", contact_id=shop.id))  # fmt: skip
    invoice = XeroInvoice(org_id=org_id, xero_invoice_id=f"inv-{uuid.uuid4()}", xero_tenant_id="t",
                          invoice_type="ACCREC", status="AUTHORISED", invoice_number="INV-7001",
                          date=date.today() - timedelta(days=2), contact_id=shop.id)  # fmt: skip
    db.add(invoice)
    db.flush()
    db.add(SalesFifoAllocation(org_id=org_id, xero_invoice_id=invoice.xero_invoice_id, xero_line_key="l1",
                               inventory_item_id=lot.id, product_name=lot.name, quantity=Decimal(24), unit="bottles"))  # fmt: skip
    db.commit()
    return customs_org


def _open(browser, app_url, user, viewport=None):
    context = browser.new_context(
        base_url=app_url, ignore_https_errors=True, viewport=viewport or {"width": 1440, "height": 900}
    )
    page = context.new_page()
    attach_probe(page)
    login_through_ui(page, user["email"], user["password"])
    page.goto(TRANSFERS)
    page.locator(READY).wait_for()
    return page


def test_a_sale_to_a_linked_cca_is_recorded_then_received(browser, app_url, duty_free_sale):
    page = _open(browser, app_url, duty_free_sale)
    expect(page.locator(".customs-views a[aria-current='page']")).to_have_text("Transfers")
    row = page.locator("[data-tr-row]")
    expect(row).to_have_count(1)
    expect(row).to_contain_text("INV-7001")
    expect(row).to_contain_text("Needs movement details")

    row.click()
    form = page.locator("[data-tr-departure-form]")
    form.get_by_label("Carrier").fill("Mainfreight")
    form.get_by_label("Consignment note").fill("MF-1")
    form.get_by_role("button", name="Save movement").click()
    expect(page.locator("[data-tr-row]")).to_contain_text("Awaiting receipt")
    expect(page.locator("[data-tr-row]")).to_contain_text("Mainfreight")

    page.locator("[data-tr-row]").click()
    receipt = page.locator("[data-tr-receipt-form]")
    receipt.get_by_label("Their acknowledgement").fill("Signed delivery docket DF-4471")
    receipt.get_by_role("button", name="Save receipt").click()
    # Received transfers leave the to-do list.
    expect(page.locator("[data-tr-row]")).to_have_count(0)
    page.get_by_role("button", name="Received · 1").click()
    expect(page.locator("[data-tr-row]")).to_contain_text("Received")
    assert_clean_page(page)
    page.context.close()


def test_the_excise_entry_says_what_it_left_out_and_links_here(browser, app_url, duty_free_sale):
    page = _open(browser, app_url, duty_free_sale)
    page.goto("/compliant/nz-alcohol/customs")
    page.locator("[data-compliant-root][aria-busy='false']").wait_for()
    sold = date.today() - timedelta(days=2)  # the fixture's sale
    page.locator(f".excise-period[data-period='{sold.replace(day=1).isoformat()}']").click()
    note = page.locator("[data-excise-transfers]")
    expect(note).to_contain_text("Left out of duty: 1 sale to another CCA")
    note.get_by_role("link", name="Transfers →").click()
    page.locator(READY).wait_for()
    expect(page.locator("[data-tr-row]")).to_contain_text("INV-7001")
    page.context.close()


def test_a_cca_is_added_and_linked_to_its_customer(browser, app_url, customs_org):
    from app.core.db import db_session
    from app.features.crm.models.xero_contact import XeroContact

    db = db_session()
    db.add(
        XeroContact(org_id=uuid.UUID(customs_org["org_id"]), xero_contact_id=f"c-{uuid.uuid4()}", name="Harbour Export")
    )
    db.commit()
    page = _open(browser, app_url, customs_org)
    expect(page.locator("[data-tr-body] .customs-empty")).to_contain_text("No sales to other CCAs yet")
    page.locator(".tr-places-card [data-tr-add-place]").click()
    form = page.locator("[data-tr-place-form]")
    form.get_by_label("Name").fill("Wellington export warehouse")
    form.get_by_label("CCA code").fill("EW-WLG-77")
    form.get_by_label("Address").fill("12 Hutt Road, Wellington")
    form.get_by_label("Kind").select_option(label="Export warehouse")
    form.get_by_label("Customer").select_option(label="Harbour Export")
    form.get_by_role("button", name="Add CCA").click()
    place = page.locator("[data-tr-places] [data-tr-place]")
    expect(place).to_have_count(1)
    expect(place).to_contain_text("EW-WLG-77")
    expect(place).to_contain_text("sales to Harbour Export")
    assert_clean_page(page)
    page.context.close()


@pytest.mark.parametrize("viewport", [{"width": 390, "height": 844}, {"width": 1440, "height": 900}, {"width": 1920, "height": 1080}], ids=["phone", "laptop", "wall"])  # fmt: skip
def test_the_register_fits_without_sideways_scroll(browser, app_url, duty_free_sale, viewport):
    page = _open(browser, app_url, duty_free_sale, viewport=viewport)
    expect(page.locator("[data-tr-row]")).to_have_count(1)
    overflow = page.evaluate(
        "() => { const c = document.getElementById('page-content'); return c.scrollWidth - c.clientWidth; }"
    )
    assert overflow <= 1, f"the register scrolls sideways by {overflow}px"
    expect(page.locator("[data-tr-places-card]")).to_be_visible()
    expect(page.locator("[data-tr-style-pick]")).to_have_count(0)  # the design switch is gone
    page.context.close()
