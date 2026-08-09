"""Fixtures for the activity-log E2E suite.

Seeds data through the real `POST /api/core/inventory` route (via an authenticated
`page.request`, same cookies the real browser session uses) rather than a DAG helper --
this slice's own routes never touch Process/Step, so there is no need for
`build_linear_dag`/`two_tenants_with_chains` (which currently fail on this shared test DB
against a `steps.org_id` NOT NULL constraint picked up from a concurrent worktree's
in-flight migration -- unrelated to this slice, see the header note in
tests/test_activity_log.py).
"""

from __future__ import annotations

import pytest

from tests.e2e.conftest import csrf_headers, login_through_ui


@pytest.fixture()
def logged_in_two_orgs(browser, app_url, fresh_user):
    """Two orgs, each with its own logged-in browser page. The cross-tenant twin used by
    this suite's tenant-isolation probes -- org B's authenticated `page.request` reaches
    for org A's ids, using real session cookies, not a bypass."""

    def _build():
        user = fresh_user()
        context = browser.new_context(base_url=app_url, ignore_https_errors=True)
        page = context.new_page()
        login_through_ui(page, user["email"], user["password"])
        return {"user": user, "page": page, "context": context}

    org_a = _build()
    org_b = _build()
    try:
        yield {"a": org_a, "b": org_b}
    finally:
        org_a["context"].close()
        org_b["context"].close()


def create_inventory_item(page, *, name: str, quantity: str = "5", unit: str = "kg") -> str:
    """Create a real inventory item through the API, in the given page's own org, and
    return its id. This is the same route the Add Item UI calls."""
    resp = page.request.post(
        "/api/core/inventory",
        headers=csrf_headers(page),
        data={"name": name, "quantity": quantity, "unit": unit, "inventory_type": "raw_material"},
    )
    assert resp.status == 201, f"seed item creation failed: {resp.status} {resp.text()}"
    return resp.json()["id"]
