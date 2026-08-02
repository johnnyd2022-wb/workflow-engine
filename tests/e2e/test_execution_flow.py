"""Execution-slice gap-fill: browser-level proof for ACs that only a real UI click proves.

Companion to test_workflow_flow.py (which proves the execution spine works end to end).
This file targets acceptance criteria from .agents/specs/execution.md that a unit/API test
cannot fully prove because the AC is specifically about what the *client* does with a
server response: does the error/warning actually render somewhere a user would see it, not
just come back in the HTTP body. Everything already covered by tests/test_executions.py,
tests/test_dag_traversal.py, or tests/test_evidence.py at the unit/API level is deliberately
not re-tested here.

The canonical "record a step" screen (/core/flows/batches/start) always loads the execution's
current READY step server-side (execution-step-page.js) — the UI structurally cannot be
pointed at an out-of-order step through normal navigation. AC4's step-order guard is
therefore a defense-in-depth check for a client whose local state has drifted from the
server (a stale tab, or a forged request). test_ac4 reproduces exactly that: the modal loads
the true ready step, then the test overrides the modal's target step id (the one piece of
state a stale tab would have wrong) before clicking the real "Record step" -> "Confirm"
flow, so the assertion is on the app's own error-rendering code path
(execution-submit.js's showNotification call), not a mocked one.
"""

import time

import pytest
from playwright.sync_api import Page, expect

from tests.e2e.conftest import csrf_headers, login_through_ui

pytestmark = pytest.mark.e2e

PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
TXT_BYTES = b"not an image, just plain text pretending to be evidence"


def _create_process(page, name: str, is_draft: bool = True) -> str:
    resp = page.request.post(
        "/api/core/processes",
        headers=csrf_headers(page),
        data={"name": name, "category": "manufacturing", "is_draft": is_draft},
    )
    assert resp.status in (200, 201), f"create process failed: {resp.status} {resp.text()}"
    return resp.json()["id"]


def _add_step(page, pid: str, step_number: int, name: str, outputs=None, execution_prompts=None) -> str:
    payload = {"step_number": step_number, "name": name}
    if outputs is not None:
        payload["outputs"] = outputs
    if execution_prompts is not None:
        payload["execution_prompts"] = execution_prompts
    resp = page.request.post(f"/api/core/processes/{pid}/steps", headers=csrf_headers(page), data=payload)
    assert resp.status in (200, 201), f"add step failed: {resp.status} {resp.text()}"
    return resp.json()["id"]


def _start_execution(page, pid: str) -> str:
    resp = page.request.post("/api/core/executions", headers=csrf_headers(page), data={"process_id": pid})
    assert resp.status in (200, 201), f"start execution failed: {resp.status} {resp.text()}"
    eid = resp.json().get("id")
    assert eid, f"no execution id: {resp.text()}"
    return eid


def _with_process(page, eid: str) -> dict:
    resp = page.request.get(f"/api/core/executions/{eid}/with-process")
    assert resp.status == 200, f"read execution failed: {resp.status} {resp.text()}"
    return resp.json()


def _execution_step(bundle: dict, step_number: int) -> dict:
    steps = bundle["execution"]["execution_steps"]
    return next(s for s in steps if s["step_number"] == step_number)


def _complete_step_via_api(page, eid: str, esid: str) -> "object":
    return page.request.post(
        f"/api/core/executions/{eid}/steps/{esid}/complete",
        headers=csrf_headers(page),
        data={"actual_inputs": [], "actual_outputs": [], "execution_data": {}},
    )


def _open_batch_start(page: Page, pid: str, eid: str) -> None:
    page.goto(f"/core/flows/batches/start?id={pid}&execution_id={eid}")
    page.wait_for_load_state("networkidle")


def _record_step_and_confirm(page: Page, *, delay_redirect: bool = False) -> None:
    """Drives the real two-click "Record step" -> "Confirm" flow (batch-start-scripts.html).

    On a successful (or warning) completion, execution-submit.js calls showNotification()
    and then `await`s onStepCompleted(), which immediately HTMX-navigates to /core/flows —
    swapping #page-content, including the notification markup, out from under the toast it
    just showed. That leaves a real but sub-poll-interval window for the toast to be visible,
    which a plain expect(...).to_be_visible() loses more often than not. delay_redirect=True
    holds the redirect's own network response for a beat so the assertion has a fair, real
    window to observe the DOM the app actually produced — not a race on how fast Playwright
    happens to poll.
    """
    if delay_redirect:

        def _hold(route):
            time.sleep(0.4)
            route.continue_()

        page.route("**/core/flows*", _hold)
    page.locator("#batch-start-record-btn").click()
    page.locator("#batch-record-confirm-ok").click()


