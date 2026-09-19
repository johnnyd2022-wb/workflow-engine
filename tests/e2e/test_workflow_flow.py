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

from tests.e2e.conftest import assert_clean_page, csrf_headers, login_through_ui

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


def test_workflow_directory_filters_and_keeps_history_as_a_separate_action(logged_in_page: Page):
    """The operational directory stays usable with a long imported workflow list.

    A workflow row is deliberately two independent controls: opening its workspace and
    opening its audit history. Browsers handle a button inside a link inconsistently, so
    assert the DOM contract as well as both user-facing actions.
    """
    page = logged_in_page
    name = f"E2E Directory Needle {uuid.uuid4().hex[:8]}"
    pid = _create_process(page, name)
    _create_process(page, f"E2E Directory Other {uuid.uuid4().hex[:8]}")

    # Follow the dashboard's operational CTA through the SPA, rather than only proving
    # a hard navigation. The directory search must bind to the freshly swapped markup.
    page.goto("/core/dashboard")
    page.locator('a[href="/core/processes"]').click()
    page.wait_for_url("**/core/processes")
    page.wait_for_selector(".processes-list-item")
    search = page.locator("#processes-list-search")
    search.fill(name)

    matching_row = page.locator(".processes-list-item").filter(has_text=name)
    assert matching_row.count() == 1
    assert "Showing 1 of" in page.locator("#processes-list-count").inner_text()
    assert page.locator("a.processes-list-item__open button").count() == 0

    history = page.locator(f'.processes-list-item__history-btn[data-process-id="{pid}"]')
    history.click()
    page.wait_for_selector("#pl-story-panel.pl-story-panel--open")
    assert page.locator("#pl-story-title").inner_text() == name
    assert page.url.endswith("/core/processes")

    page.locator("#pl-story-close").click()
    matching_row.locator(".processes-list-item__open").click()
    page.wait_for_url(f"**/core/flows?id={pid}")


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


@pytest.fixture()
def admin_page(browser, app_url, fresh_user):
    from app.core.db.models.user import UserRole

    admin = fresh_user(role=UserRole.ADMIN)
    context = browser.new_context(base_url=app_url, ignore_https_errors=True)
    page = context.new_page()
    login_through_ui(page, admin["email"], admin["password"])
    yield page
    context.close()


def test_delete_process_removes_it(admin_page: Page):
    """DELETE /api/core/processes/<id> is ADMIN-gated (review/process-design, 2026-08-03:
    it cascades to every step + the entire ProcessVersion history, a strictly more
    destructive blast radius than the single-file process-docs delete, which was
    already ADMIN-gated) — see admin_page fixture, mirrored from
    tests/e2e/test_process_docs_flow.py's own admin_page for its AC19 delete tests."""
    page = admin_page
    name = f"E2E Delete {uuid.uuid4().hex[:8]}"
    pid = _create_process(page, name)

    resp = page.request.delete(f"/api/core/processes/{pid}", headers=csrf_headers(page))
    assert resp.status in (200, 204), f"delete failed: {resp.status} {resp.text()}"

    listing = page.request.get("/api/core/processes")
    assert name not in listing.text(), "deleted process still listed"


def test_delete_process_rejected_for_non_admin_member(logged_in_page: Page):
    """A MEMBER (the default e2e_user role) cannot delete a process."""
    page = logged_in_page
    name = f"E2E Delete Forbidden {uuid.uuid4().hex[:8]}"
    pid = _create_process(page, name)

    resp = page.request.delete(f"/api/core/processes/{pid}", headers=csrf_headers(page))
    assert resp.status == 403, f"expected 403 for non-admin delete, got {resp.status}: {resp.text()}"

    listing = page.request.get("/api/core/processes")
    assert name in listing.text(), "process should not have been deleted by a non-admin"


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


def test_live_board_names_batches_and_never_renders_object_object(logged_in_page: Page):
    """A batch with no recorded batch id must get a readable name on the live board.

    Regression: the board fell back to `String(execution.event_summary)`, and the list API's
    event_summary is a JSON object, so every unlabelled batch card, timeline row, aria-label
    and the detail-sheet title read "[object Object]". Covers both a batch with no batch id
    and one whose output carries a `batch_id`.
    """
    page = logged_in_page
    pid = _create_process(page, f"E2E Board {uuid.uuid4().hex[:8]}", is_draft=True)
    for number, step_name in ((1, "Macerate"), (2, "Distil")):
        added = page.request.post(
            f"/api/core/processes/{pid}/steps",
            headers=csrf_headers(page),
            data={"step_number": number, "name": step_name},
        )
        assert added.status in (200, 201), f"add step failed: {added.status} {added.text()}"

    def start() -> str:
        started = page.request.post("/api/core/executions", headers=csrf_headers(page), data={"process_id": pid})
        assert started.status in (200, 201), f"start execution failed: {started.status} {started.text()}"
        return started.json()["id"]

    start()  # unlabelled: no step completed, so no output carries a batch id
    labelled = start()
    body = page.request.get(f"/api/core/executions/{labelled}/with-process").json()
    first_step = sorted((body.get("execution", body))["execution_steps"], key=lambda st: st["step_number"])[0]
    completed = page.request.post(
        f"/api/core/executions/{labelled}/steps/{first_step['id']}/complete",
        headers=csrf_headers(page),
        data={
            "actual_inputs": [],
            "actual_outputs": [{"name": "Macerate", "quantity": 40, "unit": "L", "batch_id": "E2E-BATCH-0921"}],
            "execution_data": {},
        },
    )
    assert completed.status in (200, 201), f"complete step failed: {completed.status} {completed.text()[:300]}"

    page.goto("/core/executions/live")
    page.wait_for_load_state("networkidle")
    page.select_option("#core2-active-process-select", value=pid)

    cards = page.locator(".core2-active-card")
    cards.first.wait_for()
    assert cards.count() == 2, f"expected both batches on the board, got {cards.count()}"

    titles = [t.strip() for t in page.locator(".core2-active-card-id").all_inner_texts()]
    assert "E2E-BATCH-0921" in titles, f"labelled batch should use its batch id: {titles}"
    assert any(t.startswith("Batch from ") for t in titles), f"unlabelled batch needs a readable name: {titles}"

    page.click("[data-core2-active-view=timeline]")
    page.locator(".core2-tl-row").first.wait_for()
    page.click("[data-core2-active-view=pipeline]")
    cards.filter(has_text="Batch from").first.click()
    detail = page.locator("#core2-active-detail-overlay")
    detail.wait_for(state="visible")
    assert detail.locator("#core2-active-detail-id").inner_text().startswith("Batch from ")

    # Aria-labels are part of the rendered surface too, so check the whole panel's HTML.
    panel_html = page.locator("#core2-active-batches-panel").inner_html() + detail.inner_html()
    for junk in ("[object Object]", "undefined", "Unassigned", "n/a"):
        assert junk not in panel_html, f"live board leaked {junk!r}"
    assert_clean_page(page)


def test_create_process_without_name_is_rejected(logged_in_page: Page):
    """Unhappy path: no name → 400, nothing created."""
    page = logged_in_page
    resp = page.request.post("/api/core/processes", headers=csrf_headers(page), data={"category": "manufacturing"})
    assert resp.status == 400, f"expected 400 for nameless process, got {resp.status}"
