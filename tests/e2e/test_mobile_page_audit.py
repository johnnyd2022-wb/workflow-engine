"""Phone-width smoke and screenshot inventory for navigable app pages.

Screenshots are saved when MOBILE_AUDIT_SCREENSHOTS is set. The visual review ledger
is docs/mobile-page-audit-index.md; geometry alone does not certify visual quality.
"""

import os
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from urllib.parse import urlparse
from uuid import UUID, uuid4

import pytest
from playwright.sync_api import expect

from app.core.db import db_session
from app.core.db.models.execution_step import ExecutionStepStatus
from app.core.db.models.user import User, UserRole
from app.core.db.repositories.feature_subscription_repo import FeatureSubscriptionRepository
from app.core.db.repositories.process_repo import ProcessRepository
from app.core.security.people import issue_invite
from app.features.compliant.service import ComplianceService
from app.features.contract_manufacturing.models.orders import ContractCustomer, ContractOrder
from app.features.crm.models.xero_contact import XeroContact
from app.features.operational_cases.models.operational_case import OperationalCase
from tests.e2e.conftest import assert_clean_page, attach_probe
from tests.factories import ExecutionFactory, InventoryItemFactory, ProcessFactory, UserFactory

pytestmark = pytest.mark.e2e
PHONE_WIDTH = int(os.environ.get("MOBILE_AUDIT_WIDTH", "390"))

PUBLIC_PAGES = ["/", "/landing-diagram", "/pricing", "/privacy", "/terms", "/portal/login", "/portal/invite"]

APP_PAGES = [
    "/core",
    "/core/dashboard",
    "/core/getting-started",
    "/core/go-live",
    "/core/processes",
    "/core/flows",
    "/core/flows/create/process-overview",
    "/core/flows/create/start",
    "/core/flows/create/template-catalog",
    "/core/inventory/view",
    "/core/inventory/live",
    "/core/inventory/add",
    "/core/inventory/add/manual",
    "/core/inventory/add/csv",
    "/core/inventory/add/barcode",
    "/core/inventory/dispose",
    "/core/executions/live",
    "/core/notifications",
    "/core/record",
    "/core/people",
    "/core/planner",
    "/core/planner/board",
    "/core/settings",
    "/core/integrations",
    "/core/sites",
    "/core/site-transfers",
    "/core/stocktake",
    "/core/suppliers",
    "/core/sourcemap",
    "/core/tasks/configuration",
    "/core/cases",
    "/core/cases/new",
    "/core/contracts",
    "/core/contracts/materials",
    "/crm",
    "/crm/customers",
    "/crm/tasks",
    "/crm/analytics",
    "/crm/configuration",
    "/crm/matching",
    "/crm/excise",
    "/compliant",
    "/compliant/nz-alcohol",
    "/compliant/nz-alcohol/configuration",
    "/compliant/nz-alcohol/customs",
    "/compliant/nz-alcohol/customs/records",
    "/compliant/nz-alcohol/customs/settings",
    "/compliant/nz-alcohol/customs/stock",
    "/compliant/nz-alcohol/customs/transfers",
    "/compliant/nz-alcohol/food-registrations",
    "/compliant/nz-alcohol/food-safety",
    "/compliant/nz-alcohol/food-safety/checks",
    "/compliant/nz-alcohol/licensing",
    "/compliant/nz-alcohol/premises",
    "/compliant/tools",
]


@pytest.fixture(scope="module", autouse=True)
def mobile_audit_subscription(e2e_user):
    db = db_session()
    db.get(User, UUID(e2e_user["user_id"])).role = UserRole.ADMIN
    FeatureSubscriptionRepository(db).grant(e2e_user["org_id"], "compliant")
    ComplianceService(db).upsert_profile(e2e_user["org_id"], {"enabled": True, "industry_module": "nz_alcohol"})
    db.commit()


