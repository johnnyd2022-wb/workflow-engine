"""Real HTTPS and phone-size home-removal evidence form, with no request interception."""

import threading
from datetime import date
from decimal import Decimal
from uuid import UUID

import pytest
from playwright.sync_api import expect
from werkzeug.serving import make_server

from app.core.db.models.site import Site
from app.core.db.models.site_transfer import SiteStockTransfer
from app.core.db.models.stock_location import StockLocation
from app.core.db.models.user import User
from app.core.security.tenant_scope import unscoped
from app.features.compliant.models.alcohol_product_profile import AlcoholProductProfile
from app.features.compliant.models.compliance_profile import ComplianceProfile
from app.features.compliant.models.excise import ExciseRate
from app.features.compliant.modules.nz_alcohol import premises
from app.features.compliant.platform.stock_movements import evaluate_stock_movement, movement_requirements
from app.features.site_transfers import routes
from tests.factories import DEFAULT_TEST_PASSWORD
from tests.test_customs_premises import coverage_data, licence_data
from tests.test_site_operations import released  # noqa: F401 -- fixture re-export
from tests.test_site_transfers import transfers  # noqa: F401 -- fixture re-export
from tests.test_sites import flask_app, world  # noqa: F401 -- fixture re-export

pytestmark = pytest.mark.e2e


@pytest.fixture
def removal_server(transfers, db, flask_app, monkeypatch):  # noqa: F811 -- imported fixtures
    org, _, _, _, default, _, _, actor_id = transfers
    monkeypatch.setattr(routes, "_policy", evaluate_stock_movement)
    from app.core.db import db_session

    monkeypatch.setattr(routes, "_requirements", lambda: movement_requirements(db_session, org.id))
    with unscoped():
        db.add(ComplianceProfile(org_id=org.id, enabled=True, industry_module="nz_alcohol"))
        db.add(
            AlcoholProductProfile(
                org_id=org.id,
                inventory_name="House Gin",
                product_type="spirits",
                pack_volume_ml=Decimal("700"),
                customs_product_code="BROWSER-SPIRITS",
            )
        )
        db.add(
            ExciseRate(
                org_id=org.id,
                tariff_item="BROWSER-SPIRITS",
                rate_per_lal=Decimal("42.50"),
                effective_from=date(2026, 7, 1),
            )
        )
        site = db.get(Site, UUID(default["id"]))
        licence = premises.add_licence(db, org.id, licence_data(number="BROWSER-HOME"))
        premises.add_coverage(db, org.id, coverage_data(licence, site))
        shop = StockLocation(org_id=org.id, site_id=site.id, name="Cellar door", inside_licensed_area=False)
        db.add(shop)
        email = db.get(User, actor_id).email
        db.commit()
        shop_id = str(shop.id)
    server = make_server("127.0.0.1", 0, flask_app, threaded=True, ssl_context="adhoc")
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"https://127.0.0.1:{server.server_port}", email, default["id"], shop_id, org.id
    finally:
        server.shutdown()
        thread.join(timeout=5)
        with unscoped():
            db.query(ExciseRate).filter(ExciseRate.org_id == org.id).delete(synchronize_session=False)
            db.commit()


@pytest.mark.parametrize("width", [1440, 390])
def test_measured_home_dispatch_and_partial_receipt(browser, removal_server, db, width):
    url, email, site_id, shop_id, org_id = removal_server
    context = browser.new_context(ignore_https_errors=True, viewport={"width": width, "height": 1000})
    try:
        assert (
            context.request.post(url + "/auth/login", data={"email": email, "password": DEFAULT_TEST_PASSWORD}).status
            == 200
        )
        page = context.new_page()
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto(url + "/core/site-transfers")
        form = page.locator("[data-transfer-dispatch]")
        expect(form).to_be_visible()
        form.locator('[name="quantity"]').fill("10")
        form.locator('[name="destination_site_id"]').select_option(site_id)
        form.locator('[name="destination_location_id"]').select_option(shop_id)
        form.locator('[name="carrier"]').fill("Browser courier")
        form.locator('[name="consignment_reference"]').fill("HOME-DOCKET")
        form.locator('[name="approval.destination_activity"]').select_option("selling")
        form.locator('[name="approval.authority"]').select_option("home_consumption")
        form.locator('[name="approval.evidence_reference"]').fill("Excise removal review")
        form.locator('[name="approval.measured_abv_percent"]').fill("45")
        form.locator('[name="approval.measurement_method"]').select_option("hydrometric")
        form.locator('[name="approval.measured_on"]').fill(date.today().isoformat())
        form.locator('[name="approval.measurement_reference"]').fill("Hydrometer certificate")
        form.locator('[name="approval.volume_reference"]').fill("700 mL bottle record")
        form.get_by_role("button", name="Dispatch", exact=True).click()
        expect(page.locator("[data-transfers-list] article")).to_have_count(1)
        expect(page.locator("[data-transfers-list]")).to_contain_text("Transit 10.0000")
        with unscoped():
            transfer = db.query(SiteStockTransfer).filter(SiteStockTransfer.org_id == org_id).one()
            assert transfer.decision_snapshot["tax_status"] == "home_consumption_excise_due"
        page.locator("[data-transfers-list] summary").click()
        receipt = page.locator("[data-transfers-list] form")
        receipt.locator('[name="quantity"]').fill("4")
        receipt.get_by_role("button", name="Record receipt", exact=True).click()
        expect(page.locator("[data-transfers-list]")).to_contain_text("Received 4.0000")
        assert not errors
        assert page.evaluate("document.documentElement.scrollWidth") <= width
    finally:
        context.close()
