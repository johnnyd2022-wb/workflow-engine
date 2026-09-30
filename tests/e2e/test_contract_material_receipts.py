"""Customer raw receipts through the real HTTPS/CSRF staff form at phone width."""

from uuid import UUID, uuid4

import pytest
from playwright.sync_api import expect
from sqlalchemy import text

from app.core.db import db_session
from app.core.db.models.organisation import Organisation
from app.core.db.models.user import UserRole
from tests.e2e.conftest import csrf_headers, login_through_ui

pytestmark = pytest.mark.e2e


def test_customer_raw_receipt_phone_form_and_csrf(browser, app_url, fresh_user):
    admin = fresh_user(UserRole.ADMIN)
    org_id = UUID(admin["org_id"])
    session = db_session()
    # Release remains off in production; only this throwaway tenant enables the slice.
    session.query(Organisation).filter(Organisation.id == org_id).update({"contract_materials_enabled": True})
    session.commit()
    context = browser.new_context(base_url=app_url, ignore_https_errors=True, viewport={"width": 390, "height": 844})
    try:
        page = context.new_page()
        login_through_ui(page, admin["email"], admin["password"])
        created = page.request.post(
            "/api/core/contract-customers", headers=csrf_headers(page), data={"name": "Brand <script>unsafe()</script>"}
        )
        assert created.status == 201
        customer_id = created.json()["customer"]["id"]
        path = f"/api/core/contract-customers/{customer_id}/material-receipts"
        data = {"name": "Botanicals", "quantity": "10", "unit": "kg", "evidence_reference": "Docket"}
        assert page.request.post(path, data=data, headers={"Idempotency-Key": str(uuid4())}).status == 400
        page.goto("/core/contracts")
        page.get_by_role("link", name="Customer raw materials").click()
        expect(page.get_by_role("heading", name="Customer materials", exact=True)).to_be_visible()
        page.locator("[data-material-customer]").select_option(customer_id)
        form = page.locator("form[data-material-receipt]")
        name = "Botanicals <b>free issue</b>"
        form.locator('[name="name"]').fill(name)
        form.locator('[name="quantity"]').fill("10")
        form.locator('[name="unit"]').fill("kg")
        form.locator('[name="supplier_batch_number"]').fill("BATCH")
        form.locator('[name="barcode"]').fill("SHARED-SUPPLIER-UPC")
        form.locator('[name="evidence_reference"]').fill("Delivery docket")
        with page.expect_response("**/material-receipts") as received:
            form.get_by_role("button", name="Receive materials").click()
        assert received.value.status == 201
        expect(page.locator("[data-material-list]")).to_contain_text(name)
        expect(page.locator("[data-material-list]")).to_contain_text("10.0000 kg")
        assert page.locator("[data-material-list] b").count() == 0
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth + 1")
        rows = page.request.get(f"/api/core/contract-customers/{customer_id}/materials").json()["materials"]
        assert len(rows) == 1 and rows[0]["free_issue_acquisition_cost"] == "0"
        assert not rows[0]["producer_acquisition_value_included"]
        assert (
            page.request.post(
                "/api/core/inventory", headers=csrf_headers(page), data={**data, "contract_customer_id": customer_id}
            ).status
            == 400
        )
    finally:
        context.close()
        # Immutable evidence is removed only by an explicit isolated-test purge.
        session.rollback()
        session.execute(text("SELECT set_config('app.migration_mode','1',true)"))
        session.execute(
            text("UPDATE inventory_items SET contract_customer_id=NULL, material_receipt_id=NULL WHERE org_id=:org"),
            {"org": org_id},
        )
        session.execute(text("DELETE FROM contract_material_receipts WHERE org_id=:org"), {"org": org_id})
        session.execute(text("DELETE FROM inventory_items WHERE org_id=:org"), {"org": org_id})
        session.commit()
