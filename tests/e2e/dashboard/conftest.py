"""Fixtures and seed helpers for the dashboard E2E suite (.agents/specs/dashboard.md).

Seeds through the real APIs the dashboard's own routes read from (inventory, processes,
executions, CRM tasks) via an authenticated `page.request` -- same cookies a real browser
session uses -- rather than writing rows directly, so every test proves the whole stack
(route -> repository -> org_id filter -> aggregation), not just the aggregation function.
"""

from __future__ import annotations

import pytest

from tests.e2e.conftest import csrf_headers, login_through_ui


@pytest.fixture()
def fresh_page(browser, app_url, fresh_user):
    """A single logged-in page in its own brand-new org.

    `logged_in_page` reuses the whole session's shared `e2e_user` org (every e2e file
    that authenticates that way writes into the same org across the run), so it cannot
    support an exact-count assertion like "a fresh org has 0 processes" -- another file's
    test may have already created one in the same org earlier in the session. Tests here
    that assert exact counts need real isolation; tests that only assert a value changed
    relative to itself can keep using `logged_in_page`.
    """
    user = fresh_user()
    context = browser.new_context(base_url=app_url, ignore_https_errors=True)
    page = context.new_page()
    login_through_ui(page, user["email"], user["password"])
    yield page
    context.close()


@pytest.fixture()
def two_tenants(browser, app_url, fresh_user):
    """Two orgs, each with its own authenticated browser page. Same shape as
    tests/e2e/test_tenant_isolation.py's fixture of the same name."""
    org_a, org_b = fresh_user(), fresh_user()
    contexts = []

    def _sign_in(user):
        context = browser.new_context(base_url=app_url, ignore_https_errors=True)
        contexts.append(context)
        page = context.new_page()
        login_through_ui(page, user["email"], user["password"])
        return page

    pages = {"a": _sign_in(org_a), "b": _sign_in(org_b)}
    yield pages
    for context in contexts:
        context.close()


def create_inventory_item(
    page,
    name: str,
    *,
    quantity: int = 5,
    unit: str = "kg",
    inventory_type: str = "raw_material",
    untracked: bool = False,
) -> str:
    payload = {"name": name, "quantity": quantity, "unit": unit, "inventory_type": inventory_type}
    if untracked:
        # The API requires notes to explain an untracked item -- see
        # tests/e2e/test_tenant_isolation.py's _create_untracked_item for the same shape.
        payload["untracked"] = True
        payload["notes"] = "dashboard e2e seed data"
    response = page.request.post("/api/core/inventory", headers=csrf_headers(page), data=payload)
    assert response.status == 201, f"seed inventory item failed: {response.status} {response.text()}"
    return response.json()["id"]


def create_process(page, name: str, *, is_draft: bool = True) -> str:
    resp = page.request.post(
        "/api/core/processes",
        headers=csrf_headers(page),
        data={"name": name, "category": "manufacturing", "is_draft": is_draft},
    )
    assert resp.status in (200, 201), f"create process failed: {resp.status} {resp.text()}"
    return resp.json()["id"]


def start_execution(page, process_id: str) -> str:
    """Starts an execution. `ExecutionRepository.create_execution` lands it in
    ExecutionStatus.IN_PROGRESS immediately (it briefly constructs the row as PENDING,
    then reassigns before commit -- see test_metrics_api.py's module docstring), so it
    counts as active under both /api/core/metrics' IN_PROGRESS-only definition and the
    dashboard summary's PENDING+IN_PROGRESS one."""
    resp = page.request.post("/api/core/executions", headers=csrf_headers(page), data={"process_id": process_id})
    assert resp.status in (200, 201), f"start execution failed: {resp.status} {resp.text()}"
    execution_id = resp.json().get("id")
    assert execution_id, f"no execution id: {resp.text()}"
    return execution_id


def create_crm_task(
    page,
    title: str,
    *,
    due_date: str | None = None,
    priority: str = "medium",
) -> str:
    """Create a CRM task via `POST /api/crm/tasks`. Requires `crm_enabled` (true in
    local.ini, the E2E boot's config), which the dashboard summary route reads to decide
    whether `tasks`/`sales` are the enabled or disabled shape."""
    payload: dict = {"title": title, "priority": priority}
    if due_date is not None:
        payload["due_date"] = due_date
    resp = page.request.post("/api/crm/tasks", headers=csrf_headers(page), data=payload)
    assert resp.status == 201, f"create CRM task failed: {resp.status} {resp.text()}"
    return resp.json()["task"]["id"]
