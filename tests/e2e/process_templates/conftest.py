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


def _grant_compliant(org_id) -> None:
    """`/api/compliant/*` is gated on an active per-org `compliant` subscription
    (spec compliant_tools.md); seed it before enabling the profile below."""
    from app.core.db import db_session
    from app.core.db.repositories.feature_subscription_repo import FeatureSubscriptionRepository

    FeatureSubscriptionRepository(db_session()).grant(org_id, "compliant")
    db_session().commit()


def _enable_compliant(page) -> None:
    resp = page.request.put(
        "/api/compliant/profile",
        headers=csrf_headers(page),
        data={"enabled": True, "industry_module": "nz_alcohol"},
    )
    assert resp.status == 200, f"could not enable Compliant: {resp.status} {resp.text()}"


def _settle_dashboard(page) -> None:
    """Let the post-login dashboard's own background fetches finish before a test
    navigates away.

    `login_through_ui` returns as soon as the URL becomes `/dashboard`, but
    `dashboard.js` kicks off `getDashboardSummary`/`getSystemFindings` fetches
    asynchronously after that. Chromium's `fetch()` rejects an in-flight request cancelled
    by navigation with a plain `TypeError: Failed to fetch` — indistinguishable, from
    `core-api.js`'s catch block, from a real network failure (no `AbortError`, since that
    name is reserved for explicit `AbortController` cancellation) — so it logs a console
    error `assert_clean_page` then treats as a genuine app fault. Waiting for network idle
    here (test-side; `app/core/frontend/js/core-api.js` is shared infra well outside this
    feature's blueprint) lets those fetches resolve before the fixture yields.
    """
    page.wait_for_load_state("networkidle")


@pytest.fixture()
def compliant_page(browser, app_url, fresh_user):
    """A logged-in page in its own fresh org with Compliant + nz_alcohol enabled."""
    user = fresh_user(role=UserRole.ADMIN)  # PUT /api/compliant/profile requires ADMIN
    _grant_compliant(user["org_id"])
    context = browser.new_context(base_url=app_url, ignore_https_errors=True)
    page = context.new_page()
    attach_probe(page)
    login_through_ui(page, user["email"], user["password"])
    _settle_dashboard(page)
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
    _settle_dashboard(page)
    yield page
    context.close()


@pytest.fixture()
def cross_tenant_pages(browser, app_url, fresh_user):
    """Org A (Compliant + nz_alcohol enabled, can copy templates) and Org B (plain,
    unrelated org) -- the AC7 hostile-neighbour probe: org B must never reach a process
    that org A created by copying a template.

    Org B does not need Compliant enabled -- the isolation this probes is
    `ProcessRepository`'s own org filter, not the catalogue's capability gate.
    """
    user_a = fresh_user(role=UserRole.ADMIN)  # PUT /api/compliant/profile requires ADMIN
    _grant_compliant(user_a["org_id"])
    user_b = fresh_user()
    contexts = []

    def _sign_in(user):
        context = browser.new_context(base_url=app_url, ignore_https_errors=True)
        contexts.append(context)
        page = context.new_page()
        attach_probe(page)
        login_through_ui(page, user["email"], user["password"])
        _settle_dashboard(page)
        return page

    page_a = _sign_in(user_a)
    _enable_compliant(page_a)
    page_b = _sign_in(user_b)

    yield {"a": page_a, "b": page_b}
    for context in contexts:
        context.close()