def _capture_and_measure(page, path):
    page.wait_for_load_state("networkidle")
    out = os.environ.get("MOBILE_AUDIT_SCREENSHOTS")
    if out:
        target = Path(out) / f"{path.strip('/').replace('/', '__') or 'landing'}-{PHONE_WIDTH}"
        target.parent.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(target.with_suffix(".png")), full_page=True)
    return page.evaluate(
        """() => ({
          viewport: innerWidth,
          document: document.documentElement.scrollWidth,
          body: document.body.scrollWidth,
          title: document.title,
          heading: document.querySelector('h1')?.textContent?.trim() || ''
        })"""
    )


@pytest.mark.parametrize("path", PUBLIC_PAGES)
def test_public_page_at_phone_width(browser, app_url, path):
    context = browser.new_context(
        base_url=app_url, ignore_https_errors=True, viewport={"width": PHONE_WIDTH, "height": 844}
    )
    page = context.new_page()
    attach_probe(page)
    try:
        response = page.goto(path)
        assert response and response.ok, f"{path}: {response.status if response else 'no response'}"
        geometry = _capture_and_measure(page, path)
        assert geometry["document"] <= geometry["viewport"] + 1, f"{path}: {geometry}"
        assert_clean_page(page)
    finally:
        context.close()


@pytest.mark.parametrize("path", APP_PAGES)
def test_app_page_at_phone_width(browser, storage_state_path, app_url, path):
    context = browser.new_context(
        base_url=app_url,
        ignore_https_errors=True,
        storage_state=storage_state_path,
        viewport={"width": PHONE_WIDTH, "height": 844},
    )
    page = context.new_page()
    attach_probe(page)
    try:
        response = page.goto(path)
        assert response and response.ok, f"{path}: {response.status if response else 'no response'}"
        assert urlparse(page.url).path.rstrip("/") == path.rstrip("/"), f"{path} redirected to {page.url}"
        geometry = _capture_and_measure(page, path)
        assert geometry["document"] <= geometry["viewport"] + 1, f"{path}: {geometry}"
        assert_clean_page(page)
    finally:
        context.close()


@pytest.fixture()
def mobile_detail_records(e2e_user):
    db = db_session()
    org_id = UUID(e2e_user["org_id"])
    user_id = UUID(e2e_user["user_id"])
    contact = XeroContact(org_id=org_id, source="bize", name="Mobile audit bottle store", is_customer=True)
    case = OperationalCase(
        org_id=org_id,
        title="Check mobile case detail",
        source_type="manual",
        check_id="mobile-audit",
        source_entity_type="inventory_item",
        source_entity_id=uuid4(),
        source_snapshot={"schema_version": 1},
        owner_id=user_id,
        created_by=user_id,
        due_at=datetime.now(UTC) + timedelta(days=3),
        next_action="Review the finding",
    )
    contract_customer = ContractCustomer(org_id=org_id, name=f"Mobile audit producer {uuid4().hex[:8]}")
    db.add_all([contact, case, contract_customer])
    db.flush()
    order = ContractOrder(
        org_id=org_id,
        customer_id=contract_customer.id,
        reference=f"MOBILE-{uuid4().hex[:8]}",
        due_date=date.today(),
        status="draft",
        duty_responsibility="producer_licensee",
    )
    db.add(order)
    process = ProcessFactory(org_id=org_id, name=f"Mobile record workflow {uuid4().hex[:8]}")
    ProcessRepository(db).add_step(process.id, org_id, 1, "Record quality check", position=1000)
    execution = ExecutionFactory(org_id=org_id, process_id=process.id)
    execution_step = execution.execution_steps[0]
    execution_step.status = ExecutionStepStatus.COMPLETED
    execution_step.completed_at = datetime.now(UTC)
    inventory = InventoryItemFactory(org_id=org_id, name="Mobile audit stock", quantity="10")
    invited = UserFactory(org_id=org_id, email=f"mobile-invite-{uuid4().hex[:8]}@example.test")
    invited.is_active = False
    invite_token = issue_invite(invited)
    db.commit()
    return contact.id, case.id, order.id, execution.id, execution_step.id, inventory.id, invite_token


