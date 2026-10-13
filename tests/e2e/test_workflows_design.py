"""The Product workflows list says what each workflow is doing in words, running ones first."""

import pytest
from playwright.sync_api import expect

from tests.e2e.test_workspace_overviews import _page
from tests.e2e.test_workspace_overviews import workspace_user as _workspace_user

workspace_user = _workspace_user

pytestmark = pytest.mark.e2e


def _process(index, name, steps, active, made, draft=False):
    return {
        "id": f"00000000-0000-4000-8000-00000000000{index}",
        "name": name,
        "step_count": steps,
        "active_executions": active,
        "completed_executions": made,
        "is_draft": draft,
        # Two runs, none finished: the old row called this "0% success".
        "event_summary": {"current_version": 4, "total_runs": active + made, "completed_runs": made},
    }


PROCESSES = {
    "processes": [
        _process(1, "Dry Gin", 3, 0, 2),
        _process(2, "Limoncello", 3, 2, 0),
        _process(3, "Navy Strength Gin", 3, 3, 1),
        _process(4, "Spiced Rum trial", 1, 0, 0, draft=True),
    ]
}


def _open(page, style="1", payload=None):
    page.route("**/api/core/processes", lambda route: route.fulfill(json=PROCESSES if payload is None else payload))
    page.goto(f"/core/processes?style={style}")
    expect(page.locator("#processes-list-loading")).to_be_hidden()


def test_rows_lead_with_what_is_running_and_say_it_in_words(browser, app_url, workspace_user):
    context, page = _page(browser, app_url, workspace_user, 1440)
    try:
        _open(page)
        rows = page.locator(".processes-list-item")
        expect(rows.locator(".processes-list-item__name")).to_have_text(
            ["Navy Strength Gin", "Limoncello", "Dry Gin", "Spiced Rum trial"]
        )
        expect(rows.locator(".workflows-state")).to_have_text(["3 under way", "2 under way", "Not running", "Draft"])
        expect(rows.nth(0)).to_have_attribute("data-state", "running")
        expect(rows.nth(0).locator(".processes-list-item__meta")).to_have_text("3 steps · 1 batch made")
        # A workflow whose batches are still under way has not failed: no "0% success" beside it.
        assert "success" not in page.locator(".processes-list-page").inner_text()
        expect(rows.nth(0).locator("a.processes-list-item__open")).to_have_attribute(
            "href", "/core/flows?id=00000000-0000-4000-8000-000000000003"
        )
        expect(page.locator(".workspace-header .workspace-button--primary:visible")).to_have_count(1)
    finally:
        context.close()


def test_figures_count_live_workflows_and_batches(browser, app_url, workspace_user):
    context, page = _page(browser, app_url, workspace_user, 1440)
    try:
        _open(page)
        expect(page.locator("[data-figure-total]")).to_have_text("3")
        expect(page.locator("[data-figure-total-note]")).to_have_text("ready to run · 1 draft")
        expect(page.locator("[data-figure-active]")).to_have_text("5")
        expect(page.locator("[data-figure-active-note]")).to_have_text("across 2 workflows")
        expect(page.locator("[data-figure-made]")).to_have_text("3")
        running = page.get_by_role("region", name="In production now", exact=True)
        expect(running.locator("li")).to_have_text(["Navy Strength Gin3 batches", "Limoncello2 batches"])
    finally:
        context.close()


def test_search_narrows_the_list_and_a_miss_offers_no_create(browser, app_url, workspace_user):
    context, page = _page(browser, app_url, workspace_user, 1440)
    try:
        _open(page)
        search = page.get_by_role("searchbox", name="Find a workflow")
        assert search.bounding_box()["width"] <= 342
        search.fill("gin")
        expect(page.locator(".processes-list-item")).to_have_count(2)
        expect(page.locator("#processes-list-count")).to_have_text("Showing 2 of 4 workflows")
        search.fill("no such product")
        expect(page.get_by_text("No workflows match that search", exact=True)).to_be_visible()
        expect(page.locator("[data-empty-create]")).to_be_hidden()
        search.fill("")
        expect(page.locator(".processes-list-item")).to_have_count(4)
    finally:
        context.close()


def test_no_workflows_shows_one_next_step_and_no_figures(browser, app_url, workspace_user):
    context, page = _page(browser, app_url, workspace_user, 1440)
    try:
        _open(page, payload={"processes": []})
        expect(page.get_by_text("No product workflows yet", exact=True)).to_be_visible()
        expect(page.locator("[data-empty-create]")).to_have_attribute("href", "/core/flows/create/start")
        expect(page.get_by_role("region", name="At a glance", exact=True)).to_be_hidden()
        expect(page.get_by_role("region", name="In production now", exact=True)).to_be_hidden()
        expect(page.get_by_role("searchbox", name="Find a workflow")).to_be_hidden()
    finally:
        context.close()


