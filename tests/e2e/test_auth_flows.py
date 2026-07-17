"""Stage 1: auth and 2FA, driven through the real browser.

Spec: .agents/specs/playwright-e2e.md. Unit tests already cover these endpoints; what
they cannot cover is whether a human can actually get through the front door — the
landing modal, its JS, and the session it produces.
"""

import re
import time
import uuid

import pyotp
import pytest
from playwright.sync_api import Page, expect

from tests.e2e.conftest import assert_clean_page, attach_probe, login_through_ui

pytestmark = pytest.mark.e2e

STRONG_PASSWORD = "Test-Passw0rd!1"


def _two_tokens(secret: str) -> tuple[str, str]:
    """Two consecutive, different TOTP codes — /auth/2fa/enable requires both.

    Same approach as tests/test_2fa_totp_optimized.py: walk the time window rather than
    sleep 30s.
    """
    totp = pyotp.TOTP(secret)
    now = int(time.time())
    token1 = totp.at(now)
    token2 = totp.at(now + 30)
    if token1 == token2:
        token2 = totp.at(now + 60)
    return token1, token2


# --------------------------------------------------------------------------------------
# Signup
# --------------------------------------------------------------------------------------


def test_signup_creates_org_and_signs_in(page: Page, app_url: str, purge_after):
    attach_probe(page)
    run_id = uuid.uuid4().hex[:8]
    email = f"e2e-signup-{run_id}@example.test"

    page.goto("/")
    page.get_by_role("button", name="Sign Up").first.click()
    expect(page.locator("#signup-org-name")).to_be_visible()

    page.locator("#signup-org-name").fill(f"E2E Signup Org {run_id}")
    page.locator("#signup-email").fill(email)
    page.locator("#signup-password").fill(STRONG_PASSWORD)
    page.locator("#signup-password-confirm").fill(STRONG_PASSWORD)

    purge_after(email)
    page.locator("#signupForm button[type=submit]").click()

    page.wait_for_url(re.compile(r"/(core/)?dashboard"), timeout=15_000)
    assert_clean_page(page)


def test_signup_rejects_mismatched_password_confirmation(page: Page, app_url: str):
    """Unhappy path: no account is created and the user is told why."""
    run_id = uuid.uuid4().hex[:8]
    page.goto("/")
    page.get_by_role("button", name="Sign Up").first.click()
    expect(page.locator("#signup-org-name")).to_be_visible()

    page.locator("#signup-org-name").fill(f"E2E Reject Org {run_id}")
    page.locator("#signup-email").fill(f"e2e-reject-{run_id}@example.test")
    page.locator("#signup-password").fill(STRONG_PASSWORD)
    page.locator("#signup-password-confirm").fill("Different-Passw0rd!2")
    page.locator("#signupForm button[type=submit]").click()

    expect(page.locator("#signup-error")).to_be_visible()
    assert not re.search(r"/(core/)?dashboard", page.url), "signed in despite mismatch"


# --------------------------------------------------------------------------------------
# Login
# --------------------------------------------------------------------------------------


def test_login_with_wrong_password_shows_error_and_no_session(page: Page, app_url: str, e2e_user: dict):
    page.goto("/")
    page.get_by_role("button", name="Sign In").first.click()
    expect(page.locator("#login-email")).to_be_visible()
    page.locator("#login-email").fill(e2e_user["email"])
    page.locator("#login-password").fill("Wrong-Passw0rd!9")
    page.locator("#login-submit-btn").click()

    expect(page.locator("#login-error")).to_be_visible()

    # The real assertion: no session was created.
    page.goto("/dashboard")
    assert not re.search(r"/(core/)?dashboard", page.url), "a failed login produced a session"


def test_logout_ends_the_session(logged_in_page: Page):
    page = logged_in_page
    page.goto("/core/dashboard")
    response = page.request.post("/auth/logout")
    assert response.status in (200, 204), f"logout returned {response.status}"

    page.goto("/dashboard")
    assert not re.search(r"/(core/)?dashboard", page.url), "still authenticated after logout"


