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
    return page.get_by_role("region", name="Under way", exact=True)  # GLASS: mockup 22 names it Under way


def test_each_batch_shows_its_step_progress_and_age_longest_running_first(production_page):
    page = production_page
    _serve(page, BATCHES)
    active = _open(page)

    expect(active).to_contain_text("4 batches, longest running first.")
    rows = active.locator("[data-execution-id]")
    expect(rows).to_have_count(4)
    assert rows.locator(".gpo-prod b").all_inner_texts() == [
        "Limoncello",
        "Pink Gin",
        "Navy Strength Gin",
        "Navy Strength Gin",
    ]
    first = rows.nth(0)
    expect(first).to_contain_text("Blend and sweeten")
    expect(first).to_contain_text("Step 2 of 3")
    expect(first).to_contain_text("8 days running")
    expect(first.get_by_role("img", name="1 of 3 steps done")).to_be_visible()
    expect(rows.nth(3)).to_contain_text("Step 1 of 3")
    expect(rows.nth(3)).to_contain_text("0 days running")
    # The two Navy Strength batches are told apart by their step, in the link's name too.
    expect(active.get_by_role("link", name=re.compile(r"^Record distil for Navy Strength Gin"))).to_be_visible()
    expect(
        active.get_by_role("link", name=re.compile(r"^Record macerate botanicals for Navy Strength Gin"))
    ).to_be_visible()

    today = page.get_by_role("region", name="In progress", exact=True)
    longest = today.get_by_role("link", name=re.compile("longest running"))
    expect(longest).to_contain_text("8 days")
    expect(longest).to_contain_text("Limoncello")
    expect(today).to_contain_text("4 batches")
    # Filtering by step shows only the batches at that step.
    today.get_by_role("button", name=re.compile("^Distil")).click()
    expect(rows.filter(visible=True)).to_have_count(1)
    expect(active).to_contain_text("1 batch at distil")
    assert_clean_page(page)


def test_a_quiet_floor_says_so_and_a_clear_check_does_not_shout(production_page):
    page = production_page
    _serve(page, [])
    active = _open(page)

    expect(active).to_contain_text("No batches are under way right now.")
    expect(page.get_by_role("region", name="In progress", exact=True)).to_contain_text("no batches under way")
    checks = page.get_by_role("group", name="Operational status")
    expired = checks.get_by_role("link", name=re.compile("Expired stock"))
    expect(expired).to_contain_text("None expired")
    expect(expired).to_have_class(re.compile("gpo-t-clear"))
    assert_clean_page(page)


def test_leaving_mid_load_is_not_reported_as_a_failure(production_page):
    page = production_page
    errors = []
    page.on("console", lambda message: errors.append(message.text) if message.type == "error" else None)
    # Hold the overview until the page has gone, then let the abort surface.
    page.route(OVERVIEW, lambda route: None)
    page.goto("/core")
    page.locator(".g-top").get_by_role("link", name="Settings", exact=True).click()  # GLASS: top bar, no sidebar
    page.wait_for_url("**/core/settings")
    page.wait_for_timeout(300)
    assert not [text for text in errors if "Failed to load core overview" in text], errors


def test_recording_production_is_the_main_action_and_is_drawn_as_one(production_page):
    page = production_page
    _serve(page, BATCHES)
    _open(page)

    work = page.get_by_role("group", name="Get to work", exact=True)  # GLASS: in the greeting bar
    main = work.get_by_role("link", name="Record production step")
    expect(main).to_have_attribute("href", "/core/record")  # the step picker, not the workflow list
    solid = main.evaluate("el => getComputedStyle(el).backgroundColor")
    for name in ["Trace and recall"]:
        other = work.get_by_role("link", name=name)
        expect(other).to_be_visible()
        assert other.evaluate("el => getComputedStyle(el).backgroundColor") != solid, "only the main action is filled"
    assert solid not in ("rgba(0, 0, 0, 0)", "rgb(255, 255, 255)")
    work.get_by_role("button", name="Add to inventory, choose how").click()
    expect(work.get_by_role("menuitem", name="Manual entry", exact=True)).to_be_visible()
    page.keyboard.press("Escape")


# ── The section head: the title, the tabs on a divider, and the main buttons on the tab row. ──


def _head(page):
    title = page.get_by_role("heading", name="Production", exact=True, level=1)
    tabs = page.get_by_role("navigation", name="Production sections", exact=True)
    return title, tabs, page.locator(".section-head__row")