def test_seeded_detail_pages_at_phone_width(browser, storage_state_path, app_url, mobile_detail_records):
    from app.features.compliant.modules.nz_alcohol.catalogue import NZ_ALCOHOL_FRAMEWORKS

    contact_id, case_id, order_id, execution_id, execution_step_id, inventory_id, _invite_token = mobile_detail_records
    customs = next(f for f in NZ_ALCOHOL_FRAMEWORKS if f["slug"] == "customs-alcohol")
    np3 = next(f for f in NZ_ALCOHOL_FRAMEWORKS if f["slug"] == "np3-food-control")
    paths = [
        f"/crm/customers/{contact_id}",
        f"/core/cases/{case_id}",
        f"/core/contracts/{order_id}",
        f"/core/contracts/{order_id}/portal-sharing",
        f"/core/executions/{execution_id}/steps/{execution_step_id}/record",
        f"/core/inventory/dispose/confirm?inventory_item_id={inventory_id}&quantity_wasted=1",
        f"/compliant/nz-alcohol/customs/records/{customs['controls'][0][0]}",
        f"/compliant/nz-alcohol/np3-audit/check/{np3['controls'][0][0]}",
    ]
    context = browser.new_context(
        base_url=app_url,
        ignore_https_errors=True,
        storage_state=storage_state_path,
        viewport={"width": PHONE_WIDTH, "height": 844},
    )
    page = context.new_page()
    attach_probe(page)
    try:
        for path in paths:
            response = page.goto(path)
            assert response and response.ok, f"{path}: {response.status if response else 'no response'}"
            requested_path = urlparse(path).path
            assert urlparse(page.url).path == requested_path, f"{path} redirected to {page.url}"
            geometry = _capture_and_measure(page, requested_path)
            assert geometry["document"] <= geometry["viewport"] + 1, f"{path}: {geometry}"
            assert_clean_page(page)
    finally:
        context.close()


def test_valid_invitation_at_phone_width(browser, app_url, mobile_detail_records):
    invite_token = mobile_detail_records[-1]
    context = browser.new_context(
        base_url=app_url, ignore_https_errors=True, viewport={"width": PHONE_WIDTH, "height": 844}
    )
    page = context.new_page()
    try:
        path = f"/invite/{invite_token}"
        response = page.goto(path)
        assert response and response.ok, f"valid invitation returned {response.status if response else 'no response'}"
        geometry = _capture_and_measure(page, "/invite/valid-token")
        assert geometry["document"] <= geometry["viewport"] + 1, geometry
    finally:
        context.close()


def test_xero_tenant_picker_at_phone_width(browser, storage_state_path, app_url):
    """OAuth normally populates this session key after Xero returns multiple tenants."""
    from app.app import app

    context = browser.new_context(
        base_url=app_url,
        ignore_https_errors=True,
        storage_state=storage_state_path,
        viewport={"width": PHONE_WIDTH, "height": 844},
    )
    page = context.new_page()
    attach_probe(page)
    try:
        cookie_name = app.config.get("SESSION_COOKIE_NAME", "session")
        cookie = next(c for c in context.cookies() if c["name"] == cookie_name)
        serializer = app.session_interface.get_signing_serializer(app)
        session_data = serializer.loads(cookie["value"])
        session_data["_xero_pending_connections"] = [
            {
                "id": "first",
                "tenantId": "audit-first",
                "tenantName": "First test organisation",
                "tenantType": "ORGANISATION",
            },
            {
                "id": "second",
                "tenantId": "audit-second",
                "tenantName": "Second test organisation",
                "tenantType": "ORGANISATION",
            },
        ]
        context.add_cookies([{**cookie, "value": serializer.dumps(session_data)}])
        path = "/crm/xero/select-tenant"
        response = page.goto(path)
        assert response and response.ok, f"{path}: {response.status if response else 'no response'}"
        assert page.url.split("?", 1)[0].endswith(path), f"{path} redirected to {page.url}"
        geometry = _capture_and_measure(page, path)
        assert geometry["document"] <= geometry["viewport"] + 1, geometry
        assert_clean_page(page)
    finally:
        context.close()


