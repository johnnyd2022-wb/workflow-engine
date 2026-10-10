"""The Production overview (/core): what is under way, how far along, and the next step on each batch.

The batches are served into the page's one overview request, so every stage and age is on screen
without building seven executions per test. The layout tests bound to the page live in
`tests/e2e/test_workspace_overviews.py`.
"""

import re
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from playwright.sync_api import expect

from app.core.db.models.user import UserRole
from tests.e2e.conftest import assert_clean_page, attach_probe, login_through_ui
from tests.factories import ExecutionFactory, InventoryItemFactory, ProcessFactory

pytestmark = pytest.mark.e2e

OVERVIEW = "**/api/core/hub/overview*"


def _batch(name, step, done, total, hours):
    started = datetime.now(UTC) - timedelta(hours=hours) if hours is not None else None
    return {
        "id": str(uuid4()),
        "process_id": str(uuid4()),
        "process_name": name,
        "status": "in_progress",
        "started_at": started.isoformat() if started else None,
        "current_step": {"step_number": done + 1, "name": step},
        "steps": [{"step_number": n + 1, "status": "completed" if n < done else "pending"} for n in range(total)],
        "total_steps": total,
        "progress": done / total * 100,
    }


BATCHES = [
    _batch("Navy Strength Gin", "Macerate botanicals", 0, 3, 2),
    _batch("Limoncello", "Blend and sweeten", 1, 3, 190),
    _batch("Pink Gin", "Bottle and label", 3, 4, 120),
    _batch("Navy Strength Gin", "Distil", 1, 3, 27),
]


@pytest.fixture
def production_page(browser, app_url, fresh_user, db):
    """An admin's page on an org with stock, a workflow and a batch, so the page is past setup."""
    user = fresh_user(UserRole.ADMIN)
    org_id = UUID(user["org_id"])
    InventoryItemFactory(org_id=org_id, name="Juniper berries")
    process = ProcessFactory(org_id=org_id, name="Dry Gin")
    ExecutionFactory(org_id=org_id, process_id=process.id)
    db.commit()
    context = browser.new_context(base_url=app_url, ignore_https_errors=True, viewport={"width": 1440, "height": 900})
    page = context.new_page()
    attach_probe(page)
    login_through_ui(page, user["email"], user["password"])
    try:
        yield page
    finally:
        context.close()


def _serve(page, batches):
    def handle(route):
        response = route.fetch()
        body = response.json()
        body["workflows"]["active_executions"] = batches
        body["metrics"]["active_executions"] = len(batches)
        route.fulfill(response=response, json=body)

    page.route(OVERVIEW, handle)


def _open(page, style=None):
    page.goto("/core" + (f"?style={style}" if style else ""))
    expect(page.locator(".production-health__state")).to_be_visible()
    return page.get_by_role("region", name="Active production", exact=True)


def test_each_batch_shows_its_step_progress_and_age_longest_running_first(production_page):
    page = production_page
    _serve(page, BATCHES)
    active = _open(page)

    expect(active).to_contain_text("4 batches under way, longest running first.")
    rows = active.locator("[data-execution-id]")
    expect(rows).to_have_count(4)
    assert rows.locator(".prod-row__name").all_inner_texts() == [
        "Limoncello",
        "Pink Gin",
        "Navy Strength Gin",
        "Navy Strength Gin",
    ]
    first = rows.nth(0)
    expect(first).to_contain_text("Blend and sweeten")
    expect(first).to_contain_text("Step 2 of 3 · Started 8 days ago")
    expect(first.get_by_role("img", name="1 of 3 steps done")).to_be_visible()
    assert first.locator(".prod-progress span.is-done").count() == 1
    expect(rows.nth(3)).to_contain_text("Step 1 of 3 · Started 2 hours ago")
    # The two Navy Strength batches are told apart by their step, in the link's name too.
    expect(active.get_by_role("link", name="Record next step for Navy Strength Gin, Distil")).to_be_visible()
    expect(
        active.get_by_role("link", name="Record next step for Navy Strength Gin, Macerate botanicals")
    ).to_be_visible()

    glance = page.get_by_role("region", name="At a glance", exact=True)
    longest = glance.get_by_role("link", name=re.compile("Longest running"))
    expect(longest).to_contain_text("8 days")
    expect(longest).to_contain_text("Limoncello")
    expect(glance.get_by_role("link", name=re.compile("Active batches"))).to_contain_text("4")
    assert_clean_page(page)


