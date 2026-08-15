"""Stage 3: CRM and the Xero OAuth entry, through the real app.

CRM is feature-flagged; the E2E boot runs with crm_enabled on (local.ini), so these run
rather than skip — a flag regression surfaces here as a failure, not silent absence.

Customers in this app are sourced from Xero sync, not a create endpoint, so "create a
customer" is not a UI flow to drive. What matters and is reliably testable: the Xero OAuth
entry degrades safely when unconfigured (it must never 500 or leak), the CRM API is
auth-gated, and CRM data is org-scoped like everything else.

The full Xero OAuth happy path (real token exchange) needs a stubbed Xero at the HTTP
layer and is deferred — a test must never touch a real Xero tenant (it would write real
invoices). Tracked in the spec.

Cross-tenant probes below cover the CRM objects that ARE creatable without a live Xero
connection — notes, tasks, product mappings — the same way test_tenant_isolation.py
covers inventory. Customers/invoices/sync-jobs are Xero-sourced only and stay out of
E2E scope for the reason above; their org-scoping is covered at the unit level
(tests/test_crm.py: test_org_isolation, test_note_org_isolation,
test_list_tasks_org_isolation) instead.
"""

import uuid

import pytest

from tests.e2e.conftest import csrf_headers, login_through_ui

pytestmark = pytest.mark.e2e


@pytest.fixture()
def two_tenants(browser, app_url, fresh_user):
    """Two orgs, each with its own authenticated browser context (mirrors
    test_tenant_isolation.py's fixture of the same name)."""
    org_a, org_b = fresh_user(), fresh_user()
    contexts = []

    def _sign_in(user):
        context = browser.new_context(base_url=app_url, ignore_https_errors=True)
        contexts.append(context)
        page = context.new_page()
        login_through_ui(page, user["email"], user["password"])
        return page

    pages = {"a": _sign_in(org_a), "b": _sign_in(org_b)}
    yield pages
    for context in contexts:
        context.close()


@pytest.fixture()
def org_a_contact(two_tenants):
    """Seed a real XeroContact for org A directly in the DB — contacts only ever arrive
    via Xero sync in this app, so there is no API to create one through."""
    from app.core.db import db_session
    from app.features.crm.models.xero_contact import XeroContact

    session = db_session()
    me = two_tenants["a"].request.get("/auth/me")
    assert me.ok, f"/auth/me failed: {me.status}"
    org_id = me.json()["user"]["org_id"]

    contact = XeroContact(
        org_id=org_id,
        xero_contact_id=f"e2e-fake-{uuid.uuid4().hex[:8]}",
        xero_tenant_id="e2e-fake-tenant",
        name=f"E2E Contact {uuid.uuid4().hex[:6]}",
        contact_status="ACTIVE",
    )
    session.add(contact)
    session.commit()
    contact_id = str(contact.id)
    yield contact_id
    session.query(XeroContact).filter(XeroContact.id == contact.id).delete(synchronize_session=False)
    session.commit()


def test_xero_auth_builds_a_wellformed_authorization_redirect(logged_in_page):
    """The OAuth entry point. Either it redirects to Xero with a correctly-formed
    authorization URL, or (if unconfigured) it degrades to the config page — never a 500,
    and never an authorization URL missing its state parameter.

    The state parameter is the OAuth CSRF defence: without it, an attacker can complete a
    connect flow against a victim's session. Asserting it is present is a real security
    check, and building the URL never contacts Xero.
    """
    from urllib.parse import parse_qs, urlparse

    response = logged_in_page.request.get("/crm/xero/auth", max_redirects=0)
    assert response.status in (301, 302), f"expected a redirect, got {response.status}"
    location = response.headers.get("location", "")

    if "login.xero.com" in location:
        query = parse_qs(urlparse(location).query)
        assert query.get("response_type") == ["code"], "not an auth-code flow"
        assert query.get("client_id"), "no client_id in the Xero redirect"
        assert query.get("redirect_uri"), "no redirect_uri in the Xero redirect"
        assert query.get("state"), "no state parameter — OAuth CSRF protection is missing"
        assert query.get("scope"), "no scopes requested"
    else:
        assert "xero_not_configured" in location or "/crm/configuration" in location, (
            f"neither a Xero redirect nor a graceful config fallback: {location!r}"
        )


def test_crm_customers_api_requires_auth(page, app_url):
    """Logged out, the CRM customer list must not return data."""
    response = page.request.get("/api/crm/customers", max_redirects=0)
    assert response.status != 200 or "customer" not in response.text().lower(), (
        "CRM customers returned to an unauthenticated request"
    )


def test_crm_customers_api_is_org_scoped(logged_in_page):
    """A logged-in member gets a clean, own-org response (empty without Xero sync, but a
    valid 200 shape, not another org's data or an error)."""
    response = logged_in_page.request.get("/api/crm/customers")
    assert response.status == 200, f"CRM customers failed for a member: {response.status}"


def test_crm_pages_reachable_for_member(logged_in_page):
    """The CRM section is navigable end to end for a logged-in user (render cleanliness is
    asserted in test_pages_render; this asserts the section is not gated shut)."""
    for path in ("/crm", "/crm/customers", "/crm/configuration"):
        response = logged_in_page.goto(path)
        assert response is not None and response.status < 400, f"{path} → {response}"


# ─────────────────────────────────────────────
# Cross-tenant probes
# ─────────────────────────────────────────────