def _notification_modal(page: Page):
    """The #notification-modal id is duplicated in the live DOM after any HTMX navigation to
    /core/flows: base_spa.html's shared shell defines the real, working one outside
    #page-content, but flows2-modals.html (swapped into #page-content) also defines its own
    copy of the same id — dead markup left over from before the shared notification chrome
    existed, never removed. getElementById (what the app's own JS uses) always resolves the
    shell's copy consistently, so this is not user-visible, but Playwright's strict-mode
    locator matching correctly refuses to guess between two elements sharing an id — hence
    .first here rather than papering over the duplicate by scoping this locator's own search.
    Flagged as a real, low-priority cleanup finding in the review report; not fixed here to
    keep this test file's blast radius to test code only.
    """
    return page.locator("#notification-modal").first


def _notification_title(page: Page):
    return page.locator("#notification-title").first


def _notification_message(page: Page):
    return page.locator("#notification-message").first


def _list_evidence(page, eid: str) -> list:
    resp = page.request.get(f"/api/core/evidence/list?execution_id={eid}")
    assert resp.status == 200, resp.text()
    return resp.json()["evidence"]


def test_ac4_step_order_violation_surfaces_error_in_ui(logged_in_page: Page):
    """AC4: completing a step before all lower-numbered steps are COMPLETED -> 400, and the
    error must render where the operator can see it, not just in the HTTP response.
    """
    page = logged_in_page
    pid = _create_process(page, "E2E Order Violation")
    _add_step(page, pid, 1, "Step One")
    _add_step(page, pid, 2, "Step Two")
    eid = _start_execution(page, pid)

    bundle = _with_process(page, eid)
    step2_exec_id = _execution_step(bundle, 2)["id"]

    _open_batch_start(page, pid, eid)
    expect(page.locator("#exec-step-subtitle")).to_contain_text("Step One")

    # The modal has genuinely loaded step 1 (the true ready step). Override the one piece of
    # client state a stale tab or forged client would have wrong — the target step id — so the
    # real "Record step" click attempts step 2 while step 1 is still incomplete. This exercises
    # the production submitExecution() -> CoreAPI.completeStep() -> showNotification() path with
    # a real server rejection, not a synthetic one.
    page.evaluate(
        "(id) => { document.getElementById('execute-step-modal').dataset.executionStepId = id; }",
        step2_exec_id,
    )

    _record_step_and_confirm(page)

    expect(_notification_modal(page)).to_be_visible()
    expect(_notification_title(page)).to_have_text("Failed to Complete Step")
    expect(_notification_message(page)).to_contain_text("prior steps")
    expect(_notification_message(page)).to_contain_text("are not completed")

    # No partial mutation: step 2 must still be untouched.
    after = _with_process(page, eid)
    assert _execution_step(after, 2)["status"] in ("pending", "PENDING"), after


def test_ac5_already_completed_step_rejection_surfaces_error_in_ui(logged_in_page: Page):
    """AC5: a step that is no longer READY/IN_PROGRESS (already completed by a second tab or
    operator) -> 400, surfaced to the still-open tab as a visible error, not a silent failure.
    """
    page = logged_in_page
    pid = _create_process(page, "E2E Already Completed")
    _add_step(page, pid, 1, "Only Step")
    eid = _start_execution(page, pid)

    _open_batch_start(page, pid, eid)
    expect(page.locator("#exec-step-subtitle")).to_contain_text("Only Step")

    # Simulate a second tab/operator completing this same step first — a genuine race the UI
    # cannot prevent, which is exactly what this server-side guard defends against.
    bundle = _with_process(page, eid)
    step1_exec_id = _execution_step(bundle, 1)["id"]
    first_complete = _complete_step_via_api(page, eid, step1_exec_id)
    assert first_complete.status in (200, 201), first_complete.text()

    # This tab's UI still thinks step 1 is READY and untouched — click through its own flow.
    _record_step_and_confirm(page)

    expect(_notification_modal(page)).to_be_visible()
    expect(_notification_title(page)).to_have_text("Failed to Complete Step")
    expect(_notification_message(page)).to_contain_text("not in a state that can be completed")


