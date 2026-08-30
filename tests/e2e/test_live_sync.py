"""LiveSync end-to-end: a change one user makes shows up on another user's open page
within a poll interval, no reload. This is the whole point of the change feed."""

import uuid

import pytest
from playwright.sync_api import expect

from tests.e2e.conftest import login_through_ui, purge_org

pytestmark = pytest.mark.e2e


@pytest.fixture
def two_users_one_org(browser, app_url):
    """One org, two committed users, each in its own logged-in browser context."""
    from app.core.db import db_session
    from app.core.db.models.user import User
    from tests.factories import DEFAULT_TEST_PASSWORD, OrganisationFactory, UserFactory

    session = db_session()
    run = uuid.uuid4().hex[:8]
    org = OrganisationFactory(name=f"LiveSync Org {run}")
    u1 = UserFactory(org_id=org.id, email=f"livesync-a-{run}@example.test")
    u2 = UserFactory(org_id=org.id, email=f"livesync-b-{run}@example.test")
    session.commit()
    uids = [u1.id, u2.id]

    contexts = []

    def _signed_in(email):
        ctx = browser.new_context(base_url=app_url, ignore_https_errors=True)
        contexts.append(ctx)
        page = ctx.new_page()
        login_through_ui(page, email, DEFAULT_TEST_PASSWORD)
        return page

    yield org, _signed_in(u1.email), _signed_in(u2.email)

    for ctx in contexts:
        ctx.close()
    session.rollback()
    for uid in uids:
        purge_org(session, org.id, uid)
        session.query(User).filter(User.id == uid).delete(synchronize_session=False)
    session.commit()


def _csrf(page):
    return page.evaluate("() => document.querySelector('meta[name=csrf-token]').content")


def test_a_batch_started_by_one_user_appears_on_another_users_flows2(two_users_one_org):
    _org, page_a, page_b = two_users_one_org

    # B creates a process with a step (via API, the shape the wizard produces).
    hdrs = {"X-CSRFToken": _csrf(page_b), "Content-Type": "application/json", "Referer": page_b.url}
    proc = page_b.request.post(
        "/api/core/processes", headers=hdrs, data='{"name": "LiveSync Line", "category": "manufacturing"}'
    )
    assert proc.status == 201, proc.text()
    pid = proc.json()["id"]
    step = page_b.request.post(
        f"/api/core/processes/{pid}/steps", headers=hdrs, data='{"step_number": 1, "name": "Mix"}'
    )
    assert step.status == 201, step.text()

    # A opens that process's flows2 and lands on Batches (0 batches).
    exec_fetches: list[str] = []
    page_a.on(
        "request",
        lambda r: exec_fetches.append(r.url)
        if r.method == "GET" and "/api/core/executions?process_id" in r.url
        else None,
    )
    page_a.goto(f"/core/flows?id={pid}")
    page_a.wait_for_load_state("networkidle")
    page_a.wait_for_selector('[data-flows2-target="batches"]')
    baseline = len(exec_fetches)
    expect(page_a.locator("#executions-badge")).to_have_text("0")

    # B starts a batch. A never touches the page.
    started = page_b.request.post(
        "/api/core/executions", headers={**hdrs, "Referer": page_b.url}, data=f'{{"process_id": "{pid}"}}'
    )
    assert started.status == 201, started.text()

    # Within a couple of poll intervals A's flows2 refetches and the badge ticks to 1.
    expect(page_a.locator("#executions-badge")).to_have_text("1", timeout=15_000)
    assert len(exec_fetches) > baseline, "flows2 did not refetch executions after the live change"


def test_live_sync_starts_and_tracks_a_cursor(logged_in_page):
    page = logged_in_page
    page.goto("/core")
    page.wait_for_load_state("networkidle")
    status = page.evaluate("() => (window.LiveSync ? window.LiveSync.status() : null)")
    assert status is not None, "LiveSync did not load"
    assert status["started"] is True
    assert isinstance(status["cursor"], int) and status["cursor"] >= 0


def _make_process_with_step(page):
    hdrs = {"X-CSRFToken": _csrf(page), "Content-Type": "application/json", "Referer": page.url}
    proc = page.request.post(
        "/api/core/processes", headers=hdrs, data='{"name": "PhaseB Line", "category": "manufacturing"}'
    )
    assert proc.status == 201, proc.text()
    pid = proc.json()["id"]
    step = page.request.post(f"/api/core/processes/{pid}/steps", headers=hdrs, data='{"step_number": 1, "name": "Mix"}')
    assert step.status == 201, step.text()
    return pid, hdrs


def test_core_hub_reflects_a_colleague_batch_without_reload(two_users_one_org):
    """Phase B: the /core hub's active-batches KPI updates when another user starts a
    batch, no reload -- the hub used to only re-fetch after the current user's own
    mutation."""
    _org, page_a, page_b = two_users_one_org
    pid, hdrs = _make_process_with_step(page_b)

    page_a.goto("/core")
    page_a.wait_for_load_state("networkidle")
    page_a.wait_for_selector("#metric-active-executions")
    expect(page_a.locator("#metric-active-executions")).to_have_text("0")

    started = page_b.request.post(
        "/api/core/executions", headers={**hdrs, "Referer": page_b.url}, data=f'{{"process_id": "{pid}"}}'
    )
    assert started.status == 201, started.text()

    expect(page_a.locator("#metric-active-executions")).to_have_text("1", timeout=15_000)


def test_dashboard_reflects_a_colleague_batch_without_reload(two_users_one_org):
    """Phase B: /core/dashboard's active-batches KPI ticks when a colleague starts a
    batch, no reload."""
    _org, page_a, page_b = two_users_one_org
    pid, hdrs = _make_process_with_step(page_b)

    page_a.goto("/core/dashboard")
    page_a.wait_for_selector("[data-dashboard-root]")
    page_a.wait_for_load_state("networkidle")

    started = page_b.request.post(
        "/api/core/executions", headers={**hdrs, "Referer": page_b.url}, data=f'{{"process_id": "{pid}"}}'
    )
    assert started.status == 201, started.text()

    expect(page_a.locator("[data-kpi-active-batches]")).to_have_text("1", timeout=15_000)


def test_execute_step_page_warns_when_the_batch_changes_elsewhere(two_users_one_org):
    """Phase B: a user recording a step sees a sticky warning (not an auto-reload) when
    someone else completes that step or changes the batch underneath them."""
    _org, page_a, page_b = two_users_one_org
    pid, hdrs = _make_process_with_step(page_b)

    started = page_b.request.post(
        "/api/core/executions", headers={**hdrs, "Referer": page_b.url}, data=f'{{"process_id": "{pid}"}}'
    )
    assert started.status == 201, started.text()
    eid = started.json()["id"]

    detail = page_b.request.get(f"/api/core/executions/{eid}")
    assert detail.status == 200, detail.text()
    steps = detail.json().get("execution_steps", [])
    ready = next(s for s in steps if str(s.get("status", "")).lower() == "ready")
    esid = ready["id"]

    page_a.goto(f"/core/flows/batches/start?execution_id={eid}&id={pid}")
    page_a.wait_for_load_state("networkidle")
    page_a.wait_for_selector("#execute-step-modal")
    assert page_a.locator("#exec-step-stale-warning").count() == 0

    done = page_b.request.post(
        f"/api/core/executions/{eid}/steps/{esid}/complete",
        headers={**hdrs, "Referer": page_b.url},
        data="{}",
    )
    assert done.status in (200, 201), done.text()

    expect(page_a.locator("#exec-step-stale-warning")).to_be_visible(timeout=15_000)