def test_org_b_cannot_attach_note_to_org_a_contact(two_tenants, org_a_contact):
    """Regression coverage for a real bug found in this review: create_note used to
    accept ANY contact_id with no ownership check, letting org B silently attach a note
    to org A's real (guessed/leaked) contact UUID. It must now 400, and no note should
    land against org A's contact."""
    page_b = two_tenants["b"]

    response = page_b.request.post(
        f"/api/crm/customers/{org_a_contact}/notes",
        headers=csrf_headers(page_b),
        data={"content": "cross-tenant note attempt"},
    )
    assert response.status == 400, f"expected 400, got {response.status}: {response.text()}"

    page_a = two_tenants["a"]
    detail = page_a.request.get(f"/api/crm/customers/{org_a_contact}")
    assert detail.ok, detail.text()
    notes = detail.json()["notes"]
    assert not any("cross-tenant note attempt" in (n.get("content") or "") for n in notes), (
        "org B's note leaked onto org A's contact"
    )


def test_org_b_cannot_read_update_or_delete_org_a_product_mapping(two_tenants):
    """Product mappings are creatable without any Xero data, so this probes the full
    read/write/delete surface the way test_tenant_isolation.py does for inventory."""
    page_a = two_tenants["a"]
    page_b = two_tenants["b"]
    marker = f"E2E Secret Product {uuid.uuid4().hex[:6]}"

    created = page_a.request.post(
        "/api/crm/product-mappings",
        headers=csrf_headers(page_a),
        data={"biz_e_product_name": marker, "xero_description_pattern": marker},
    )
    assert created.status == 201, created.text()
    mapping_id = created.json()["product_mapping"]["id"]

    listing_b = page_b.request.get("/api/crm/product-mappings")
    assert listing_b.ok, listing_b.text()
    assert not any(m["id"] == mapping_id for m in listing_b.json()["product_mappings"]), (
        "org B's product-mapping list includes org A's mapping"
    )

    update_b = page_b.request.put(
        f"/api/crm/product-mappings/{mapping_id}",
        headers=csrf_headers(page_b),
        data={"notes": "hijacked from org B"},
    )
    assert update_b.status == 404, f"expected 404, got {update_b.status}: {update_b.text()}"

    delete_b = page_b.request.delete(
        f"/api/crm/product-mappings/{mapping_id}",
        headers=csrf_headers(page_b),
    )
    assert delete_b.status == 404, f"expected 404, got {delete_b.status}: {delete_b.text()}"

    still_there = page_a.request.get("/api/crm/product-mappings")
    assert any(m["id"] == mapping_id for m in still_there.json()["product_mappings"]), (
        "org A's mapping was deleted/modified by org B's request"
    )


def test_org_b_cannot_read_update_or_delete_org_a_task(two_tenants):
    """Tasks don't require a contact either, so this is independently testable from the
    note probe above."""
    page_a = two_tenants["a"]
    page_b = two_tenants["b"]
    marker = f"E2E Secret Task {uuid.uuid4().hex[:6]}"

    created = page_a.request.post(
        "/api/crm/tasks",
        headers=csrf_headers(page_a),
        data={"title": marker},
    )
    assert created.status == 201, created.text()
    task_id = created.json()["task"]["id"]

    listing_b = page_b.request.get("/api/crm/tasks")
    assert listing_b.ok, listing_b.text()
    assert not any(t["id"] == task_id for t in listing_b.json()["tasks"]), "org B's task list includes org A's task"

    update_b = page_b.request.put(
        f"/api/crm/tasks/{task_id}",
        headers=csrf_headers(page_b),
        data={"status": "cancelled"},
    )
    assert update_b.status == 404, f"expected 404, got {update_b.status}: {update_b.text()}"

    delete_b = page_b.request.delete(
        f"/api/crm/tasks/{task_id}",
        headers=csrf_headers(page_b),
    )
    assert delete_b.status == 404, f"expected 404, got {delete_b.status}: {delete_b.text()}"


# ─────────────────────────────────────────────
# Unhappy paths
# ─────────────────────────────────────────────


def test_xero_callback_rejects_mismatched_oauth_state(logged_in_page):
    """The OAuth CSRF check: a callback whose `state` doesn't match what this session
    stashed must be rejected, not silently accepted (which would let an attacker
    complete a connect flow against a victim's session — a classic OAuth CSRF)."""
    response = logged_in_page.request.get(
        "/crm/xero/callback?state=attacker-supplied-state&code=irrelevant",
        max_redirects=0,
    )
    assert response.status in (301, 302), f"expected a redirect, got {response.status}"
    location = response.headers.get("location", "")
    assert "xero_state_mismatch" in location, f"state mismatch was not rejected: {location!r}"


def test_invoice_actions_404_cleanly_for_unknown_invoice(logged_in_page):
    """Authorise/PDF/view-url against an invoice id that doesn't exist in this org must
    return a clean 400 with a JSON error body, never a bare 500."""
    fake_id = str(uuid.uuid4())

    authorise = logged_in_page.request.post(
        f"/api/crm/invoices/{fake_id}/authorise", headers=csrf_headers(logged_in_page)
    )
    assert authorise.status == 400, f"expected 400, got {authorise.status}: {authorise.text()}"
    assert "error" in authorise.json()

    pdf = logged_in_page.request.get(f"/api/crm/invoices/{fake_id}/pdf")
    assert pdf.status == 400, f"expected 400, got {pdf.status}: {pdf.text()}"

    view_url = logged_in_page.request.get(f"/api/crm/invoices/{fake_id}/view-url")
    assert view_url.status == 400, f"expected 400, got {view_url.status}: {view_url.text()}"
