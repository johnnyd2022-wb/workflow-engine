"""Create-wizard sequencing and open-redirect guard (AC10-AC13).

The 7-page wizard (process-overview -> step-name -> inputs -> outputs ->
evidence-and-prompts -> summary -> next-steps) is session-backed: `_flow_state_get`/
`_flow_state_reset` track a `max_step` per process id (or "new" when none exists yet) in
the Flask session, and `_maybe_enforce_flow_wizard_step` uses it to block URL-driven
skip-ahead. `_safe_flow_return_to` is the open-redirect guard on the wizard's "back to
where I was" link, and `_filtered_flow_query_args` is the allowlist that keeps redirects
from carrying arbitrary query params along for the ride.

`logged_in_page` gives every test its own browser context from a shared storage-state
*snapshot* (see conftest.py's `storage_state_path`) — each test's context starts from
that snapshot independently, so per-test session-cookie mutations here (the whole point
of this file) never leak into other tests.
"""

import uuid

import pytest
from playwright.sync_api import Page

from tests.e2e.conftest import csrf_headers

pytestmark = pytest.mark.e2e


def _create_process_with_step(page, name: str) -> tuple[str, str]:
    proc = page.request.post(
        "/api/core/processes",
        headers=csrf_headers(page),
        data={"name": name, "category": "manufacturing"},
    )
    assert proc.status == 201, f"process setup failed: {proc.status} {proc.text()}"
    pid = proc.json()["id"]
    step = page.request.post(
        f"/api/core/processes/{pid}/steps",
        headers=csrf_headers(page),
        data={"step_number": 1, "name": "Mix"},
    )
    assert step.status == 201, f"step setup failed: {step.status} {step.text()}"
    return pid, step.json()["id"]


# --------------------------------------------------------------------------------------
# AC10: wizard entry point.
# --------------------------------------------------------------------------------------


def test_ac10_no_id_starts_fresh_and_lands_on_process_overview(logged_in_page: Page):
    page = logged_in_page

    # The redirect itself (before any client JS runs) carries fresh=1 — checked via the
    # raw HTTP response, since create-process-modal.js strips it from the address bar
    # with history.replaceState once the page loads (confirmed below via page.goto).
    redirected = page.request.get("/core/flows/create", max_redirects=0)
    assert redirected.status in (301, 302, 303, 307, 308)
    assert "process-overview" in redirected.headers.get("location", "")
    assert "fresh=1" in redirected.headers.get("location", "")

    page.goto("/core/flows/create")
    assert "/core/flows/create/process-overview" in page.url


def test_ac10_existing_process_id_resumes_wizard_for_that_process(logged_in_page: Page):
    page = logged_in_page
    pid, _sid = _create_process_with_step(page, f"E2E Wizard Resume {uuid.uuid4().hex[:8]}")

    page.goto(f"/core/flows/create?id={pid}")
    assert "/core/flows/create/process-overview" in page.url
    assert f"id={pid}" in page.url
    assert "fresh=1" not in page.url


def test_ac10_unknown_process_id_is_404(logged_in_page: Page):
    page = logged_in_page
    resp = page.goto(f"/core/flows/create?id={uuid.uuid4()}")
    assert resp.status == 404


# --------------------------------------------------------------------------------------
# AC11: wizard step sequencing / skip-ahead guard.
# --------------------------------------------------------------------------------------


def test_ac11_skip_ahead_with_no_anchor_bounces_to_the_start(logged_in_page: Page):
    """A totally fresh session jumping straight to a late page (no ?id=, so no persisted
    anchor exists) is bounced back to the wizard's beginning."""
    page = logged_in_page
    resp = page.goto("/core/flows/create/outputs")
    assert resp.status == 200
    assert "/core/flows/create/process-overview" in page.url, f"expected a bounce to the start, landed on {page.url}"


