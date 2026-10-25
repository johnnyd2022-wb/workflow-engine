"""Sales → Tasks in a browser: due dates on the local day, one load, lanes once, ticking a task
done, and each view at phone, laptop and wall widths."""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from playwright.sync_api import expect

from app.core.db.models.user import UserRole
from tests.e2e.conftest import csrf_headers, login_through_ui

pytestmark = pytest.mark.e2e

TASKS = "/crm/tasks"
READY = "#tasks-page[aria-busy='false']"
NZ = "Pacific/Auckland"


@pytest.fixture()
def sales_user(fresh_user):
    return fresh_user(UserRole.ADMIN)


def _page(browser, app_url, user, width=1440, timezone=NZ):
    context = browser.new_context(
        base_url=app_url, ignore_https_errors=True, viewport={"width": width, "height": 900}, timezone_id=timezone
    )
    page = context.new_page()
    login_through_ui(page, user["email"], user["password"])
    return context, page


def _task(page, title, days=None, **extra):
    body = {"title": title, **extra}
    if days is not None:
        body["due_date"] = (datetime.now(ZoneInfo(NZ)).date() + timedelta(days=days)).isoformat()
    resp = page.request.post("/api/crm/tasks", headers=csrf_headers(page), data=body)
    assert resp.status == 201, resp.text()
    return resp.json()["task"]


def _open(page, style, query=""):
    page.goto(f"{TASKS}?style={style}{query}")
    page.locator(READY).wait_for()


def test_a_task_due_today_is_under_today_on_a_new_zealand_clock(browser, app_url, sales_user):
    # toISOString() gave the UTC date, the day before in New Zealand until 1pm.
    context, page = _page(browser, app_url, sales_user)
    try:
        _task(page, "Confirm the Christmas order", days=0)
        _task(page, "Drop off a tasting kit", days=1)
        _open(page, "2")
        expect(page.locator(".tasks-group--today .tasks-row__title")).to_have_text(["Confirm the Christmas order"])
        expect(page.locator(".tasks-group--tomorrow .tasks-row__title")).to_have_text(["Drop off a tasting kit"])
        _open(page, "3")
        expect(page.locator(".tasks-day--today .tasks-card__title")).to_have_text(["Confirm the Christmas order"])
    finally:
        context.close()


def test_the_page_asks_for_its_tasks_and_lanes_once(browser, app_url, sales_user):
    # x-init="init()" on top of Alpine's own init() call loaded everything twice.
    context, page = _page(browser, app_url, sales_user)
    try:
        calls = []
        page.on("request", lambda r: calls.append(r.url.split("?")[0]) if "/api/crm/tasks" in r.url else None)
        _open(page, "1")
        page.wait_for_load_state("networkidle")
        assert sum(url.endswith("/api/crm/tasks") for url in calls) == 1, calls
        assert sum(url.endswith("/api/crm/tasks/lanes") for url in calls) == 1, calls
    finally:
        context.close()


def test_a_custom_lane_shows_once_with_its_tasks(browser, app_url, sales_user):
    context, page = _page(browser, app_url, sales_user)
    try:
        lane = page.request.post(
            "/api/crm/tasks/lanes", headers=csrf_headers(page), data={"title": "Waiting on customer"}
        )
        assert lane.status == 201, lane.text()
        task = _task(page, "Signed credit application", days=3)
        moved = page.request.put(
            f"/api/crm/tasks/{task['id']}/lane", headers=csrf_headers(page), data={"lane_id": lane.json()["lane"]["id"]}
        )
        assert moved.ok, moved.text()
        _open(page, "1")
        lanes = page.locator(".tasks-lane", has_text="Waiting on customer")
        expect(lanes).to_have_count(1)
        expect(lanes.locator(".tasks-card__title")).to_have_text(["Signed credit application"])
    finally:
        context.close()


def test_ticking_a_task_done_moves_it_to_finished(browser, app_url, sales_user):
    context, page = _page(browser, app_url, sales_user)
    try:
        _task(page, "Send the price list", days=0)
        _open(page, "2")
        page.get_by_role("button", name="Mark done: Send the price list").click()
        expect(page.locator(".tasks-group--today")).to_have_count(0)
        expect(page.locator(".tasks-summary")).to_have_text("0 open")
        page.get_by_role("button", name="Show finished (1)").click()
        expect(page.locator(".tasks-group--finished .tasks-row--done")).to_contain_text("Done today")
    finally:
        context.close()


def test_new_task_opens_from_the_header_and_from_the_overview_link(browser, app_url, sales_user):
    context, page = _page(browser, app_url, sales_user)
    try:
        _open(page, "1", "&new=1")
        expect(page.locator(".crm-task-sheet__title")).to_have_text("New task")
        page.get_by_role("button", name="Cancel").click()
        page.locator("[data-new-task]").click()
        page.locator("#task-title").fill("Book a staff tasting")
        page.get_by_role("button", name="Create task").click()
        expect(page.locator(".tasks-card__title", has_text="Book a staff tasting")).to_be_visible()
    finally:
        context.close()


# Each supported view must fit at every target width.
@pytest.mark.parametrize("style", ["1", "2", "3"])
@pytest.mark.parametrize("width", [390, 1440, 1920], ids=["phone", "laptop", "wall"])
def test_each_layout_fits_without_sideways_scroll(browser, app_url, sales_user, style, width):
    context, page = _page(browser, app_url, sales_user, width)
    try:
        for days, title in (
            (-2, "Call about the reorder"),
            (0, "Confirm the order"),
            (4, "Quote for gift packs"),
            (None, "Newsletter"),
        ):
            _task(page, title, days=days, priority="high" if days == -2 else "medium")
        _open(page, style)
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        region = {"1": ".tasks-board", "2": ".tasks-list", "3": ".tasks-week"}[style]
        expect(page.locator(region)).to_be_visible()
        expect(page.get_by_text("Call about the reorder").first).to_be_visible()
    finally:
        context.close()


def test_view_switch_remembers_choice_and_preserves_filters(browser, app_url, sales_user):
    context, page = _page(browser, app_url, sales_user)
    try:
        _task(page, "Keep the reorder", days=0)
        _task(page, "Other work", days=0)
        page.goto(TASKS)
        page.locator(READY).wait_for()
        switch = page.get_by_role("group", name="Task view")
        expect(switch.get_by_role("button", name="Board", exact=True)).to_have_attribute("aria-pressed", "true")
        page.get_by_role("searchbox", name="Search tasks").fill("Keep")
        for label, region in (("List", ".tasks-list"), ("Week", ".tasks-week"), ("Board", ".tasks-board")):
            switch.get_by_role("button", name=label, exact=True).click()
            expect(switch.get_by_role("button", name=label, exact=True)).to_have_attribute("aria-pressed", "true")
            expect(page.locator(region)).to_be_visible()
            expect(page.get_by_role("searchbox", name="Search tasks")).to_have_value("Keep")
            expect(page.locator(region)).to_contain_text("Keep the reorder")
            expect(page.locator(region)).not_to_contain_text("Other work")
        switch.get_by_role("button", name="Week", exact=True).click()
        page.reload()
        page.locator(READY).wait_for()
        expect(page.locator(".tasks-week")).to_be_visible()
        expect(switch.get_by_role("button", name="Week", exact=True)).to_have_attribute("aria-pressed", "true")
    finally:
        context.close()
