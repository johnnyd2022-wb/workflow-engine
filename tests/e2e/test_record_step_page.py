"""Record a production step (/core/record), the Production overview's main button.

A go-live UX blocker: from /core, recording any step takes one tap to the picker and one tap
to the step, and saving brings you back to the picker with the batch's next step on top.
"""

from __future__ import annotations

import json
import re
import time

import pytest
from playwright.sync_api import Page, expect

from tests.e2e.test_execution_flow import _add_step, _create_process, _start_execution

pytestmark = pytest.mark.e2e

READY = "[data-rs-workflows-section]:not([hidden])"


def _workflow(page: Page, steps=("Macerate", "Distil", "Bottle")) -> str:
    pid = _create_process(page, f"Picker gin {time.time()}", is_draft=False)
    for i, name in enumerate(steps):
        _add_step(page, pid, i + 1, name)
    return pid


def _open(page: Page):
    page.goto("/core/record")
    page.locator(READY).wait_for()


def test_a_batch_in_flight_is_one_tap_from_its_step_and_saving_comes_back(logged_in_page: Page):
    page = logged_in_page
    pid = _workflow(page)
    eid = _start_execution(page, pid)
    _open(page)
    row = page.locator(f".rs-batch[href*='execution_id={eid}']")
    expect(row).to_contain_text("Macerate")
    expect(row).to_contain_text("Step 1 of 3")

    row.click()
    page.wait_for_url(re.compile(r"/core/flows/batches/start"))
    crumbs = page.get_by_role("navigation", name="Breadcrumb")
    expect(crumbs.get_by_role("link", name="Record a production step")).to_have_attribute("href", "/core/record")

    page.locator("#batch-start-record-btn").click()
    page.locator("#batch-record-confirm-ok").click()
    page.wait_for_url(re.compile(rf"/core/record\?recorded={eid}"))
    notice = page.locator("[data-rs-recorded]")
    expect(notice).to_contain_text("Recorded.")
    expect(notice).to_contain_text("step 2 of 3: Distil")
    expect(notice.get_by_role("link", name="Record Distil")).to_have_attribute(
        "href", re.compile(f"execution_id={eid}")
    )
    # The batch just recorded leads the list, highlighted.
    expect(page.locator(".rs-batch").first).to_have_attribute("href", re.compile(f"execution_id={eid}"))
    expect(page.locator(".rs-batch").first).to_have_class(re.compile("is-recorded"))


def test_a_new_batch_is_one_tap_from_its_workflows_first_step(logged_in_page: Page):
    page = logged_in_page
    pid = _workflow(page, ("Steep", "Distil"))
    _open(page)
    tile = page.locator(f".rs-workflow[href*='id={pid}']")
    expect(tile).to_contain_text("2 steps · starts with Steep")
    tile.click()
    page.wait_for_url(re.compile(rf"/core/flows/batches/start\?draft=1&id={pid}"))
    expect(page.get_by_text("Starting new batch")).to_be_visible()


def test_no_batches_shows_only_the_start_list(logged_in_page: Page):
    page = logged_in_page
    page.route(
        "**/api/core/record-options",
        lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body='{"batches": [], "workflows": [{"process_id": "x", "name": "Gin", "step_count": 1, '
            '"first_step": "Distil", "in_flight": 0, "last_started_at": null, "href": "/core/flows"}]}',
        ),
    )
    _open(page)
    expect(page.locator("[data-rs-batches-section]")).to_be_hidden()
    expect(page.locator(".rs-workflow")).to_have_count(1)


def _options(page: Page, body: dict):
    page.route(
        "**/api/core/record-options*",
        lambda route: route.fulfill(status=200, content_type="application/json", body=json.dumps(body)),
    )