@pytest.mark.parametrize("width", [390, 1024, 1440, 1920])
def test_the_page_opens_with_its_title_then_the_tabs_then_the_board(production_page, width):
    page = production_page
    page.set_viewport_size({"width": width, "height": 1080 if width == 1920 else 900})
    _serve(page, BATCHES)
    _open(page)
    title, tabs, row = _head(page)

    expect(title).to_be_visible()
    expect(page.locator("#page-content h1:visible")).to_have_count(1)
    expect(page.locator("#core2-hub-caption")).to_be_hidden()
    expect(tabs.get_by_role("tab")).to_have_count(5)  # GLASS: Tasks is a tab
    health = page.get_by_role("region", name="Production health", exact=True)
    tops = [title.bounding_box()["y"], tabs.bounding_box()["y"], health.bounding_box()["y"]]
    assert tops == sorted(tops)

    work = page.get_by_role("group", name="Get to work", exact=True)  # GLASS: in the greeting bar
    main = work.get_by_role("link", name="Record production step")
    expect(main).to_be_in_viewport()
    boxes = [main.bounding_box(), work.get_by_role("link", name="Trace and recall").bounding_box()]
    boxes.append(work.get_by_role("button", name="Add to inventory, choose how").bounding_box())
    tab_boxes = [tab.bounding_box() for tab in tabs.get_by_role("tab").all()]
    for index, one in enumerate(boxes + tab_boxes):
        for other in (boxes + tab_boxes)[index + 1 :]:
            apart = (
                one["x"] + one["width"] <= other["x"] + 1
                or other["x"] + other["width"] <= one["x"] + 1
                or one["y"] + one["height"] <= other["y"] + 1
                or other["y"] + other["height"] <= one["y"] + 1
            )
            assert apart, (one, other)

    # GLASS: the buttons sit in the greeting bar under the tabs at every width, above the board.
    tabs_bottom = tabs.bounding_box()["y"] + tabs.bounding_box()["height"]
    assert all(box["y"] >= tabs_bottom for box in boxes)
    assert all(box["y"] + box["height"] <= health.bounding_box()["y"] for box in boxes)
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth + 1"), "scrolls sideways"
    assert_clean_page(page)


def test_the_current_tab_is_marked_by_colour_weight_and_its_own_surface(production_page):
    # GLASS: the tabs are a segmented switch; the current one is a solid pill, not an underline.
    page = production_page
    _serve(page, BATCHES)
    _open(page)
    _title, tabs, _row = _head(page)
    current = tabs.get_by_role("tab", name="Overview", exact=True)
    other = tabs.get_by_role("tab", name="Planner", exact=True)

    def style(tab, prop):
        return tab.evaluate("(el, prop) => getComputedStyle(el)[prop]", prop)

    expect(current).to_have_attribute("aria-selected", "true")
    assert style(current, "backgroundColor") != style(other, "backgroundColor")
    assert style(current, "color") != style(other, "color")
    boxes = [tab.bounding_box() for tab in tabs.get_by_role("tab").all()]
    for left, right in zip(boxes, boxes[1:], strict=False):
        assert left["x"] + left["width"] <= right["x"] + 0.5


def test_other_production_pages_show_the_section_then_the_tabs_then_their_own_title(production_page):
    page = production_page
    _serve(page, BATCHES)
    _open(page)
    tabs_at = page.get_by_role("tab", name="Overview", exact=True).bounding_box()

    page.get_by_role("tab", name="Workflows", exact=True).click()
    page.wait_for_url(re.compile(r"/core/processes"))
    own = page.get_by_role("heading", name="Workflows", exact=True, level=1)
    expect(own).to_be_visible()
    expect(page.locator("#page-content h1:visible")).to_have_count(1)
    name = page.locator(".section-head__title")
    expect(name).to_have_text("Production")
    current = page.get_by_role("tab", name="Workflows", exact=True)
    expect(current).to_have_attribute("aria-selected", "true")
    here = page.get_by_role("tab", name="Overview", exact=True).bounding_box()
    # The tabs keep their place across; GLASS: the overview's larger title moves them down a little.
    assert abs(here["x"] - tabs_at["x"]) < 1
    assert name.bounding_box()["y"] < here["y"] < own.bounding_box()["y"]
    expect(page.locator(".section-head__actions")).to_have_count(0)

    page.get_by_role("tab", name="Overview", exact=True).click()
    page.wait_for_url(re.compile(r"/core/?$"))
    expect(page.locator(".production-health__state")).to_be_visible()
    expect(page.locator("#page-content h1:visible")).to_have_text("Production")
    work = page.get_by_role("group", name="Get to work", exact=True)  # GLASS: the greeting bar
    expect(work.get_by_role("link", name="Record production step")).to_be_visible()