def test_failed_load_is_not_an_empty_list_and_retry_recovers(browser, app_url, workspace_user):
    context, page = _page(browser, app_url, workspace_user, 1440)
    try:
        page.route("**/api/core/processes", lambda route: route.fulfill(status=503, json={"error": "Unavailable"}))
        page.goto("/core/processes")
        expect(page.get_by_text("Product workflows could not load.", exact=True)).to_be_visible()
        expect(page.get_by_text("No product workflows yet", exact=True)).to_be_hidden()
        expect(page.get_by_role("region", name="At a glance", exact=True)).to_be_hidden()
        page.unroute("**/api/core/processes")
        page.route("**/api/core/processes", lambda route: route.fulfill(json=PROCESSES))
        page.get_by_role("button", name="Try again", exact=True).click()
        expect(page.locator(".processes-list-item")).to_have_count(4)
        expect(page.locator("[data-figure-active]")).to_have_text("5")
    finally:
        context.close()


def test_list_loads_again_after_leaving_by_a_tab_and_returning(browser, app_url, workspace_user):
    context, page = _page(browser, app_url, workspace_user, 1440)
    try:
        _open(page)
        page.evaluate("window.__workflowsSentinel = true")
        page.get_by_role("tab", name="Planner", exact=True).click()
        expect(page.locator(".workspace-header h1")).to_have_text("Planner")
        page.get_by_role("tab", name="Workflows", exact=True).click()
        expect(page.locator(".processes-list-item")).to_have_count(4)
        expect(page.locator("[data-figure-total]")).to_have_text("3")
        assert page.evaluate("window.__workflowsSentinel"), "must be an in-app swap, not a full load"
    finally:
        context.close()


# CONCEPT ONLY — delete with the preview switch and the two layouts not chosen.
@pytest.mark.parametrize("style", ["1", "2", "3"])
@pytest.mark.parametrize("width", [390, 1024, 1440, 1920])
def test_concepts_fit_and_keep_every_workflow(browser, app_url, workspace_user, style, width):
    context, page = _page(browser, app_url, workspace_user, width)
    try:
        _open(page, style)
        expect(page.locator(".processes-list-page")).to_have_attribute("data-workflows-style", style)
        rows = page.locator(".processes-list-item")
        expect(rows).to_have_count(4)
        expect(page.locator(".workflows-state:visible")).to_have_count(4)
        expect(page.locator(".processes-list-item__history-btn:visible")).to_have_count(4)
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1")
        card = page.locator(".processes-list-hero").bounding_box()
        for row in rows.all():
            box = row.bounding_box()
            assert box["x"] >= card["x"] and box["x"] + box["width"] <= card["x"] + card["width"] + 1
    finally:
        context.close()


# CONCEPT ONLY
def test_each_concept_arranges_the_same_workflows_its_own_way(browser, app_url, workspace_user):
    context, page = _page(browser, app_url, workspace_user, 1440)
    try:
        _open(page, "1")
        rows = page.locator(".processes-list-item")
        expect(page.locator("[data-workflows-brief]")).to_be_hidden()
        assert rows.nth(1).bounding_box()["y"] > rows.nth(0).bounding_box()["y"]  # one per line
        page.get_by_role("button", name="2 · Catalogue", exact=True).click()
        expect(page.get_by_role("region", name="At a glance", exact=True)).to_be_hidden()
        expect(page.locator("[data-workflows-brief]")).to_have_text(
            "3 product workflows: 5 batches under way across 2, 3 batches made, 1 draft."
        )
        assert abs(rows.nth(1).bounding_box()["y"] - rows.nth(0).bounding_box()["y"]) < 2  # cards side by side
        page.get_by_role("button", name="3 · Register", exact=True).click()
        header = page.locator(".workflows-columns")
        expect(header).to_be_visible()
        # Each column heading ends where its figures end.
        made_heading = header.locator("span").nth(3).bounding_box()
        made_cell = rows.nth(0).locator(".workflows-cell").nth(1).bounding_box()
        assert abs((made_heading["x"] + made_heading["width"]) - (made_cell["x"] + made_cell["width"])) < 2
        expect(rows.nth(0).locator(".workflows-cell")).to_have_text(["3", "1"])
    finally:
        context.close()