# --------------------------------------------------------------------------------------
# 2FA
# --------------------------------------------------------------------------------------


def test_2fa_enroll_enable_then_login_requires_a_code(page: Page, app_url: str, fresh_user):
    """The whole 2FA lifecycle through the UI, which is where it actually matters."""
    user = fresh_user()
    attach_probe(page)

    login_through_ui(page, user["email"], user["password"])

    enroll = page.request.post("/auth/2fa/enroll")
    assert enroll.status == 200, f"enroll failed: {enroll.status} {enroll.text()}"
    secret = enroll.json()["secret"]

    token1, token2 = _two_tokens(secret)
    enable = page.request.post("/auth/2fa/enable", data={"token1": token1, "token2": token2})
    assert enable.status == 200, f"enable failed: {enable.status} {enable.text()}"

    page.request.post("/auth/logout")
    page.context.clear_cookies()

    # Logging in now must stop at the 2FA gate rather than handing over a session.
    page.goto("/")
    page.get_by_role("button", name="Sign In").first.click()
    expect(page.locator("#login-email")).to_be_visible()
    page.locator("#login-email").fill(user["email"])
    page.locator("#login-password").fill(user["password"])
    page.locator("#login-submit-btn").click()

    two_fa = page.locator("#login-2fa-section")
    expect(two_fa).to_be_visible()
    assert two_fa.get_attribute("data-mode") == "visible"
    assert not re.search(r"/(core/)?dashboard", page.url), "2FA was bypassed entirely"

    # A wrong code must not get in.
    page.locator("#login-2fa-code").fill("000000")
    page.locator("#login-submit-btn").click()
    expect(page.locator("#login-error")).to_be_visible()
    assert not re.search(r"/(core/)?dashboard", page.url), "wrong 2FA code was accepted"

    # The right code must.
    page.locator("#login-2fa-code").fill(pyotp.TOTP(secret).now())
    page.locator("#login-submit-btn").click()
    page.wait_for_url(re.compile(r"/(core/)?dashboard"), timeout=15_000)
    assert_clean_page(page)


def test_2fa_can_be_disabled_and_login_returns_to_one_step(page: Page, app_url: str, fresh_user):
    user = fresh_user()
    login_through_ui(page, user["email"], user["password"])

    secret = page.request.post("/auth/2fa/enroll").json()["secret"]
    token1, token2 = _two_tokens(secret)
    page.request.post("/auth/2fa/enable", data={"token1": token1, "token2": token2})

    disable = page.request.post(
        "/auth/2fa/disable", data={"password": user["password"], "token": pyotp.TOTP(secret).now()}
    )
    assert disable.status == 200, f"disable failed: {disable.status} {disable.text()}"

    page.request.post("/auth/logout")
    page.context.clear_cookies()

    login_through_ui(page, user["email"], user["password"])  # no 2FA step; passes or times out


# --------------------------------------------------------------------------------------
# Password change
# --------------------------------------------------------------------------------------


def test_change_password_invalidates_the_old_one(page: Page, app_url: str, fresh_user):
    user = fresh_user()
    new_password = "Rotated-Passw0rd!7"
    login_through_ui(page, user["email"], user["password"])

    response = page.request.post(
        "/auth/change-password",
        data={
            "current_password": user["password"],
            "new_password": new_password,
            "new_password_confirm": new_password,
        },
    )
    assert response.status == 200, f"change-password failed: {response.status} {response.text()}"

    page.request.post("/auth/logout")
    page.context.clear_cookies()

    # Old password must be dead.
    page.goto("/")
    page.get_by_role("button", name="Sign In").first.click()
    expect(page.locator("#login-email")).to_be_visible()
    page.locator("#login-email").fill(user["email"])
    page.locator("#login-password").fill(user["password"])
    page.locator("#login-submit-btn").click()
    expect(page.locator("#login-error")).to_be_visible()

    # New password must work.
    page.context.clear_cookies()
    login_through_ui(page, user["email"], new_password)