def test_ac11_skip_ahead_past_max_step_bounces_to_furthest_allowed_page(logged_in_page: Page):
    """Once a wizard session exists, jumping more than one page ahead of max_step bounces
    back to max_step's page, not all the way to the start."""
    page = logged_in_page
    page.goto("/core/flows/create")  # started=True, max_step=1 (process-overview)
    assert "/core/flows/create/process-overview" in page.url

    resp = page.goto("/core/flows/create/summary")  # requested=6, max_step+1=2 -> bounce
    assert resp.status == 200
    assert "/core/flows/create/process-overview" in page.url, f"expected a bounce to max_step, landed on {page.url}"


def test_ac11_single_step_advance_is_allowed(logged_in_page: Page):
    """Advancing exactly one page ahead of max_step is normal forward navigation, not a
    skip — it must not bounce."""
    page = logged_in_page
    page.goto("/core/flows/create")  # max_step=1
    resp = page.goto("/core/flows/create/step-name")  # requested=2 == max_step+1, allowed
    assert resp.status == 200
    assert "/core/flows/create/step-name" in page.url, f"single-step advance was bounced: {page.url}"


def test_ac11_persisted_process_id_auto_initializes_without_bouncing(logged_in_page: Page):
    """A process created mid-wizard (e.g. via the API) is itself the anchor: the first
    navigation to any page for that id advances state in place instead of bouncing."""
    page = logged_in_page
    pid, _sid = _create_process_with_step(page, f"E2E Wizard Anchor {uuid.uuid4().hex[:8]}")

    resp = page.goto(f"/core/flows/create/summary?id={pid}")
    assert resp.status == 200
    assert "/core/flows/create/summary" in page.url, f"persisted process id was bounced away: {page.url}"
    assert f"id={pid}" in page.url


def test_ac11_persisted_process_id_reaches_next_steps_page(logged_in_page: Page):
    """Same auto-initialize behavior as the summary page above, exercised on the wizard's
    final page (next-steps: 'add another step or finish')."""
    page = logged_in_page
    pid, _sid = _create_process_with_step(page, f"E2E Wizard NextSteps {uuid.uuid4().hex[:8]}")

    resp = page.goto(f"/core/flows/create/next-steps?id={pid}")
    assert resp.status == 200
    assert "/core/flows/create/next-steps" in page.url


@pytest.mark.parametrize(
    "step,expected_path",
    [
        (1, "/core/flows/create/process-overview"),
        (2, "/core/flows/create/inputs"),
        (3, "/core/flows/create/outputs"),
        (4, "/core/flows/create/evidence-and-prompts"),
        (5, "/core/flows/create/process-overview"),
        (99, "/core/flows/create/process-overview"),
    ],
)
def test_legacy_numeric_step_shim_redirects_to_current_named_pages(logged_in_page: Page, step: int, expected_path: str):
    """/core/flows/create/step/<int> is a best-effort redirect shim for old bookmarks
    (ASSUMPTION in the spec). Note step=2 maps to 'inputs', not 'step-name' — steps 5+
    all fall through to process-overview rather than 404ing. Checked against the shim's
    own redirect Location header (max_redirects=0) so this is independent of the wizard
    sequencing guard the target page would separately apply."""
    page = logged_in_page
    resp = page.request.get(f"/core/flows/create/step/{step}", max_redirects=0)
    assert resp.status in (301, 302, 303, 307, 308)
    location_path = resp.headers.get("location", "").split("?")[0]
    assert location_path == expected_path, f"step {step} redirected to {location_path!r}, expected {expected_path!r}"


# --------------------------------------------------------------------------------------
# AC12: _safe_flow_return_to open-redirect guard.
# --------------------------------------------------------------------------------------

_BYPASS_PAYLOADS = [
    "//evil.com",
    "javascript:alert(1)",
    "/core/flows/../../admin",
    "\\\\evil.com",
    "/core/flows\\..\\..\\admin",
    "%5c..%5c..%5cadmin",
    "https://evil.com/core/flows",
    "data:text/html,<script>alert(1)</script>",
]


