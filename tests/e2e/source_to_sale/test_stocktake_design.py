"""The Stocktake page's redesign (docs/stocktake-redesign-plan.md): what home leads with, the
open count as the primary action, the schedule keeping its tolerance, the count view's filters,
the reconciliation on a phone, and the three CONCEPT ONLY layouts."""

import pytest
from playwright.sync_api import expect

from tests.e2e.source_to_sale.conftest import BATCH, PRODUCT

pytestmark = pytest.mark.e2e


def _home(page, query=""):
    page.goto("/core/stocktake" + query)
    expect(page.locator("[data-st-position] table").first).to_be_visible()


def test_an_open_count_is_the_primary_action_and_home_says_what_is_due(alcohol_scenario):
    page = alcohol_scenario["page"]
    _home(page)
    expect(page.get_by_role("button", name="Start stocktake")).to_be_visible()
    expect(page.locator("[data-st-continue]")).to_be_hidden()
    expect(page.locator('[data-st-figure="counting"]')).to_have_text("None")
    expect(page.locator('[data-st-figure="lines"]')).to_have_text("1")

    page.get_by_role("button", name="Start stocktake").click()
    expect(page.locator(f".st-line:has-text('{BATCH}')")).to_be_visible()
    page.get_by_role("button", name="Back to stocktakes").click()
    # While a count is open, home leads back to it and does not offer a second scheduled count
    # (that would count the same stock twice); the inspector's visit can still start one.
    expect(page.get_by_role("button", name="Continue stocktake")).to_be_visible()
    expect(page.get_by_role("button", name="Start stocktake")).to_be_hidden()
    expect(page.get_by_role("button", name="Customs is here")).to_be_visible()
    expect(page.locator('[data-st-tile="counting"]')).to_have_attribute("data-state", "warn")
    page.get_by_role("button", name="Continue stocktake").click()
    expect(page.locator("[data-st-count-title]")).to_contain_text("Stocktake")


def test_saving_how_often_to_count_keeps_the_bulk_tolerance(alcohol_scenario):
    """Regression: the form never showed the tolerance and sent none, so changing the
    frequency reset a custom tolerance to the 0.5% default."""
    page = alcohol_scenario["page"]
    _home(page)
    page.locator("[data-st-schedule-form] summary").click()
    page.locator("[data-st-tolerance]").fill("1.5")
    page.locator("[data-st-save-schedule]").click()
    expect(page.locator("[data-st-message]")).to_have_text("Schedule saved.")
    expect(page.locator("[data-st-tolerance]")).to_have_value("1.5")

    page.locator("[data-st-frequency]").select_option("quarterly")
    page.locator("[data-st-save-schedule]").click()
    expect(page.locator("[data-st-schedule-text]")).to_contain_text("Count every quarter.")
    expect(page.locator("[data-st-tolerance]")).to_have_value("1.5")
    schedule = page.request.get("/api/core/stocktakes").json()["schedule"]
    assert schedule["frequency"] == "quarterly" and schedule["bulk_tolerance_percent"] == "1.5"


def test_count_filters_show_what_is_left_and_the_reconciliation_reads_on_a_phone(alcohol_scenario):
    page = alcohol_scenario["page"]
    page.set_viewport_size({"width": 390, "height": 844})
    _home(page)
    page.get_by_role("button", name="Start stocktake").click()
    line = page.locator(".st-line", has_text=BATCH)
    page.get_by_role("button", name="Differences").click()
    expect(line).to_be_hidden()
    expect(page.locator("[data-st-filter-empty]")).to_be_visible()
    page.get_by_role("button", name="To count").click()
    expect(line).to_be_visible()

    line.get_by_role("spinbutton", name=f"Counted {PRODUCT} {BATCH}").fill("48")
    line.get_by_role("button", name="Save", exact=True).click()
    expect(line).to_be_hidden()  # counted, so it leaves "To count"
    page.get_by_role("button", name="Differences").click()
    expect(line).to_contain_text("Difference to resolve")
    expect(page.locator("[data-st-progress-bar]")).to_have_attribute("style", "width: 100%;")

    # Each product is a labelled card, not ten squeezed columns.
    row = page.locator(".st-recon-table tbody tr").first
    expect(row.locator('[data-label="Difference"]')).to_have_text("-2")
    assert (
        row.locator('[data-label="Difference"]').evaluate("el => getComputedStyle(el, '::before').content")
        == '"Difference"'
    )
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1")


# CONCEPT ONLY: remove with the losing styles once one is picked.
@pytest.mark.parametrize("width", [390, 1024, 1440, 1920])
@pytest.mark.parametrize("style", ["1", "2", "3"])
def test_concept_styles_fit_the_width(alcohol_scenario, style, width):
    page = alcohol_scenario["page"]
    page.set_viewport_size({"width": width, "height": 900})
    _home(page, f"?style={style}")
    expect(page.locator("[data-stocktake-root]")).to_have_attribute("data-st-style", style)
    expect(page.get_by_role("heading", name="Stock position", exact=True)).to_be_visible()
    if style == "1":
        expect(page.locator(".st-glance")).to_be_visible()
        expect(page.locator("[data-st-brief]")).to_be_hidden()
    else:
        expect(page.locator(".st-glance")).to_be_hidden()
        expect(page.locator("[data-st-brief]")).to_contain_text("No stocktake finished yet.")
    if style == "2":
        expect(page.locator("[data-st-next]")).to_contain_text("Start a first stocktake to set a baseline.")
    else:
        expect(page.locator("[data-st-next]")).to_be_hidden()
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1")
