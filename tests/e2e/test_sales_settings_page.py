"""Sales settings in a browser: one load, a Save per section that saves only that section, a failed
load that hides the settings, the overview's "Map" link, and (CONCEPT ONLY) each layout's fit.

Requests are routed into the Flask test client (see test_crm_contact_sync_ui), and Xero is faked.
"""

from __future__ import annotations

import pytest
from playwright.sync_api import expect

from tests.e2e.test_crm_contact_sync_ui import client, sales_page, xero  # noqa: F401 -- fixture re-export
from tests.test_crm import db, org, user  # noqa: F401 -- fixture re-export

pytestmark = pytest.mark.e2e

PAGE = "https://crm.test/crm/configuration"
READY = ".sales-settings[aria-busy='false']"


def _open(page, style="1", width=1440, query=""):
    page.set_viewport_size({"width": width, "height": 900})
    page.goto(f"{PAGE}?style={style}{query}")
    page.locator(READY).wait_for()


def test_the_settings_load_once(xero, sales_page):  # noqa: F811
    # x-init="init()" on top of Alpine's own init() call loaded every setting twice.
    calls = []
    sales_page.on("request", lambda r: calls.append(r.url) if r.url.endswith("/traceability-config") else None)
    _open(sales_page)
    sales_page.wait_for_load_state("networkidle")
    assert len(calls) == 1, calls


def test_a_section_saves_only_itself(xero, sales_page, client):  # noqa: F811
    # All three Save buttons sent the whole form, so saving Tasks also saved a half-typed target.
    _open(sales_page)
    sales_page.locator("#ss-revenue-target").fill("42000")
    sales_page.locator("#ss-archive-days").fill("14")
    sales_page.locator("#tasks").get_by_role("button", name="Save").click()
    expect(sales_page.locator("#tasks .ss-saved")).to_have_text("Saved.")
    saved = client.get("/api/crm/traceability-config").get_json()
    assert saved["task_done_archive_days"] == 14
    assert saved["revenue_baseline_target_mtd"] is None
    # The unsaved target is still in its box, waiting for its own Save.
    expect(sales_page.locator("#ss-revenue-target")).to_have_value("42000")


def test_settings_that_did_not_load_cannot_be_saved_over(xero, sales_page):  # noqa: F811
    # The page used to show the defaults after a failed load, and saving them overwrote the real ones.
    sales_page.route(
        "**/api/crm/traceability-config",
        lambda route: route.fulfill(status=503, json={"error": "Sales settings could not load."}),
    )
    _open(sales_page)
    expect(sales_page.get_by_role("alert")).to_contain_text("Sales settings could not load.")
    expect(sales_page.locator("#matching")).to_be_hidden()
    sales_page.unroute("**/api/crm/traceability-config")
    sales_page.get_by_role("button", name="Try again").click()
    expect(sales_page.locator("#matching")).to_be_visible()


def test_the_overview_map_link_opens_the_form_for_that_line(xero, sales_page):  # noqa: F811
    _open(sales_page, query="&map=Wildflower%20Gin%20700ml")
    dialog = sales_page.get_by_role("dialog", name="Add a mapping")
    expect(dialog).to_be_visible()
    expect(dialog.locator("#ss-mapping-line")).to_have_value("Wildflower Gin 700ml")
    sales_page.keyboard.press("Escape")
    expect(dialog).to_be_hidden()


# CONCEPT ONLY: the next three are deleted with the two layouts not picked.
def test_read_first_shows_the_value_and_changes_it_in_place(xero, sales_page):  # noqa: F811
    _open(sales_page, style="3")
    tasks = sales_page.locator("#tasks")
    expect(tasks.locator(".ss-read")).to_contain_text("7 days")
    expect(tasks.locator("#ss-archive-days")).to_be_hidden()
    tasks.get_by_role("button", name="Change when finished tasks are archived").click()
    tasks.locator("#ss-archive-days").fill("10")
    tasks.get_by_role("button", name="Save").click()
    expect(tasks.locator(".ss-read")).to_contain_text("10 days")
    expect(tasks.locator("#ss-archive-days")).to_be_hidden()


def test_side_by_side_saves_every_changed_section_from_one_bar(xero, sales_page, client):  # noqa: F811
    _open(sales_page, style="2")
    bar = sales_page.get_by_role("region", name="Unsaved changes")
    expect(bar).to_be_hidden()
    sales_page.locator("#ss-revenue-target").fill("42000")
    sales_page.locator("#ss-archive-days").fill("21")
    expect(bar).to_contain_text("Unsaved changes to revenue and tasks")
    bar.get_by_role("button", name="Save changes").click()
    expect(bar).to_be_hidden()
    saved = client.get("/api/crm/traceability-config").get_json()
    assert (saved["revenue_baseline_target_mtd"], saved["task_done_archive_days"]) == (42000, 21)


@pytest.mark.parametrize("style", ["1", "2", "3"])
@pytest.mark.parametrize("width", [390, 1440, 1920], ids=["phone", "laptop", "wall"])
def test_each_layout_fits_without_sideways_scroll(xero, sales_page, style, width):  # noqa: F811
    _open(sales_page, style=style, width=width)
    assert sales_page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    for section in ("#xero", "#mappings", "#matching", "#customers", "#revenue", "#tasks"):
        expect(sales_page.locator(section)).to_be_visible()
