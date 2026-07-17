"""Regression tests for the two landing-page bugs Stage 0's clean-page checks found.

Both were silent: the app looked fine and every unit test passed. They are pinned here so
they cannot come back — see .agents/specs/playwright-e2e.md (F1, F2).
"""

import pytest
from playwright.sync_api import Page, expect

from tests.e2e.conftest import assert_clean_page, attach_probe

pytestmark = pytest.mark.e2e


# --------------------------------------------------------------------------------------
# F1: password-policy.js was @requires_auth, so the logged-out landing page got a 302 to
# "/" and text/html where it expected JavaScript. window.PasswordPolicy never existed, and
# landing.html's `if (window.PasswordPolicy)` guard hid that forever.
# --------------------------------------------------------------------------------------


def test_password_policy_script_is_served_to_anonymous_users(page: Page, app_url: str):
    response = page.request.get("/ui/shared/password-policy.js")
    assert response.status == 200, f"expected 200, got {response.status}"
    assert "javascript" in response.headers.get("content-type", ""), (
        f"served as {response.headers.get('content-type')!r} — the browser will refuse to execute it"
    )


def test_password_policy_is_usable_on_the_signup_form(page: Page, app_url: str):
    """The point of F1: signup gets live password guidance, not just a rejection later."""
    attach_probe(page)
    page.goto("/")
    assert page.evaluate("typeof window.PasswordPolicy") == "object", (
        "window.PasswordPolicy is undefined — the signup form's password warnings are dead"
    )
    assert_clean_page(page)


def test_gated_shared_assets_still_require_auth(page: Page, app_url: str):
    """The allowlist must not have opened the whole directory.

    Guards the actual risk of F1's fix: a blanket exemption would expose every shared
    asset. Anonymous access to a non-allowlisted file must not return its contents.
    """
    for gated in ("account-info.js", "workflow-engine-settings.js", "sidebar.js"):
        response = page.request.get(f"/ui/shared/{gated}", max_redirects=0)
        assert response.status != 200, f"{gated} is being served to anonymous users"


# --------------------------------------------------------------------------------------
# F2: openModal ran a *full* reset on a timer after the modal was visible (50ms login,
# 100ms/300ms signup), wiping anything typed or autofilled in that window.
# --------------------------------------------------------------------------------------


def test_login_modal_keeps_credentials_typed_immediately(page: Page, app_url: str):
    """Types instantly, like a password manager does, then waits out every old timer."""
    page.goto("/")
    page.get_by_role("button", name="Sign In").first.click()

    email = page.locator("#login-email")
    password = page.locator("#login-password")
    expect(email).to_be_visible()
    email.fill("someone@example.test")
    password.fill("Test-Passw0rd!1")

    page.wait_for_timeout(400)  # outlast the old 50ms reset

    expect(email).to_have_value("someone@example.test")
    expect(password).to_have_value("Test-Passw0rd!1")


def test_signup_modal_keeps_input_typed_immediately(page: Page, app_url: str):
    page.goto("/")
    page.get_by_role("button", name="Sign Up").first.click()

    org = page.locator("#signup-org-name")
    email = page.locator("#signup-email")
    expect(org).to_be_visible()
    org.fill("Whistlebird Distillery")
    email.fill("founder@example.test")

    page.wait_for_timeout(500)  # outlast the old 100ms AND 300ms resets

    expect(org).to_have_value("Whistlebird Distillery")
    expect(email).to_have_value("founder@example.test")


def test_login_modal_still_resets_stale_state_on_reopen(page: Page, app_url: str):
    """The timers exist to kill stuck 2FA state — that must still work after the split."""
    page.goto("/")
    page.get_by_role("button", name="Sign In").first.click()
    expect(page.locator("#login-email")).to_be_visible()

    # Force the modal into 2FA mode and a stale error, as a failed attempt would.
    page.evaluate("""
        document.getElementById('login-2fa-section').setAttribute('data-mode', 'visible');
        document.getElementById('login-2fa-section').style.display = 'block';
        const err = document.getElementById('login-error');
        err.textContent = 'stale error';
        err.style.display = 'block';
    """)

    page.locator("#loginModal .btn-ghost").first.click()
    page.get_by_role("button", name="Sign In").first.click()
    page.wait_for_timeout(400)

    assert page.locator("#login-2fa-section").get_attribute("data-mode") == "hidden", (
        "reopening the modal left it stuck in 2FA mode"
    )
    expect(page.locator("#login-error")).not_to_be_visible()