_ROW = {
    "process_id": "p",
    "workflow": "Gin",
    "label": None,
    "started_at": None,
    "step_number": 2,
    "step_total": 3,
    "waited_seconds": 30,
    "waiting": False,
    "last_by": None,
}
_TILE = {
    "process_id": "p",
    "name": "Gin",
    "step_count": 3,
    "first_step": "Steep",
    "in_flight": 2,
    "last_started_at": None,
    "href": "/core/flows",
}


def test_a_recorded_batch_outside_the_bounded_list_is_not_called_finished(logged_in_page: Page):
    """Review on !576: absence from the (bounded) list said "finished" while a step remained."""
    page = logged_in_page
    mine = {**_ROW, "execution_id": "new", "label": "GIN-042", "step_name": "Distil", "href": "/core/flows?mine"}
    _options(
        page,
        {
            "batches": [{**_ROW, "execution_id": "old", "step_name": "Steep", "href": "/core/flows?old"}],
            "batches_total": 2,
            "workflows": [_TILE],
            "workflows_total": 1,
            "recorded": {"execution_id": "new", "finished": False, "batch": mine},
        },
    )
    page.goto("/core/record?recorded=new")
    notice = page.locator("[data-rs-recorded]")
    expect(notice).to_contain_text("GIN-042 is now at step 2 of 3: Distil")
    expect(notice).not_to_contain_text("finished")
    expect(notice.get_by_role("link", name="Record Distil")).to_have_attribute("href", "/core/flows?mine")
    expect(page.locator(".rs-batch").first).to_have_attribute("href", "/core/flows?mine")
    expect(page.locator("[data-rs-batches-more]")).to_contain_text("Showing the oldest 1 of 2 batches in progress")


def test_a_batch_with_nothing_ready_is_not_called_finished_either(logged_in_page: Page):
    page = logged_in_page
    _options(
        page,
        {
            "batches": [],
            "batches_total": 0,
            "workflows": [_TILE],
            "workflows_total": 1,
            "recorded": {"execution_id": "new", "finished": False, "batch": None},
        },
    )
    page.goto("/core/record?recorded=new")
    notice = page.locator("[data-rs-recorded]")
    expect(notice).to_contain_text("no step ready to record yet")
    expect(notice).not_to_contain_text("finished")


def test_a_finished_batch_says_so(logged_in_page: Page):
    page = logged_in_page
    _options(
        page,
        {
            "batches": [],
            "batches_total": 0,
            "workflows": [_TILE],
            "workflows_total": 1,
            "recorded": {"execution_id": "new", "finished": True, "batch": None},
        },
    )
    page.goto("/core/record?recorded=new")
    expect(page.locator("[data-rs-recorded]")).to_contain_text("the batch is finished")


def test_a_long_workflow_list_can_be_searched_and_says_when_it_is_bounded(logged_in_page: Page):
    page = logged_in_page
    tiles = [{**_TILE, "process_id": str(i), "name": f"Workflow {i}", "href": f"/core/flows?{i}"} for i in range(8)]
    tiles.append({**_TILE, "process_id": "r", "name": "Rhubarb Liqueur", "href": "/core/flows?r"})
    _options(page, {"batches": [], "batches_total": 0, "workflows": tiles, "workflows_total": 240, "recorded": None})
    _open(page)
    expect(page.locator("[data-rs-workflows-more]")).to_contain_text(
        "Showing the most recently used 9 of 240 workflows"
    )
    expect(page.locator("[data-rs-workflows-more] a")).to_have_attribute("href", "/core/processes")
    page.locator("#rs-wsearch").fill("rhubarb")
    expect(page.locator(".rs-workflow")).to_have_count(1)
    expect(page.locator(".rs-workflow")).to_contain_text("Rhubarb Liqueur")


@pytest.mark.parametrize("width", [390, 1440, 1920])
def test_the_picker_fits_every_width(logged_in_page: Page, width):
    page = logged_in_page
    page.set_viewport_size({"width": width, "height": 900})
    _open(page)
    assert page.evaluate("document.documentElement.scrollWidth <= document.documentElement.clientWidth")