def test_google_second_factor_page_at_phone_width(browser, app_url, e2e_user):
    """Inspect the transient page shown after Google sign-in when 2FA is required."""
    from app.app import app

    context = browser.new_context(
        base_url=app_url, ignore_https_errors=True, viewport={"width": PHONE_WIDTH, "height": 844}
    )
    page = context.new_page()
    attach_probe(page)
    try:
        serializer = app.session_interface.get_signing_serializer(app)
        context.add_cookies(
            [
                {
                    "name": app.config.get("SESSION_COOKIE_NAME", "session"),
                    "value": serializer.dumps(
                        {"pending_auth_method": "google", "pending_2fa_user_id": e2e_user["user_id"]}
                    ),
                    "url": app_url,
                    "secure": True,
                    "httpOnly": True,
                }
            ]
        )
        path = "/auth/google/challenge"
        response = page.goto(path)
        assert response and response.ok, f"{path}: {response.status if response else 'no response'}"
        assert urlparse(page.url).path == path, f"{path} redirected to {page.url}"
        geometry = _capture_and_measure(page, path)
        assert geometry["document"] <= geometry["viewport"] + 1, geometry
        assert_clean_page(page)
    finally:
        context.close()


def test_mobile_navigation_and_customer_task_sheet(browser, storage_state_path, app_url, mobile_detail_records):
    contact_id = mobile_detail_records[0]
    context = browser.new_context(
        base_url=app_url,
        ignore_https_errors=True,
        storage_state=storage_state_path,
        viewport={"width": PHONE_WIDTH, "height": 844},
    )
    page = context.new_page()
    attach_probe(page)
    try:
        page.goto("/core")
        page.locator("a.nav-link[href='/crm']").click()
        expect(page).to_have_url(f"{app_url}/crm")
        page.locator("a.nav-link[href='/compliant']").click()
        expect(page).to_have_url(f"{app_url}/compliant")
        page.locator("a.nav-link[href='/core']").click()
        expect(page).to_have_url(f"{app_url}/core")
        page.goto(f"/crm/customers/{contact_id}")
        page.get_by_role("button", name="New task").click()
        sheet = page.locator('.crm-task-sheet-overlay[x-show="showCustomerTaskModal"]')
        expect(sheet).to_be_visible()
        geometry = _capture_and_measure(page, "/crm/customers/task-sheet")
        assert geometry["document"] <= geometry["viewport"] + 1, geometry
        sheet.get_by_role("button", name="Close").click()
        assert_clean_page(page)
    finally:
        context.close()


def test_workflow_wizard_pages_at_phone_width(browser, storage_state_path, app_url):
    from tests.e2e.test_process_wizard_flow import _create_process_with_step

    context = browser.new_context(
        base_url=app_url,
        ignore_https_errors=True,
        storage_state=storage_state_path,
        viewport={"width": PHONE_WIDTH, "height": 844},
    )
    page = context.new_page()
    attach_probe(page)
    try:
        page.goto("/core/flows")
        process_id, step_id = _create_process_with_step(page, f"Mobile audit workflow {uuid4().hex[:8]}")
        for segment in (
            "process-overview",
            "step-name",
            "inputs",
            "outputs",
            "evidence-and-prompts",
            "summary",
            "next-steps",
        ):
            path = f"/core/flows/create/{segment}"
            response = page.goto(f"{path}?id={process_id}")
            assert response and response.ok, f"{path}: {response.status if response else 'no response'}"
            assert urlparse(page.url).path == path, f"{path} redirected to {page.url}"
            geometry = _capture_and_measure(page, path)
            assert geometry["document"] <= geometry["viewport"] + 1, f"{path}: {geometry}"
            assert_clean_page(page)
        path = "/core/flows/batches/start"
        response = page.goto(f"{path}?draft=1&id={process_id}&step_id={step_id}")
        assert response and response.ok, f"{path}: {response.status if response else 'no response'}"
        assert urlparse(page.url).path == path, f"{path} redirected to {page.url}"
        geometry = _capture_and_measure(page, path)
        assert geometry["document"] <= geometry["viewport"] + 1, f"{path}: {geometry}"
        assert_clean_page(page)
    finally:
        context.close()
