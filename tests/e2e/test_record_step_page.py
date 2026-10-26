"""Record a production step (/core/record), the Production overview's main button.

A go-live UX blocker: from /core, recording any step takes one tap to the picker and one tap
to the step, and saving brings you back to the picker with the batch's next step on top.
"""

from __future__ import annotations

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


@pytest.mark.parametrize("width", [390, 1440, 1920])
def test_the_picker_fits_every_width(logged_in_page: Page, width):
    page = logged_in_page
    page.set_viewport_size({"width": width, "height": 900})
    _open(page)
    assert page.evaluate("document.documentElement.scrollWidth <= document.documentElement.clientWidth")
