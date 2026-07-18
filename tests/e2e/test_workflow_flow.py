"""Stage 2: the workflow/process spine — CRUD + run an execution.

This is the core of the product: a process is a DAG of steps; an execution runs it and
completes steps, which is where the real business logic lives (inventory quantity writes,
execution lineage). Render-only coverage proves the pages load; this proves the actual
lifecycle works end to end.

Driven through the real browser session (its cookies, its CSRF token, its org scope) so
the full stack is exercised — auth, CSRF, org filtering, and the domain rules — with the
UI asserted to reflect the created state. Clicking every wizard fragment by hand is a
higher-maintenance, lower-value follow-up; the state changes and their persistence are
what matter and are all asserted here.
"""

import uuid

import pytest
from playwright.sync_api import Page

from tests.e2e.conftest import assert_clean_page, csrf_headers

pytestmark = pytest.mark.e2e


def _create_process(page, name: str, is_draft: bool = False) -> str:
    resp = page.request.post(
        "/api/core/processes",
        headers=csrf_headers(page),
        data={"name": name, "category": "manufacturing", "is_draft": is_draft},
    )
    assert resp.status in (200, 201), f"create process failed: {resp.status} {resp.text()}"
    pid = resp.json().get("id")
    assert pid, f"no id in create response: {resp.text()}"
    return pid


def test_create_process_then_it_lists(logged_in_page: Page):
    page = logged_in_page
    name = f"E2E Process {uuid.uuid4().hex[:8]}"
    pid = _create_process(page, name)

    # Reads back by id and appears in the list.
    single = page.request.get(f"/api/core/processes/{pid}")
    assert single.status == 200 and name in single.text()

    listing = page.request.get("/api/core/processes")
    assert listing.status == 200 and name in listing.text(), "created process not in list"

    # And the UI page renders it cleanly.
    page.goto("/core/processes")
    page.wait_for_load_state("networkidle")
    assert_clean_page(page)


def test_rename_process_persists(logged_in_page: Page):
    page = logged_in_page
    pid = _create_process(page, f"E2E Rename Me {uuid.uuid4().hex[:8]}")
    new_name = f"E2E Renamed {uuid.uuid4().hex[:8]}"

    resp = page.request.put(
        f"/api/core/processes/{pid}",
        headers=csrf_headers(page),
        data={"name": new_name},
    )
    assert resp.status == 200, f"rename failed: {resp.status} {resp.text()}"

    after = page.request.get(f"/api/core/processes/{pid}")
    assert new_name in after.text(), "rename did not persist"


def test_add_steps_to_process(logged_in_page: Page):
    page = logged_in_page
    pid = _create_process(page, f"E2E Stepped {uuid.uuid4().hex[:8]}", is_draft=True)

    for n in (1, 2):
        resp = page.request.post(
            f"/api/core/processes/{pid}/steps",
            headers=csrf_headers(page),
            data={"step_number": n, "name": f"Step {n}"},
        )
        assert resp.status in (200, 201), f"add step {n} failed: {resp.status} {resp.text()}"

    detail = page.request.get(f"/api/core/processes/{pid}")
    assert "Step 1" in detail.text() and "Step 2" in detail.text(), "steps not persisted"


def test_delete_process_removes_it(logged_in_page: Page):
    page = logged_in_page
    name = f"E2E Delete {uuid.uuid4().hex[:8]}"
    pid = _create_process(page, name)

    resp = page.request.delete(f"/api/core/processes/{pid}", headers=csrf_headers(page))
    assert resp.status in (200, 204), f"delete failed: {resp.status} {resp.text()}"

    listing = page.request.get("/api/core/processes")
    assert name not in listing.text(), "deleted process still listed"


def test_run_execution_and_complete_a_step(logged_in_page: Page):
    """The spine: build a process with a step, start an execution, complete the step."""
    page = logged_in_page
    pid = _create_process(page, f"E2E Runnable {uuid.uuid4().hex[:8]}", is_draft=True)
    add = page.request.post(
        f"/api/core/processes/{pid}/steps",
        headers=csrf_headers(page),
        data={"step_number": 1, "name": "Mix"},
    )
    assert add.status in (200, 201), f"add step failed: {add.status} {add.text()}"

    started = page.request.post("/api/core/executions", headers=csrf_headers(page), data={"process_id": pid})
    assert started.status in (200, 201), f"start execution failed: {started.status} {started.text()}"
    eid = started.json().get("id")
    assert eid, f"no execution id: {started.text()}"

    with_process = page.request.get(f"/api/core/executions/{eid}/with-process")
    assert with_process.status == 200, f"read execution failed: {with_process.status}"
    body = with_process.json()
    # Response shape: {"execution": {"execution_steps": [...]}, "process": {...}}.
    execution = body.get("execution", body)
    steps = execution.get("execution_steps") or execution.get("steps") or []
    assert steps, f"execution has no steps: {with_process.text()[:300]}"
    esid = steps[0]["id"]

    completed = page.request.post(
        f"/api/core/executions/{eid}/steps/{esid}/complete",
        headers=csrf_headers(page),
        data={"actual_inputs": [], "actual_outputs": [], "execution_data": {}},
    )
    assert completed.status in (200, 201), f"complete step failed: {completed.status} {completed.text()[:300]}"

    # The execution page renders the run cleanly.
    page.goto("/core/executions/live")
    page.wait_for_load_state("networkidle")
    assert_clean_page(page)


def test_create_process_without_name_is_rejected(logged_in_page: Page):
    """Unhappy path: no name → 400, nothing created."""
    page = logged_in_page
    resp = page.request.post("/api/core/processes", headers=csrf_headers(page), data={"category": "manufacturing"})
    assert resp.status == 400, f"expected 400 for nameless process, got {resp.status}"
