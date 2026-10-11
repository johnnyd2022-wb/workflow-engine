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


def test_recording_production_is_the_main_action_and_is_drawn_as_one(production_page):
    page = production_page
    _serve(page, BATCHES)
    _open(page)

    work = page.get_by_role("region", name="Get to work", exact=True)
    main = work.get_by_role("link", name="Record production step")
    expect(main).to_have_attribute("href", "/core/processes")
    solid = main.evaluate("el => getComputedStyle(el).backgroundColor")
    for name in ["Trace and recall"]:
        other = work.get_by_role("link", name=name)
        expect(other).to_be_visible()
        assert other.evaluate("el => getComputedStyle(el).backgroundColor") != solid, "only the main action is filled"
    assert solid not in ("rgba(0, 0, 0, 0)", "rgb(255, 255, 255)")
    work.get_by_role("button", name="Add to inventory, choose how").click()
    expect(work.get_by_role("menuitem", name="Manual entry", exact=True)).to_be_visible()
    page.keyboard.press("Escape")


# ── CONCEPT ONLY: round-four mock-ups A to E. Delete with the ones not chosen. ──

MOCKS = {
    "a": ("line", "left", "inline"),
    "b": ("line", "left", "below"),
    "c": ("line", "center", "below"),
    "d": ("pill", "left", "inline"),
    "e": ("pill", "center", "below"),
}


def _open_mock(page, mock):
    page.goto(f"/core?mock={mock}")
    expect(page.locator(".production-health__state")).to_be_visible()
    return page.get_by_role("region", name="Get to work", exact=True)


@pytest.mark.parametrize("mock", list(MOCKS))
@pytest.mark.parametrize("width", [390, 1024, 1440, 1920])
def test_every_mock_up_has_title_then_tabs_then_the_board_with_the_actions_in_reach(production_page, mock, width):
    page = production_page
    page.set_viewport_size({"width": width, "height": 1080 if width == 1920 else 900})
    _serve(page, BATCHES)
    work = _open_mock(page, mock)

    title = page.get_by_role("heading", name="Production", exact=True, level=1)
    expect(title).to_be_visible()
    expect(page.locator("#core2-hub-caption")).to_be_hidden()
    tabs = page.get_by_role("navigation", name="Production sections", exact=True)
    expect(tabs).to_have_count(1)
    expect(tabs.get_by_role("tab")).to_have_count(4)
    health = page.get_by_role("region", name="Production health", exact=True)
    tops = [title.bounding_box()["y"], tabs.bounding_box()["y"], health.bounding_box()["y"]]
    assert tops == sorted(tops), "title, then tabs, then the board"

    main = work.get_by_role("link", name="Record production step")
    expect(main).to_be_in_viewport()
    boxes = [main.bounding_box(), work.get_by_role("link", name="Trace and recall").bounding_box()]
    boxes.append(work.get_by_role("button", name="Add to inventory, choose how").bounding_box())
    boxes += [tab.bounding_box() for tab in tabs.get_by_role("tab").all()]
    for index, one in enumerate(boxes):
        for other in boxes[index + 1 :]:
            apart = (
                one["x"] + one["width"] <= other["x"] + 1
                or other["x"] + other["width"] <= one["x"] + 1
                or one["y"] + one["height"] <= other["y"] + 1
                or other["y"] + other["height"] <= one["y"] + 1
            )
            assert apart, (one, other)
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth + 1"), "scrolls sideways"
    assert_clean_page(page)


@pytest.mark.parametrize("mock", list(MOCKS))
def test_each_mock_up_draws_and_places_the_tabs_and_buttons_as_it_says(production_page, mock):
    page = production_page
    _serve(page, BATCHES)
    work = _open_mock(page, mock)
    style, align, cta = MOCKS[mock]

    row = page.locator("[data-production-tabrow]")
    tabs = page.get_by_role("tab")
    current = page.get_by_role("tab", name="Overview", exact=True)
    other = page.get_by_role("tab", name="Planner", exact=True)
    expect(current).to_have_attribute("aria-selected", "true")
    fill = current.evaluate("el => getComputedStyle(el).backgroundColor")
    bar = current.evaluate("el => getComputedStyle(el).borderBottomColor")
    if style == "line":
        # Marked twice, neither of them a fill: a bar under it and a heavier label.
        assert fill == "rgba(0, 0, 0, 0)" and bar != other.evaluate("el => getComputedStyle(el).borderBottomColor")
        assert int(current.evaluate("el => getComputedStyle(el).fontWeight")) > int(
            other.evaluate("el => getComputedStyle(el).fontWeight")
        )
        assert row.evaluate("el => getComputedStyle(el).borderBottomWidth") == "1px", "a divider under the tabs"
        bottom = current.bounding_box()["y"] + current.bounding_box()["height"]
        edge = row.bounding_box()["y"] + row.bounding_box()["height"]
        assert abs(bottom - edge) <= 1, "the current tab's bar sits on the divider"
    else:
        assert (
            fill != "rgba(0, 0, 0, 0)"
            and other.evaluate("el => getComputedStyle(el).backgroundColor") == "rgba(0, 0, 0, 0)"
        )

    box = row.bounding_box()
    first, last = tabs.first.bounding_box(), tabs.last.bounding_box()
    left, right = first["x"] - box["x"], box["x"] + box["width"] - (last["x"] + last["width"])
    if align == "left":
        assert left < 8 and right > 200
    else:
        assert abs(left - right) < 12 and left > 150

    main = work.get_by_role("link", name="Record production step").bounding_box()
    if cta == "inline":
        # On the tab row, at its right edge.
        assert box["y"] <= main["y"] and main["y"] + main["height"] <= box["y"] + box["height"]
        assert abs(box["x"] + box["width"] - (main["x"] + main["width"])) < 2
    else:
        # On the row beneath, starting at the page's left edge.
        assert main["y"] >= box["y"] + box["height"] and abs(main["x"] - box["x"]) < 2


def test_the_tabs_still_take_you_places_and_the_arrangement_survives_the_trip(production_page):
    page = production_page
    _serve(page, BATCHES)
    _open_mock(page, "a")
    page.get_by_role("button", name="A", exact=True).click()  # remembered, as the switch does

    page.get_by_role("tab", name="Workflows", exact=True).click()
    page.wait_for_url(re.compile(r"/core/processes"))
    page.locator("#sidebar").get_by_role("link", name="Production", exact=True).click()
    page.wait_for_url(re.compile(r"/core/?$"))
    expect(page.locator(".production-health__state")).to_be_visible()
    row = page.locator("[data-production-tabrow]")
    expect(row.get_by_role("navigation", name="Production sections", exact=True)).to_have_count(1)
    expect(row.get_by_role("link", name="Record production step")).to_be_visible()
    page.evaluate("localStorage.removeItem('production.mock')")
