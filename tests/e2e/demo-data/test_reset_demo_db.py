"""POST /api/core/reset-demo-db — the demo-data slice's one route.

Covers AC1 (authentication and CSRF required), AC3 (successful reset shape), and
regression coverage for security-audit F1: an authenticated caller outside the demo
organisation must never reset its data.

AC2 (environment gate) and AC4 (demo user missing) are not covered here — both require
booting the app with a different `config.environment` / DB state than this session's
`app_url` fixture provides (always local, demo user always present). See the report for
why those stay unit-test territory.
"""

import pytest

from tests.e2e.conftest import csrf_headers, login_through_ui

pytestmark = pytest.mark.e2e


def test_ac1_unauthenticated_reset_is_rejected(browser, app_url):
    """An anonymous reset receives the signed-out protected-write response."""
    context = browser.new_context(base_url=app_url, ignore_https_errors=True)
    page = context.new_page()
    try:
        resp = page.request.post("/api/core/reset-demo-db")
        assert resp.status == 401
        assert resp.json().get("code") == "signed_out"
        assert resp.json().get("error") == "Session expired or not authenticated"
    finally:
        context.close()


def test_demo_org_member_still_needs_csrf_to_reset(browser, app_url, demo_org_member):
    context = browser.new_context(base_url=app_url, ignore_https_errors=True)
    page = context.new_page()
    try:
        login_through_ui(page, demo_org_member["email"], demo_org_member["password"])
        before = page.request.get("/api/core/processes").json()["processes"]
        response = page.request.post("/api/core/reset-demo-db")
        assert response.status == 400
        assert response.json().get("code") == "csrf"
        assert "csrf" in response.text().lower()
        after = page.request.get("/api/core/processes").json()["processes"]
        assert {row["id"] for row in after} == {row["id"] for row in before}
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

    Pins the repaired F1 boundary: even with a valid CSRF token, the caller must
    belong to the demo organisation.
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