def test_a_quiet_floor_says_so_and_a_clear_check_does_not_shout(production_page):
    page = production_page
    _serve(page, [])
    active = _open(page)

    expect(active).to_contain_text("No batches are active right now.")
    expect(active.locator("[data-production-active-caption]")).to_be_hidden()
    expect(page.get_by_role("region", name="At a glance", exact=True)).to_contain_text("no batches under way")
    checks = page.get_by_role("group", name="Operational status")
    expired = checks.get_by_role("link", name=re.compile("Expired stock"))
    expect(expired).to_contain_text("Nothing to do.")
    expect(expired).to_have_class(re.compile("prod-check--clear"))
    assert_clean_page(page)


def test_leaving_mid_load_is_not_reported_as_a_failure(production_page):
    page = production_page
    errors = []
    page.on("console", lambda message: errors.append(message.text) if message.type == "error" else None)
    # Hold the overview until the page has gone, then let the abort surface.
    page.route(OVERVIEW, lambda route: None)
    page.goto("/core")
    page.locator("#sidebar").get_by_role("link", name="Settings", exact=True).click()
    page.wait_for_url("**/core/settings")
    page.wait_for_timeout(300)
    assert not [text for text in errors if "Failed to load core overview" in text], errors


# ── CONCEPT ONLY: the three styles on offer. Delete with the two styles not chosen. ──


@pytest.mark.parametrize("style", ["1", "2", "3"])
@pytest.mark.parametrize("width", [390, 1024, 1440, 1920])
def test_every_style_shows_health_the_work_and_the_actions_without_sideways_scrolling(production_page, style, width):
    page = production_page
    page.set_viewport_size({"width": width, "height": 1080 if width == 1920 else 900})
    _serve(page, BATCHES)
    active = _open(page, style)

    expect(page.locator("[data-production-root]")).to_have_attribute("data-production-style", style)
    expect(page.get_by_role("button", name=f"Style {style}")).to_have_attribute("aria-pressed", "true")
    for name in ["Production health", "Active production", "At a glance", "Get to work"]:
        expect(page.get_by_role("region", name=name, exact=True)).to_be_visible()
    expect(active.locator("[data-execution-id]")).to_have_count(4)
    expect(active.get_by_role("link", name=re.compile("^Record next step"))).to_have_count(4)
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth + 1"), "scrolls sideways"
    assert_clean_page(page)


def test_the_line_sorts_batches_into_lanes_by_how_far_along_they_are(production_page):
    page = production_page
    _serve(page, BATCHES)
    active = _open(page, "2")

    lanes = {
        name: active.get_by_role("region", name=name, exact=True)
        for name in ["Not started", "In progress", "Last step"]
    }
    expect(lanes["Not started"].locator("[data-execution-id]")).to_have_count(1)
    expect(lanes["Not started"]).to_contain_text("Macerate botanicals")
    expect(lanes["In progress"].locator("[data-execution-id]")).to_have_count(2)
    expect(lanes["Last step"].locator("[data-execution-id]")).to_have_count(1)
    expect(lanes["Last step"]).to_contain_text("Pink Gin")
    boxes = [lane.bounding_box() for lane in lanes.values()]
    assert len({box["y"] for box in boxes}) == 1 and boxes[0]["x"] < boxes[1]["x"] < boxes[2]["x"]


def test_the_worklist_filters_by_stage_and_keeps_the_action_on_every_row(production_page):
    page = production_page
    _serve(page, BATCHES)
    active = _open(page, "3")

    expect(active.get_by_role("columnheader", name="Next step")).to_be_visible()
    expect(active.locator("tbody tr")).to_have_count(4)
    active.get_by_role("button", name=re.compile("^In progress")).click()
    expect(active.get_by_role("button", name=re.compile("^In progress"))).to_have_attribute("aria-pressed", "true")
    expect(active.get_by_role("button", name=re.compile("^In progress"))).to_be_focused()
    expect(active.locator("tbody tr")).to_have_count(2)
    expect(active.locator("tbody tr").get_by_role("link", name=re.compile("^Record next step"))).to_have_count(2)
    active.get_by_role("button", name=re.compile("^All")).click()
    expect(active.locator("tbody tr")).to_have_count(4)
