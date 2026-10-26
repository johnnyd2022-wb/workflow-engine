"""GL-U03: a save that meets an expired session or a dropped connection loses nothing.

Recording a production step is the first critical write the assessment names. Both failures
must leave the form as typed, save nothing, and say what happened; an expired session must
also say how to get back in without leaving the page (app/ui/shared/session-ended.js).
"""

from __future__ import annotations

import time

import pytest
from playwright.sync_api import Page, expect

from tests.e2e.test_execution_flow import (
    _add_step,
    _create_process,
    _execution_step,
    _notification_message,
    _open_batch_start,
    _start_execution,
    _with_process,
)

pytestmark = pytest.mark.e2e


def _step_form(page: Page) -> tuple[str, str]:
    pid = _create_process(page, f"Interrupted save {time.time()}", is_draft=False)
    _add_step(page, pid, 1, "Distil", execution_prompts=[{"label": "Still temp", "type": "text", "required": False}])
    eid = _start_execution(page, pid)
    _open_batch_start(page, pid, eid)
    return pid, eid


def _fail_the_save(page: Page, how: str) -> None:
    def handler(route):
        if route.request.method == "POST" and route.request.url.endswith("/complete"):
            if how == "offline":
                return route.abort("internetdisconnected")
            return route.fulfill(
                status=401,
                content_type="application/json",
                body='{"error": "Session expired or account is unavailable"}',
            )
        return route.continue_()

    page.route("**/api/core/executions/**", handler)


def _record(page: Page) -> None:
    page.locator("#batch-start-record-btn").click()
    page.locator("#batch-record-confirm-ok").click()


@pytest.mark.parametrize("how", ["offline", "signed-out"])
def test_an_interrupted_step_save_keeps_the_form_and_saves_nothing(logged_in_page: Page, how):
    page = logged_in_page
    _, eid = _step_form(page)
    field = page.get_by_label("Still temp")
    field.fill("82")
    _fail_the_save(page, how)
    _record(page)

    expect(_notification_message(page)).to_contain_text("Network error" if how == "offline" else "Session expired")
    expect(field).to_have_value("82")
    assert _execution_step(_with_process(page, eid), 1)["status"] != "completed"


def test_a_signed_out_save_says_how_to_get_back_in_without_leaving(logged_in_page: Page):
    page = logged_in_page
    _step_form(page)
    _fail_the_save(page, "signed-out")
    _record(page)

    notice = page.get_by_role("alert").filter(has_text="You’ve been signed out")
    expect(notice).to_be_visible()
    link = notice.get_by_role("link", name="Sign in again")
    expect(link).to_have_attribute("target", "_blank")
    expect(link).to_have_attribute("href", "/?login=1")
    notice.get_by_role("button", name="Close").click()
    expect(notice).to_be_hidden()


def test_an_offline_save_does_not_claim_the_session_ended(logged_in_page: Page):
    page = logged_in_page
    _step_form(page)
    _fail_the_save(page, "offline")
    _record(page)
    expect(_notification_message(page)).to_contain_text("Network error")
    expect(page.locator("#session-ended-notice")).to_have_count(0)


# --- Codex review on !573: the real journey, not a fulfilled 401 ---------------------------


_SAVE = """async (name) => {
  const token = document.querySelector('meta[name="csrf-token"]').getAttribute('content');
  const r = await fetch('/api/core/processes', {
    method: 'POST', credentials: 'include',
    headers: { 'Content-Type': 'application/json', 'X-CSRFToken': token },
    body: JSON.stringify({ name, is_draft: true }),
  });
  return r.status;
}"""


def test_signed_out_then_signed_in_elsewhere_the_open_page_saves(logged_in_page: Page, e2e_user):
    from tests.e2e.conftest import login_through_ui

    page = logged_in_page
    page.goto("/core/processes")
    page.wait_for_load_state("networkidle")
    name = f"Saved after signing in again {time.time()}"

    # The session ends (expiry, or the cookie is lost): real Flask-WTF fails the CSRF check
    # first, and that now reads as signed out, with the way back in.
    page.context.clear_cookies()
    assert page.evaluate(_SAVE, name) == 401
    expect(page.get_by_role("alert").filter(has_text="You’ve been signed out")).to_be_visible()

    # Sign in for real in another tab: a new session and a new CSRF secret.
    other = page.context.new_page()
    login_through_ui(other, e2e_user["email"], e2e_user["password"])
    other.close()

    # Back on the first page, with its stale token and without reloading: the save goes through.
    page.bring_to_front()
    assert page.evaluate(_SAVE, name) == 201
    listed = page.request.get("/api/core/processes").json()
    listed = listed.get("processes", listed) if isinstance(listed, dict) else listed
    assert any(p["name"] == name for p in listed)
