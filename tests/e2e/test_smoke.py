"""Stage 0 proof: the harness genuinely drives the real app.

If this passes, the foundation is real — app boots over TLS, the browser trusts it, the
login flow works end to end, and the deterministic page checks are wired up.
"""

import re

import pytest
from playwright.sync_api import Page, expect

from tests.e2e.conftest import assert_clean_page, attach_probe

pytestmark = pytest.mark.e2e


def test_landing_page_renders_clean(page: Page, app_url: str):
    attach_probe(page)
    page.goto("/")
    expect(page.get_by_role("button", name="Sign In").first).to_be_visible()
    assert_clean_page(page)


def test_login_lands_on_dashboard(logged_in_page: Page):
    """/dashboard redirects to /core/dashboard (app.py:95) — assert where we land."""
    page = logged_in_page
    page.goto("/dashboard")
    expect(page).to_have_url(re.compile(r"/core/dashboard"))
    assert_clean_page(page)


def test_logged_out_user_cannot_reach_dashboard(page: Page, app_url: str):
    """Blocking-tier security check: a protected route must never serve content to an
    unauthenticated browser."""
    attach_probe(page)
    page.goto("/dashboard")
    assert not page.url.endswith("/dashboard"), "dashboard served to a logged-out browser"
