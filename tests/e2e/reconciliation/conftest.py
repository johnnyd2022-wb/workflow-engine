"""E2E fixtures for the reconciliation slice (.agents/specs/reconciliation.md).

Reuses the app-wide E2E scaffolding (tests/e2e/conftest.py: csrf_headers,
login_through_ui) and the shared two-org/two-user tenant world
(tests/conftest.py: two_org_two_user, owned by the test-fixtures skill) rather than
hand-seeding either — AC8 (tenant isolation) is the primary target of this suite and
needs exactly the "hostile neighbor org" shape that fixture already provides.
"""

from __future__ import annotations

import pytest

from tests.e2e.conftest import csrf_headers, login_through_ui, purge_org
from tests.factories import DEFAULT_TEST_PASSWORD


def create_process(page, name: str, is_draft: bool = False) -> str:
    resp = page.request.post(
        "/api/core/processes",
        headers=csrf_headers(page),
        data={"name": name, "category": "manufacturing", "is_draft": is_draft},
    )
    assert resp.status in (200, 201), f"create process failed: {resp.status} {resp.text()}"
    pid = resp.json().get("id")
    assert pid, f"no id in create response: {resp.text()}"
    return pid


def add_step(page, process_id: str, step_number: int, name: str) -> str:
    resp = page.request.post(
        f"/api/core/processes/{process_id}/steps",
        headers=csrf_headers(page),
        data={"step_number": step_number, "name": name},
    )
    assert resp.status in (200, 201), f"add step failed: {resp.status} {resp.text()}"
    sid = resp.json().get("id")
    assert sid, f"no id in add-step response: {resp.text()}"
    return sid


def create_untracked_item(page, name: str, quantity, unit: str, notes: str = "found during stocktake") -> str:
    """An untracked InventoryItem via the real add-inventory route (backend.py:3599).

    extra_data.untracked=true is only set server-side when the caller marks the addition
    `untracked` and supplies non-empty `notes` — this goes through that same real path
    (the "log untracked stock" flow a human uses), not a database shortcut.
    """
    resp = page.request.post(
        "/api/core/inventory",
        headers=csrf_headers(page),
        data={
            "name": name,
            "quantity": quantity,
            "unit": unit,
            "inventory_type": "raw_material",
            "untracked": True,
            "notes": notes,
        },
    )
    assert resp.status in (200, 201), f"create untracked item failed: {resp.status} {resp.text()}"
    body = resp.json()
    item_id = body.get("id") or body.get("item", {}).get("id")
    assert item_id, f"no id in untracked-item create response: {resp.text()}"
    return item_id


@pytest.fixture()
def two_org_sessions(db, browser, app_url, two_org_two_user):
    """Two authenticated browser contexts, signed in as the shared two_org_two_user
    world's user_a (org_a) and user_b (org_b) — the hostile-neighbor world AC8's
    cross-tenant probes need, reused rather than reseeded per test (test-fixtures skill).

    two_org_two_user's own teardown (tests/conftest.py) deletes org_a/org_b's users then
    orgs directly and was written for API-only tests with no real login; a real browser
    login through login_through_ui writes an audit_logs row referencing the user, so that
    plain delete hits a foreign-key violation the moment a test here actually signs in.
    Running purge_org (the same FK-safe, schema-walking cleanup tests/e2e/conftest.py
    already uses for fresh_user/e2e_user) here first empties both orgs before
    two_org_two_user's own teardown runs, so that teardown's delete matches zero rows
    instead of failing.
    """
    org_a = two_org_two_user["org_a"]
    org_b = two_org_two_user["org_b"]
    user_a = two_org_two_user["user_a"]
    user_b = two_org_two_user["user_b"]
    contexts = []

    def _sign_in(user):
        context = browser.new_context(base_url=app_url, ignore_https_errors=True)
        contexts.append(context)
        page = context.new_page()
        login_through_ui(page, user.email, DEFAULT_TEST_PASSWORD)
        return page

    pages = {"a": _sign_in(user_a), "b": _sign_in(user_b)}
    yield pages
    for context in contexts:
        context.close()
    db.rollback()
    purge_org(db, org_a.id, user_a.id)
    purge_org(db, org_b.id, user_b.id)
