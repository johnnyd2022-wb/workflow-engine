"""Fixtures for the industry process templates E2E suite (.agents/specs/process_templates.md).

Enables Compliant on a fresh org through the real API (`PUT /api/compliant/profile`, the
same route the Compliant settings page calls) rather than writing the `ComplianceProfile`
row directly, so every test proves the whole stack (route -> service -> ComplianceProfile
-> catalogue policy), not just the registry function. Matches the "seed through real APIs"
convention in tests/e2e/dashboard/conftest.py.
"""

from __future__ import annotations

import pytest

from app.core.db.models.user import UserRole
from tests.e2e.conftest import attach_probe, csrf_headers, login_through_ui


def _enable_compliant(page) -> None:
    resp = page.request.put(
        "/api/compliant/profile",
        headers=csrf_headers(page),
        data={"enabled": True, "industry_module": "nz_alcohol"},
    )
    assert resp.status == 200, f"could not enable Compliant: {resp.status} {resp.text()}"


@pytest.fixture()
def compliant_page(browser, app_url, fresh_user):
    """A logged-in page in its own fresh org with Compliant + nz_alcohol enabled."""
    user = fresh_user(role=UserRole.ADMIN)  # PUT /api/compliant/profile requires ADMIN
    context = browser.new_context(base_url=app_url, ignore_https_errors=True)
    page = context.new_page()
    attach_probe(page)
    login_through_ui(page, user["email"], user["password"])
    _enable_compliant(page)
    yield page
    context.close()


@pytest.fixture()
def no_compliant_page(browser, app_url, fresh_user):
    """A logged-in page in its own fresh org with NO Compliant profile at all (AC2/AC3)."""
    user = fresh_user()
    context = browser.new_context(base_url=app_url, ignore_https_errors=True)
    page = context.new_page()
    attach_probe(page)
    login_through_ui(page, user["email"], user["password"])
    yield page
    context.close()
