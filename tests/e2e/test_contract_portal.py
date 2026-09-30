"""Real HTTPS/CSRF portal publishing and sign-in regression; Chromium stays in E2E."""

from uuid import uuid4

import pytest
from playwright.sync_api import expect

from app.core.db.models.user import UserRole
from tests.e2e.conftest import csrf_headers, login_through_ui

pytestmark = pytest.mark.e2e


def test_publish_invite_and_customer_readonly_portal_at_390px(browser, app_url, fresh_user):
    admin = fresh_user(UserRole.ADMIN)
    contexts = []
    try:
        staff_context = browser.new_context(
            base_url=app_url, ignore_https_errors=True, viewport={"width": 390, "height": 844}
        )
        contexts.append(staff_context)
        page = staff_context.new_page()
        login_through_ui(page, admin["email"], admin["password"])
        customer = page.request.post(
            "/api/core/contract-customers",
            headers=csrf_headers(page),
            data={"name": f"Brand <script>alert(1)</script> {uuid4().hex[:8]}"},
        )
        assert customer.status == 201
        customer_id = customer.json()["customer"]["id"]
        created = page.request.post(
            "/api/core/contract-orders",
            headers=csrf_headers(page),
            data={
                "customer_id": customer_id,
                "reference": f"E2E-{uuid4().hex[:8]}",
                "due_date": "2026-12-01",
                "status": "confirmed",
                "duty_responsibility": "producer_licensee",
                "lines": [{"product_name": "Gin", "quantity": "600", "unit": "bottles", "materials_source": "mixed"}],
            },
        )
        assert created.status == 201
        order = created.json()["order"]
        page.goto(f"/core/contracts/{order['id']}/portal-sharing")
        upload = page.locator("form[data-upload]")
        upload.locator('[name="title"]').fill("Lab result <b>shared</b>")
        upload.locator('[name="document"]').set_input_files(
            {"name": "coa.pdf", "mimeType": "application/pdf", "buffer": b"%PDF-1.4\nShared laboratory result"}
        )
        with page.expect_response("**/portal-documents") as uploaded:
            upload.get_by_role("button", name="Upload copy").click()
        assert uploaded.value.status == 201
        expect(page.locator('form[data-publication] [name="document_ids"]')).to_have_count(1)
        document_id = page.locator('form[data-publication] [name="document_ids"]').input_value()
        publish = page.locator("form[data-publication]")
        publish.locator('[name="stage_label"]').fill("Packed <script>alert(2)</script>")
        publish.locator('[name="actual_abv"]').fill("40.2")
        publish.locator('[name="spec_abv"]').fill("40")
        publish.locator('[name="document_ids"]').check()
        publish.get_by_role("button", name="Publish update").click()
        expect(page.get_by_text("Last revision: 1")).to_be_visible()
        approval = page.request.post(
            f"/api/core/contract-orders/{order['id']}/portal-approvals",
            headers=csrf_headers(page),
            data={"document_id": document_id, "prompt": "Approve the shared label proof"},
        )
        assert approval.status == 201, approval.text()
        email = f"portal-e2e-{uuid4().hex[:8]}@brand.test"
        invite = page.locator("form[data-invite]")
        invite.locator('[name="email"]').fill(email)
        invite.get_by_role("button", name="Create invitation").click()
        expect(page.locator("[data-invite-result]")).to_be_visible()
        link = page.locator("[data-invite-result]").inner_text().removeprefix("Invitation: ")
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth + 1")

        customer_context = browser.new_context(
            base_url=app_url, ignore_https_errors=True, viewport={"width": 390, "height": 844}
        )
        contexts.append(customer_context)
        portal = customer_context.new_page()
        portal.goto(link)
        assert "#" not in portal.url
        password = "E2E-Portal-Password-2026"
        portal.locator('[name="password"]').fill(password)
        portal.get_by_role("button", name="Create portal account").click()
        expect(portal.get_by_role("heading", name="Your orders", exact=True)).to_be_visible()
        portal.get_by_role("link", name=order["reference"], exact=True).click()
        expect(portal.get_by_role("heading", name=order["reference"], exact=True)).to_be_visible()
        expect(portal.get_by_text("Shared actual ABV: 40.2%")).to_be_visible()
        expect(portal.get_by_text("Approve the shared label proof")).to_be_visible()
        portal.get_by_role("button", name="Approve proof").click()
        expect(portal.locator("form[data-approval-api]")).to_have_count(0)
        assert "approved" in portal.get_by_role("heading", name="10. What's waiting on you").locator("..").inner_text()
        expect(portal.get_by_text("Order declaration: producer licensee responsible for excise.")).to_be_visible()
        expect(
            portal.get_by_text("Dispatch, Customs treatment and payment have not been verified or shared")
        ).to_be_visible()
        portal.locator('textarea[name="body"]').fill("Can you confirm the bottling date? <b>Thanks</b>")
        portal.get_by_role("button", name="Send message").click()
        expect(portal.locator('[data-message="customer"]')).to_have_count(1)
        assert "<b>Thanks</b>" in portal.locator('[data-message="customer"]').inner_text()
        assert portal.locator("h2").count() == 10
        assert portal.locator("main script").count() == 0
        assert portal.locator("main b").count() == 0
        assert portal.locator('a[href^="/core/"]').count() == 0
        assert portal.evaluate("document.documentElement.scrollWidth <= window.innerWidth + 1")
        with portal.expect_download() as download:
            portal.get_by_role("link", name="Lab result <b>shared</b>").click()
        assert download.value.suggested_filename.endswith(".pdf")
        assert portal.request.get("/api/core/processes").status == 403
        portal.get_by_role("button", name="Sign out", exact=True).click()
        expect(portal.get_by_role("heading", name="Sign in to your orders")).to_be_visible()
        portal.locator('[name="email"]').fill(email)
        portal.locator('[name="password"]').fill(password)
        portal.get_by_role("button", name="Sign in", exact=True).click()
        expect(portal.get_by_role("heading", name="Your orders", exact=True)).to_be_visible()
        assert portal.request.get("/api/core/processes").status == 403
    finally:
        for context in contexts:
            context.close()