def test_ac9_zero_quantity_output_skipped_with_warning_shown_in_ui(logged_in_page: Page):
    """AC9/AC10: a zero-quantity output is skipped (not blocked), and the resulting warning
    must be shown to the operator in the UI, not just returned in the response body.
    """
    page = logged_in_page
    pid = _create_process(page, "E2E Zero Qty Output")
    _add_step(page, pid, 1, "Produce", outputs=[{"name": "Out1", "quantity": 5, "unit": "kg"}])
    eid = _start_execution(page, pid)

    _open_batch_start(page, pid, eid)
    expect(page.locator("#exec-step-subtitle")).to_contain_text("Produce")

    qty_input = page.locator(".execute-output-quantity-input")
    expect(qty_input).to_be_visible()
    qty_input.fill("0")

    _record_step_and_confirm(page, delay_redirect=True)

    expect(_notification_modal(page)).to_be_visible()
    expect(_notification_title(page)).to_have_text("Step completed with warnings")
    expect(_notification_message(page)).to_contain_text("Out1")
    expect(_notification_message(page)).to_contain_text("zero or negative quantity")

    # The step still completed (warnings are non-blocking). actual_outputs is the raw
    # submission and legitimately still records the zero-quantity attempt; the "skip" is
    # about not creating an InventoryItem for it, which is what we check for here.
    after = _with_process(page, eid)
    step1 = _execution_step(after, 1)
    assert step1["status"] in ("completed", "COMPLETED"), step1
    inv_resp = page.request.get(f"/api/core/inventory?process_id={pid}")
    assert inv_resp.status == 200, inv_resp.text()
    assert inv_resp.json()["inventory_items"] == [], inv_resp.text()


def test_ac14_evidence_upload_succeeds_and_becomes_downloadable(logged_in_page: Page):
    """AC14/AC15: uploading a real image through the file input succeeds, and the resulting
    evidence record is genuinely finalized (ACTIVE) — proven by it being downloadable, not
    just present with a PENDING status a UI could paper over.
    """
    page = logged_in_page
    pid = _create_process(page, "E2E Evidence Upload")
    _add_step(
        page,
        pid,
        1,
        "Photo Step",
        execution_prompts=[{"type": "evidence", "label": "Photo evidence", "required": True}],
    )
    eid = _start_execution(page, pid)

    _open_batch_start(page, pid, eid)
    expect(page.locator("#exec-step-subtitle")).to_contain_text("Photo Step")

    file_input = page.locator(".execute-evidence-file-input")
    expect(file_input).to_be_attached()
    file_input.set_input_files(files=[{"name": "proof.png", "mimeType": "image/png", "buffer": PNG_BYTES}])
    expect(page.get_by_text("proof.png")).to_be_visible()

    _record_step_and_confirm(page, delay_redirect=True)

    expect(_notification_modal(page)).to_be_visible()
    expect(_notification_title(page)).to_have_text("Step Completed")

    evidence = _list_evidence(page, eid)
    assert len(evidence) == 1, evidence
    assert evidence[0]["file_name"] == "proof.png", evidence

    # A record stuck at PENDING (finalize/checksum step failed) would 404 here — active_only
    # download is the real-world proof that the two-phase upload actually reached ACTIVE.
    download = page.request.get(f"/api/core/evidence/{evidence[0]['id']}/download")
    assert download.status == 200, download.text()
    assert download.body() == PNG_BYTES


def test_ac14_evidence_upload_rejects_disallowed_file_type(logged_in_page: Page):
    """AC14 unhappy path: server-side MIME sniffing (not the client's declared type) rejects a
    disallowed file, the rejection is shown to the operator, and nothing is left half-done —
    no evidence record, and the step is not completed.
    """
    page = logged_in_page
    pid = _create_process(page, "E2E Evidence Rejected")
    _add_step(
        page,
        pid,
        1,
        "Photo Step",
        execution_prompts=[{"type": "evidence", "label": "Photo evidence", "required": True}],
    )
    eid = _start_execution(page, pid)

    _open_batch_start(page, pid, eid)
    expect(page.locator("#exec-step-subtitle")).to_contain_text("Photo Step")

    file_input = page.locator(".execute-evidence-file-input")
    # accept="image/jpeg,image/png,application/pdf" on the input is a client hint only; a real
    # attacker (or a careless operator on a renamed file) bypasses it trivially, which is exactly
    # why the server sniffs magic bytes rather than trusting Content-Type. set_input_files does
    # the same bypass here on purpose.
    file_input.set_input_files(files=[{"name": "evil.txt", "mimeType": "text/plain", "buffer": TXT_BYTES}])
    expect(page.get_by_text("evil.txt")).to_be_visible()

    _record_step_and_confirm(page)

    expect(_notification_modal(page)).to_be_visible()
    expect(_notification_title(page)).to_have_text("Evidence upload failed")
    expect(_notification_message(page)).to_contain_text("File type not allowed")

    assert _list_evidence(page, eid) == []
    after = _with_process(page, eid)
    assert _execution_step(after, 1)["status"] in ("ready", "READY"), after


