"""The Customs excise page with several sites (GL-P07 A5): a tab per CCA licence, each with its
own entry, lodged on its own.

Requests are routed into the Flask test client (see test_crm_contact_sync_ui).
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from decimal import Decimal

import pytest
from playwright.sync_api import expect

from app.core.db.models.site import Site
from app.core.db.models.stock_location import StockLocation
from app.core.db.models.user import UserRole
from app.core.security.tenant_scope import unscoped
from tests.dag_traversal_helpers import clear_org_synthetic_data
from tests.e2e.test_crm_contact_sync_ui import client, sales_page  # noqa: F401 -- fixture re-export
from tests.factories import grant_multi_site
from tests.test_crm import db, org  # noqa: F401 -- fixture re-export
from tests.test_crm import user as _member  # noqa: F401 -- fixture re-export
from tests.test_customs_premises import coverage_data, licence_data

pytestmark = pytest.mark.e2e

BASE = "https://crm.test"
GIN = "CCA tab gin"


def _last_month() -> date:
    first = date.today().replace(day=1)
    return (first - timedelta(days=1)).replace(day=1)


@pytest.fixture()
def user(_member, db):  # noqa: F811
    _member.role = UserRole.ADMIN
    db.commit()
    grant_multi_site(db, _member.org_id)
    return _member


@pytest.fixture()
def two_ccas(org, db, client):  # noqa: F811
    from app.core.db.repositories.feature_subscription_repo import FeatureSubscriptionRepository
    from app.core.db.repositories.inventory_repo import InventoryRepository
    from app.features.compliant.models import ComplianceProfile
    from app.features.compliant.models.alcohol_product_profile import AlcoholProductProfile
    from app.features.compliant.models.customs_premises import CustomsCoverage, CustomsLicence
    from app.features.compliant.models.excise import ExciseLodgement
    from app.features.compliant.modules.nz_alcohol import premises
    from app.features.crm.models.sales_fifo_allocation import SalesFifoAllocation
    from app.features.crm.models.xero_invoice import XeroInvoice

    with unscoped():
        FeatureSubscriptionRepository(db).grant(org.id, "compliant")
        db.add(
            ComplianceProfile(
                org_id=org.id,
                enabled=True,
                settings={"alcohol_product_types": ["spirits"], "excise_frequency": "monthly"},
            )
        )
        db.add(
            AlcoholProductProfile(
                org_id=org.id,
                inventory_name=GIN,
                product_type="spirits",
                pack_volume_ml=Decimal("700"),
                excise_category="gin",
            )
        )
        db.commit()
    assert client.put("/api/core/sites/settings", json={"enabled": True}).status_code == 200
    with unscoped():
        main = db.query(Site).filter(Site.org_id == org.id, Site.is_default.is_(True)).one()
        bond = Site(id=uuid.uuid4(), org_id=org.id, name="Bond store", kind="storage", is_active=True)
        db.add(bond)
        db.flush()
        one = premises.add_licence(db, org.id, licence_data(number="CCA-1", name="Distillery"))
        two = premises.add_licence(db, org.id, licence_data(number="CCA-2", name="Bond", kind="oss"))
        premises.add_coverage(db, org.id, coverage_data(one, main))
        premises.add_coverage(db, org.id, coverage_data(two, bond))
        lot = InventoryRepository(db).create_inventory_item(
            org_id=org.id,
            name=GIN,
            quantity="100",
            unit="bottles",
            inventory_type="final_product",
            supplier_batch_number="VAT1",
            extra_data={"abv_percent": "44"},
            site_id=main.id,
        )
        invoice = XeroInvoice(
            org_id=org.id,
            xero_invoice_id=f"inv-{uuid.uuid4()}",
            xero_tenant_id="e2e",
            invoice_type="ACCREC",
            status="AUTHORISED",
            invoice_number="INV-CCA-1",
            date=_last_month() + timedelta(days=4),
        )
        db.add(invoice)
        db.flush()
        db.add(
            SalesFifoAllocation(
                org_id=org.id,
                xero_invoice_id=invoice.xero_invoice_id,
                xero_line_key="l1",
                inventory_item_id=lot.id,
                product_name=GIN,
                quantity=Decimal("10"),
                unit="bottles",
            )
        )
        db.commit()
    yield one, two
    db.rollback()
    with unscoped():
        for model in (ExciseLodgement, SalesFifoAllocation, XeroInvoice, CustomsCoverage, CustomsLicence):
            db.query(model).filter(model.org_id == org.id).delete(synchronize_session=False)
        db.query(AlcoholProductProfile).filter(AlcoholProductProfile.org_id == org.id).delete(synchronize_session=False)
        db.query(ComplianceProfile).filter(ComplianceProfile.org_id == org.id).delete(synchronize_session=False)
        clear_org_synthetic_data(db, org.id)
        db.query(StockLocation).filter(StockLocation.org_id == org.id).delete(synchronize_session=False)
        db.commit()


def test_each_cca_has_its_own_entry_lodged_on_its_own(sales_page, two_ccas):  # noqa: F811
    period = _last_month().isoformat()
    sales_page.set_viewport_size({"width": 1440, "height": 900})
    sales_page.goto(f"{BASE}/compliant/nz-alcohol/customs?period={period}")
    tabs = sales_page.locator(".excise-cca")
    expect(tabs).to_have_count(2)
    expect(tabs.nth(0)).to_contain_text("CCA-1")
    expect(tabs.nth(0)).to_have_attribute("aria-pressed", "true")
    draft = sales_page.locator("[data-excise-draft]")
    expect(draft).to_contain_text("10 bottles")  # the distillery's sale
    lodge = sales_page.get_by_role("button", name="Record as lodged for CCA-1")
    lodge.click()
    expect(draft).to_contain_text("Recorded as lodged")
    expect(tabs.nth(0)).to_contain_text("Lodged")
    # The bond store's licence sold nothing: a nil return of its own, still to lodge.
    tabs.nth(1).click()
    expect(tabs.nth(1)).to_have_attribute("aria-pressed", "true")
    expect(tabs.nth(1)).to_contain_text("To lodge")
    expect(sales_page.get_by_role("button", name="Record nil return as lodged for CCA-2")).to_be_visible()


def test_a_reminder_link_opens_that_cca(sales_page, two_ccas):  # noqa: F811
    _, two = two_ccas
    sales_page.set_viewport_size({"width": 390, "height": 900})
    sales_page.goto(f"{BASE}/compliant/nz-alcohol/customs?period={_last_month().isoformat()}&cca={two.id}")
    expect(sales_page.locator(".excise-cca[aria-pressed='true']")).to_contain_text("CCA-2")
    assert sales_page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
