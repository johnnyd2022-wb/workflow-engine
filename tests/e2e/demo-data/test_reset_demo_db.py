"""POST /api/core/reset-demo-db — the demo-data slice's one route.

Covers .agents/specs/demo-data.md AC1 (auth required — observable as 400, see below),
AC3 (successful reset shape),
and the mandatory cross-tenant probe. The cross-tenant probe asserts the SECURE outcome
(403 for a caller outside the demo org) — per security-audit F1
(.agents/reports/demo-data/security-audit.md), the route currently checks only
@requires_auth with no caller-identity/org check, so this test is expected to be RED
against unpatched code and green once F1 is fixed. That is deliberate: e2e tests are
ground truth, not a report card massaged to pass.

AC2 (environment gate) and AC4 (demo user missing) are not covered here — both require
booting the app with a different `config.environment` / DB state than this session's
`app_url` fixture provides (always local, demo user always present). See the report for
why those stay unit-test territory.
"""

import pytest

from tests.e2e.conftest import csrf_headers, login_through_ui

pytestmark = pytest.mark.e2e


def test_ac1_unauthenticated_reset_is_rejected(browser, app_url):
    """An anonymous caller cannot succeed — but the observable status is 400
    (CSRF token missing), not 401. Flask-WTF's CSRFProtect runs as a global
    before_request hook that fires before any route's @requires_auth check, and only
    the authenticated SPA shell (base_spa.html) embeds a csrf-token meta tag — there is
    no public page an anonymous visitor can use to obtain one. This is true of every
    state-changing POST/PUT/PATCH/DELETE route in the app, not specific to demo-data;
    a clean 401-before-CSRF case is not reachable over real HTTP for this route."""
    context = browser.new_context(base_url=app_url, ignore_https_errors=True)
    page = context.new_page()
    try:
        resp = page.request.post("/api/core/reset-demo-db")
        assert resp.status == 400
        assert "csrf" in resp.text().lower()
    finally:
        context.close()


def test_ac3_demo_org_member_can_reset_and_reseed(browser, app_url, demo_org_member):
    """A user who belongs to the demo org resets it and gets the distillery fixture back."""
    context = browser.new_context(base_url=app_url, ignore_https_errors=True)
    page = context.new_page()
    try:
        login_through_ui(page, demo_org_member["email"], demo_org_member["password"])

        resp = page.request.post("/api/core/reset-demo-db", headers=csrf_headers(page))
        assert resp.status == 200, resp.text()
        body = resp.json()
        assert body.get("success") is True, body

        processes = page.request.get("/api/core/processes").json()["processes"]
        names = [p["name"] for p in processes]
        assert "Distillery Spirit Production" in names, names

        items = page.request.get("/api/core/inventory").json()["inventory_items"]
        expired = [i for i in items if i.get("name") == "Yeast" and i.get("expiry_date")]
        assert expired, f"expected an expired Yeast raw material for check-needed, got: {items}"
        assert expired[0]["expiry_date"] < __import__("datetime").date.today().isoformat()
    finally:
        context.close()


def test_cross_tenant_reset_is_rejected(browser, app_url, fresh_user):
    """The mandatory cross-tenant probe (e2e-playwright skill, §1): a user outside the
    demo org must not be able to trigger a reset of the demo org's data.

    Expected to FAIL today — see module docstring and security-audit F1. A caller from
    any org currently gets 200/success because the route never checks the caller's
    identity against the demo org it always targets.
    """
    outsider = fresh_user()
    context = browser.new_context(base_url=app_url, ignore_https_errors=True)
    page = context.new_page()
    try:
        login_through_ui(page, outsider["email"], outsider["password"])
        resp = page.request.post("/api/core/reset-demo-db", headers=csrf_headers(page))
        assert resp.status == 403, (
            f"caller outside the demo org got {resp.status} {resp.text()!r} — "
            "any authenticated user of any org can reset the demo org's data (F1)"
        )
    finally:
        context.close()
