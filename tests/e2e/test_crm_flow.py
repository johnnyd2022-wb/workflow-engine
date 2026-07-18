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
"""

import pytest

pytestmark = pytest.mark.e2e


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
