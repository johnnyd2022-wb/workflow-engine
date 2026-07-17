"""Stage 4 blocking-tier security checks: headers, cookie flags, CSRF.

These are deterministic and cheap, and they protect controls that are invisible until the
day they regress. A dropped Secure flag or a CSP that quietly stopped being sent does not
fail any functional test — the app works fine — right up until it is the story in a
breach report. Pinned here so a regression fails the push instead.
"""

import pytest

pytestmark = pytest.mark.e2e


def test_security_headers_present_on_landing(page, app_url):
    response = page.request.get("/")
    headers = {k.lower(): v for k, v in response.headers.items()}

    assert headers.get("x-content-type-options") == "nosniff"
    assert "content-security-policy" in headers, "no CSP on the public landing page"
    assert headers.get("x-frame-options") in ("SAMEORIGIN", "DENY")


def test_hsts_present_over_https(page, app_url):
    """HSTS is only emitted on secure requests; the E2E boot is real TLS, so it must be
    here. If this fails, browsers are not being told to stay on HTTPS."""
    response = page.request.get("/")
    headers = {k.lower(): v for k, v in response.headers.items()}
    hsts = headers.get("strict-transport-security", "")
    assert "max-age=" in hsts, f"no HSTS over HTTPS: {hsts!r}"
    assert int(hsts.split("max-age=")[1].split(";")[0]) >= 15_552_000, "HSTS max-age too short"


def test_session_cookie_flags(logged_in_page):
    """Secure + HttpOnly + SameSite on the session cookie. A missing HttpOnly makes the
    session stealable by any XSS; a missing Secure lets it leak over plain HTTP."""
    cookies = logged_in_page.context.cookies()
    session_cookies = [c for c in cookies if "session" in c["name"].lower()]
    assert session_cookies, f"no session cookie found among {[c['name'] for c in cookies]}"

    for cookie in session_cookies:
        assert cookie["httpOnly"], f"{cookie['name']} is not HttpOnly — stealable via XSS"
        assert cookie["secure"], f"{cookie['name']} is not Secure — leaks over HTTP"
        assert cookie.get("sameSite") in ("Lax", "Strict"), (
            f"{cookie['name']} SameSite is {cookie.get('sameSite')!r} — CSRF exposure"
        )


def test_mutating_request_without_csrf_token_is_rejected(logged_in_page):
    """The CSRF control itself. A state-changing POST with a valid session but no
    X-CSRFToken must be refused."""
    logged_in_page.goto("/core/dashboard")
    response = logged_in_page.request.post(
        "/api/core/inventory",
        headers={"Referer": logged_in_page.url},
        data={"name": "csrf probe", "quantity": 1, "unit": "kg"},
    )
    assert response.status in (400, 403), f"mutating request without a CSRF token was accepted: {response.status}"


def test_js_asset_served_with_correct_mime_type(page, app_url):
    """Guards the F1 class of bug generally: a script served as text/html is refused by
    the browser under nosniff, and every feature that script powers dies silently."""
    response = page.request.get("/ui/shared/password-policy.js")
    assert response.status == 200
    content_type = response.headers.get("content-type", "")
    assert "javascript" in content_type, f"JS served as {content_type!r}"