def test_ac17_evidence_download_and_delete_through_ui(logged_in_page: Page):
    """AC17: an operator can download and remove evidence attached to a step they own, through
    the real widgets (not just via the API), and a delete really persists.
    """
    page = logged_in_page
    pid = _create_process(page, "E2E Evidence Manage")
    step_def_id = _add_step(
        page,
        pid,
        1,
        "Photo Step",
        execution_prompts=[{"type": "evidence", "label": "Photo evidence", "required": False}],
    )
    eid = _start_execution(page, pid)

    # Seed a real, already-finalized evidence record (as if attached moments earlier), so the
    # widget renders the real View/Download/Remove row instead of the client-staged "pending" one.
    upload = page.request.post(
        "/api/core/evidence/upload",
        headers=csrf_headers(page),
        multipart={
            "execution_id": eid,
            "step_id": step_def_id,
            "file": {"name": "already-attached.png", "mimeType": "image/png", "buffer": PNG_BYTES},
        },
    )
    assert upload.status == 201, upload.text()
    evidence_id = upload.json()["id"]

    _open_batch_start(page, pid, eid)
    expect(page.locator("#exec-step-subtitle")).to_contain_text("Photo Step")

    row = page.locator(f'.execute-evidence-row[data-evidence-id="{evidence_id}"]')
    expect(row).to_be_visible()
    expect(row).to_contain_text("already-attached.png")

    with page.expect_download() as download_info:
        row.get_by_role("link", name="Download").click()
    download = download_info.value
    assert download.suggested_filename == "already-attached.png"

    row.get_by_role("button", name="Remove").click()
    expect(_notification_modal(page)).to_be_visible()
    expect(_notification_title(page)).to_have_text("Evidence removed")
    expect(row).to_have_count(0)

    remaining = _list_evidence(page, eid)
    assert evidence_id not in [e["id"] for e in remaining], remaining


@pytest.fixture()
def two_tenant_pages(browser, app_url, fresh_user):
    """Two orgs, each with its own authenticated browser context (mirrors test_tenant_isolation)."""
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


def test_cross_tenant_cannot_reach_execution_step_page_or_evidence(two_tenant_pages):
    """Mandatory cross-tenant probe: org B must never see or act on org A's execution or
    evidence, whether through the execute-step page or the evidence API routes directly.
    """
    page_a = two_tenant_pages["a"]
    page_b = two_tenant_pages["b"]

    pid = _create_process(page_a, "E2E Cross Tenant Execution")
    step_def_id = _add_step(page_a, pid, 1, "Secret Step")
    eid = _start_execution(page_a, pid)

    upload = page_a.request.post(
        "/api/core/evidence/upload",
        headers=csrf_headers(page_a),
        multipart={
            "execution_id": eid,
            "step_id": step_def_id,
            "file": {"name": "secret.png", "mimeType": "image/png", "buffer": PNG_BYTES},
        },
    )
    assert upload.status == 201, upload.text()
    evidence_id = upload.json()["id"]

    # Fetch org B's own CSRF token *before* navigating to the (soon to be 404) execute-step
    # page below — csrf_headers() reads the meta tag off the current page, and Flask's default
    # 404 page has no such tag, which would otherwise hang this call waiting for it.
    b_headers = csrf_headers(page_b)

    # Page-level: org B cannot even open org A's execute-step screen.
    resp = page_b.goto(f"/core/flows/batches/start?id={pid}&execution_id={eid}")
    assert resp is not None and resp.status == 404, getattr(resp, "status", None)

    # Route-level: org B cannot download org A's evidence.
    download = page_b.request.get(f"/api/core/evidence/{evidence_id}/download")
    assert download.status == 404, download.text()

    # delete_evidence() is deliberately idempotent (evidence_service.py: "if the record is
    # already missing, returns success so retries get 200") and org-scopes its lookup, so an
    # id belonging to another org is indistinguishable from an already-deleted id -> 200, not
    # 404. That is safe *only* if it never actually touches org A's row underneath — assert
    # that directly rather than trusting the status code alone.
    delete = page_b.request.delete(f"/api/core/evidence/{evidence_id}", headers=b_headers)
    assert delete.status == 200, delete.text()

    # The org-B delete call must not have actually removed org A's evidence.
    still_there = page_a.request.get(f"/api/core/evidence/{evidence_id}/download")
    assert still_there.status == 200, still_there.text()
    assert still_there.body() == PNG_BYTES
