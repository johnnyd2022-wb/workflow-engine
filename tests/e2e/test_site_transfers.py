"""Real HTTPS dispatch, approval form, partial receipt and mobile geometry.

The internal operations gate is enabled only in this isolated fixture. The module
provider and its generic field metadata are real; requests are not intercepted.
"""

import threading
from uuid import UUID

import pytest
from playwright.sync_api import expect
from werkzeug.serving import make_server

from app.core.db.models.site import Site
from app.core.db.models.user import User
from app.core.security.tenant_scope import unscoped
from app.features.compliant.models.alcohol_product_profile import AlcoholProductProfile
from app.features.compliant.models.compliance_profile import ComplianceProfile
from app.features.compliant.modules.nz_alcohol import premises
from app.features.compliant.platform.stock_movements import evaluate_stock_movement, movement_requirements
from app.features.site_transfers import routes
from tests.factories import DEFAULT_TEST_PASSWORD
from tests.test_customs_premises import coverage_data, licence_data
from tests.test_site_operations import released  # noqa: F401
from tests.test_site_transfers import transfers  # noqa: F401
from tests.test_sites import flask_app, world  # noqa: F401

pytestmark = pytest.mark.e2e


@pytest.fixture
def transfer_server(transfers, db, flask_app, monkeypatch):  # noqa: F811
    org, _, _, _, default, additional, _, actor_id = transfers
    monkeypatch.setattr(routes, "_policy", evaluate_stock_movement)
    # Resolve request-thread sessions, not the test thread's scoped session.
    from app.core.db import db_session

    monkeypatch.setattr(routes, "_requirements", lambda: movement_requirements(db_session, org.id))
    with unscoped():
        db.add(ComplianceProfile(org_id=org.id, enabled=True, industry_module="nz_alcohol"))
        db.add(AlcoholProductProfile(org_id=org.id, inventory_name="House Gin", product_type="spirits"))
        for index, site in enumerate((default, additional)):
            licence = premises.add_licence(db, org.id, licence_data(number=f"BROWSER-{index}"))
            premises.add_coverage(db, org.id, coverage_data(licence, db.get(Site, UUID(site["id"]))))
        email = db.get(User, actor_id).email
        db.commit()
    server = make_server("127.0.0.1", 0, flask_app, threaded=True, ssl_context="adhoc")
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"https://127.0.0.1:{server.server_port}", email, additional["id"]
    finally:
        server.shutdown()
        thread.join(timeout=5)


@pytest.mark.parametrize("width", [1440, 390])
def test_dispatch_approval_partial_receipt_and_docket(browser, transfer_server, width):
    url, email, destination = transfer_server
    context = browser.new_context(ignore_https_errors=True, viewport={"width": width, "height": 1000})
    try:
        response = context.request.post(url + "/auth/login", data={"email": email, "password": DEFAULT_TEST_PASSWORD})
        assert response.status == 200
        page = context.new_page()
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto(url + "/core/site-transfers")
        dispatch = page.locator("[data-transfer-dispatch]")
        expect(dispatch).to_be_visible()
        dispatch.locator('[name="quantity"]').fill("10")
        dispatch.locator('[name="destination_site_id"]').select_option(destination)
        dispatch.locator('[name="carrier"]').fill("Browser courier")
        dispatch.locator('[name="consignment_reference"]').fill("BROWSER-DOCKET")
        dispatch.locator('[name="approval.destination_activity"]').select_option("storage")
        dispatch.locator('[name="approval.authority"]').select_option("same_legal_entity")
        dispatch.locator('[name="approval.evidence_reference"]').fill("Registered licences")
        dispatch.get_by_role("button", name="Dispatch", exact=True).click()
        expect(page.locator("[data-transfers-list] article")).to_have_count(1)
        expect(page.locator("[data-transfers-list]")).to_contain_text("Transit 10.0000")
        page.locator("[data-transfers-list] summary").click()
        receipt = page.locator("[data-transfers-list] form")
        receipt.locator('[name="quantity"]').fill("4")
        receipt.get_by_role("button", name="Record receipt", exact=True).click()
        expect(page.locator("[data-transfers-list]")).to_contain_text("Transit 6.0000")
        expect(page.locator("[data-transfers-list]")).to_contain_text("Received 4.0000")
        # Full navigation/script state survives JSON submit (hx-boost false).
        assert page.url.endswith("/core/site-transfers")
        assert not errors
        page.locator("[data-transfers-list] summary").click()
        bounds = page.locator("input:visible, select:visible, button:visible").evaluate_all(
            "nodes => nodes.map(n => {const r=n.getBoundingClientRect();return {left:r.left,right:r.right}})"
        )
        assert all(item["left"] >= 0 and item["right"] <= width for item in bounds)
        assert page.evaluate("document.documentElement.scrollWidth") <= width
        with page.expect_popup() as opened:
            page.get_by_role("link", name="Print transfer docket").click()
        docket = opened.value
        expect(docket.get_by_role("heading", name="Stock transfer docket")).to_be_visible()
        expect(docket.locator("body")).to_contain_text("BROWSER-DOCKET")
        expect(docket.locator("body")).to_contain_text("BROWSER-0")
        expect(docket.locator("body")).to_contain_text("BROWSER-1")
    finally:
        context.close()