@pytest.mark.parametrize("payload", _BYPASS_PAYLOADS)
def test_ac12_return_to_bypass_payloads_fall_back_to_safe_default(logged_in_page: Page, payload: str):
    page = logged_in_page
    pid, sid = _create_process_with_step(page, f"E2E ReturnTo {uuid.uuid4().hex[:8]}")

    resp = page.request.get(
        "/core/flows/batches/start",
        params={"id": pid, "draft": "1", "step_id": sid, "return_to": payload},
    )
    assert resp.status == 200, f"page failed to render: {resp.status}"
    body = resp.text()
    assert f'"/core/flows?id={pid}"' in body, "expected the safe default return_to, got page body without it"
    assert "evil.com" not in body, f"bypass payload leaked into the page: {payload!r}"
    assert "javascript:" not in body.lower(), f"bypass payload leaked into the page: {payload!r}"
    assert "<script>alert" not in body, f"bypass payload leaked into the page: {payload!r}"


def test_ac12_return_to_allows_legit_wizard_path(logged_in_page: Page):
    """Positive control: a real /core/flows/... path is preserved, not replaced — proves
    the parametrized bypass test above is actually exercising the guard, not just always
    returning the default regardless of input."""
    page = logged_in_page
    pid, sid = _create_process_with_step(page, f"E2E ReturnTo Legit {uuid.uuid4().hex[:8]}")
    legit = f"/core/flows/create/summary?id={pid}"

    resp = page.request.get(
        "/core/flows/batches/start",
        params={"id": pid, "draft": "1", "step_id": sid, "return_to": legit},
    )
    assert resp.status == 200
    assert f'"{legit}"' in resp.text(), "a legitimate same-app return_to path was not preserved"


# --------------------------------------------------------------------------------------
# AC13: only {id, fresh} survive a wizard redirect's query string.
# --------------------------------------------------------------------------------------


def test_ac13_redirect_drops_unlisted_query_params(logged_in_page: Page):
    page = logged_in_page
    pid, _sid = _create_process_with_step(page, f"E2E QueryFilter {uuid.uuid4().hex[:8]}")

    resp = page.request.get(
        "/core/flows/create",
        params={"id": pid, "fresh": "1", "evil": "xss", "return_to": "//evil.com"},
        max_redirects=0,
    )
    assert resp.status in (301, 302, 303, 307, 308), f"expected a redirect, got {resp.status}"
    location = resp.headers.get("location", "")
    assert "evil" not in location, f"unlisted query param leaked into the redirect: {location}"
    assert f"id={pid}" in location
    assert "fresh=1" in location


# --------------------------------------------------------------------------------------
# Perf: the Inputs step is an inventory picker -- it must not pull the fat list.
# --------------------------------------------------------------------------------------


def test_inputs_step_loads_inventory_compact_not_the_full_list(logged_in_page: Page):
    """create-process-modal.js::loadInventoryItems used to fetch /api/core/inventory
    three times (process-scoped, ?type=raw_material, and unfiltered ~1 MB) then dedupe by
    name. It needs only name/unit/type, so it uses ?view=compact and drops the redundant
    raw-material call."""
    page = logged_in_page
    pid, _sid = _create_process_with_step(page, f"E2E InputsPerf {uuid.uuid4().hex[:8]}")

    inv_calls: list[str] = []
    page.on(
        "request",
        lambda r: inv_calls.append(r.url.split("/api/core/", 1)[1])
        if r.method == "GET" and "/api/core/inventory" in r.url
        else None,
    )

    page.goto(f"/core/flows/create/inputs?id={pid}")
    page.wait_for_load_state("networkidle")

    plain = [c for c in inv_calls if c.split("?")[0] == "inventory"]
    assert plain, f"no /api/core/inventory call on the Inputs step: {inv_calls}"
    assert all("view=compact" in c for c in plain), f"Inputs step fetched the fat inventory list: {inv_calls}"
    assert not any("type=raw_material" in c for c in inv_calls), f"redundant raw-material call still fires: {inv_calls}"
