"""The Planner shows what needs making before it shows a form, and says when it is due in words."""

from datetime import date, timedelta

import pytest
from playwright.sync_api import expect

from tests.e2e.test_workspace_overviews import _page
from tests.e2e.test_workspace_overviews import workspace_user as _workspace_user

workspace_user = _workspace_user

pytestmark = pytest.mark.e2e

GIN, PINK = "11111111-1111-4111-8111-111111111111", "22222222-2222-4222-8222-222222222222"


def _due(days):
    return (date.today() + timedelta(days=days)).isoformat()


def _demands():
    def row(index, reference, output, quantity, days, priority, status="open"):
        return {
            "id": f"00000000-0000-4000-8000-00000000000{index}",
            "reference": reference,
            "source_output_id": output,
            "quantity": quantity,
            "unit": "L",
            "due_date": _due(days),
            "priority": priority,
            "status": status,
        }

    return {
        "outputs": [
            {"id": GIN, "name": "Navy Strength Gin: bottle and label", "unit": "L", "process_id": "p1"},
            {"id": PINK, "name": "Pink Gin: bottle and label", "unit": "L", "process_id": "p2"},
        ],
        # As the API returns them: soonest due first.
        "demands": [
            row(1, "Regional Wines summer order", GIN, "240.0000", -2, 20),
            row(2, "Moore Wilson's standing order", PINK, "120.5000", 1, 60),
            row(3, "Bottle-O restock", GIN, "180.0000", 6, 90),
            row(4, "December forecast", PINK, "300.0000", 21, 10),
            row(5, "Trade show samples", GIN, "40.0000", 12, 10, "cancelled"),
        ],
    }


def _open(page, style="1", payload=None):
    page.route("**/api/core/planner/demands", lambda route: route.fulfill(json=payload or _demands()))
    page.goto(f"/core/planner?style={style}")
    expect(page.locator("[data-planner-layout]")).to_have_attribute("aria-busy", "false")


def test_demand_leads_and_says_when_it_is_due_in_words(browser, app_url, workspace_user):
    context, page = _page(browser, app_url, workspace_user, 1440)
    try:
        _open(page)
        rows = page.locator("[data-demand-list] .planner-row")
        expect(rows).to_have_count(4)
        labels = rows.locator(".planner-due").all_inner_texts()
        assert labels[:3] == ["2 days overdue", "Due tomorrow", "Due in 6 days"]
        assert labels[3].startswith("Due ") and labels[3] != f"Due {_due(21)}"
        expect(rows.nth(0).locator(".planner-due")).to_have_attribute("data-state", "overdue")
        expect(rows.nth(0).locator(".planner-due")).to_have_attribute("title", _due(-2))
        # Quantities drop their padding: 240 L, not 240.0000 L; a real fraction is kept.
        expect(rows.nth(0)).to_contain_text("240 L · Navy Strength Gin: bottle and label")
        expect(rows.nth(1)).to_contain_text("120.5 L")
        assert "240.0000" not in page.locator("[data-planning-root]").inner_text()
        # The form is not on the page until it is asked for.
        expect(page.get_by_role("heading", name="Add demand", exact=True)).to_be_hidden()
        expect(page.locator(".workspace-header .workspace-button--primary:visible")).to_have_count(1)
    finally:
        context.close()


def test_figures_and_totals_add_up_open_demand_only(browser, app_url, workspace_user):
    context, page = _page(browser, app_url, workspace_user, 1440)
    try:
        _open(page)
        expect(page.locator("[data-figure-open]")).to_have_text("4")
        expect(page.locator("[data-figure-overdue]")).to_have_text("1")
        expect(page.locator("[data-figure-week]")).to_have_text("2")
        expect(page.locator("[data-figure-overdue-tile]")).to_have_attribute("data-state", "overdue")
        make = page.get_by_role("region", name="To make", exact=True)
        # 240 + 180 of gin; the cancelled 40 is not counted.
        expect(make.locator("li").nth(0)).to_contain_text("Navy Strength Gin: bottle and label")
        expect(make.locator("li").nth(0).locator("strong")).to_have_text("420 L")
        expect(make.locator("li").nth(1).locator("strong")).to_have_text("420.5 L")
        closed = page.locator("[data-closed]")
        expect(closed.locator("summary")).to_have_text("Closed demand (1)")
        expect(closed.locator(".planner-row")).to_be_hidden()
        closed.locator("summary").click()
        expect(closed.locator(".planner-row")).to_contain_text("Trade show samples")
        expect(closed.get_by_role("button")).to_have_count(0)
    finally:
        context.close()


def test_add_demand_opens_the_form_and_close_puts_it_away(browser, app_url, workspace_user):
    context, page = _page(browser, app_url, workspace_user, 1440)
    try:
        _open(page)
        toggle = page.locator(".workspace-header [data-add-toggle]")
        toggle.click()
        expect(toggle).to_have_attribute("aria-expanded", "true")
        expect(page.locator('[name="reference"]')).to_be_focused()
        expect(page.get_by_label("Product output").locator("option")).to_have_count(3)
        # While the form is open, its Save is the one filled action on the page.
        filled = page.evaluate(
            """() => [...document.querySelectorAll('[data-planning-root] .planner-primary')]
                 .filter(b => b.offsetParent && getComputedStyle(b).backgroundColor === getComputedStyle(document.querySelector('.planner-add [type=submit]')).backgroundColor).length"""
        )
        assert filled == 1
        page.get_by_role("button", name="Close", exact=True).click()
        expect(page.locator('[name="reference"]')).to_be_hidden()
        expect(toggle).to_be_focused()
    finally:
        context.close()


def test_no_demand_shows_one_next_step_and_no_row_of_zeros(browser, app_url, workspace_user):
    context, page = _page(browser, app_url, workspace_user, 1440)
    try:
        _open(page, payload={"demands": [], "outputs": []})
        expect(page.get_by_text("No production demand yet", exact=True)).to_be_visible()
        expect(page.get_by_role("region", name="At a glance", exact=True)).to_be_hidden()
        expect(page.get_by_role("region", name="To make", exact=True)).to_be_hidden()
        page.locator(".planner-empty").get_by_role("button", name="Add demand", exact=True).click()
        expect(page.locator('[name="reference"]')).to_be_focused()
    finally:
        context.close()


def test_failed_load_is_not_an_empty_planner_and_retry_recovers(browser, app_url, workspace_user):
    context, page = _page(browser, app_url, workspace_user, 1440)
    try:
        page.route(
            "**/api/core/planner/demands", lambda route: route.fulfill(status=503, json={"error": "Unavailable"})
        )
        page.goto("/core/planner")
        expect(page.get_by_role("alert")).to_contain_text("Production demand could not load")
        expect(page.get_by_text("No production demand yet", exact=True)).to_be_hidden()
        expect(page.get_by_role("region", name="At a glance", exact=True)).to_be_hidden()
        page.unroute("**/api/core/planner/demands")
        page.route("**/api/core/planner/demands", lambda route: route.fulfill(json=_demands()))
        page.get_by_role("button", name="Try again", exact=True).click()
        expect(page.locator("[data-demand-list] .planner-row")).to_have_count(4)
        expect(page.get_by_role("alert")).to_be_hidden()
    finally:
        context.close()


def test_planner_loads_again_after_leaving_by_a_tab_and_returning(browser, app_url, workspace_user):
    """Arriving by an in-app link, not a full load, must fetch and render again."""
    context, page = _page(browser, app_url, workspace_user, 1440)
    try:
        _open(page)
        page.evaluate("window.__plannerSentinel = true")
        page.get_by_role("tab", name="Workflows", exact=True).click()
        expect(page.locator(".workspace-header h1")).to_have_text("Workflows")
        page.get_by_role("tab", name="Planner", exact=True).click()
        expect(page.locator("[data-demand-list] .planner-row")).to_have_count(4)
        expect(page.locator("[data-figure-open]")).to_have_text("4")
        assert page.evaluate("window.__plannerSentinel"), "must be an in-app swap, not a full load"
    finally:
        context.close()


# CONCEPT ONLY — delete with the preview switch and the two layouts not chosen.
@pytest.mark.parametrize("style", ["1", "2", "3"])
@pytest.mark.parametrize("width", [390, 1024, 1440, 1920])
def test_concepts_fit_and_keep_every_region(browser, app_url, workspace_user, style, width):
    context, page = _page(browser, app_url, workspace_user, width)
    try:
        _open(page, style)
        root = page.locator("[data-planning-root]")
        expect(root).to_have_attribute("data-planner-style", style)
        expect(page.locator("[data-demand-list] .planner-row")).to_have_count(4)
        expect(page.get_by_role("region", name="To make", exact=True)).to_be_visible()
        expect(page.locator("[data-closed] > summary")).to_be_visible()
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1")
        # Nothing in a demand row is drawn outside its card.
        card = page.locator(".planner-demand").bounding_box()
        for row in page.locator("[data-demand-list] .planner-row").all():
            box = row.bounding_box()
            assert box["x"] >= card["x"] and box["x"] + box["width"] <= card["x"] + card["width"] + 1
    finally:
        context.close()


# CONCEPT ONLY
def test_each_concept_orders_the_same_demand_its_own_way(browser, app_url, workspace_user):
    context, page = _page(browser, app_url, workspace_user, 1440)
    try:
        _open(page, "1")
        names = lambda: page.locator("[data-demand-list] .planner-row h3").all_inner_texts()  # noqa: E731
        assert names()[0] == "Regional Wines summer order"  # soonest due first
        expect(page.locator("[data-planner-brief]")).to_be_hidden()
        page.get_by_role("button", name="2 · Queue", exact=True).click()
        assert names()[0] == "Bottle-O restock"  # highest priority first
        expect(page.locator("[data-demand-list] .planner-row__rank").first).to_have_text("1")
        expect(page.locator("[data-planner-brief]")).to_have_text(
            "4 orders and forecasts are open: 1 overdue, 2 due this week, 1 later."
        )
        expect(page.get_by_role("region", name="At a glance", exact=True)).to_be_hidden()
        page.get_by_role("button", name="3 · Timeline", exact=True).click()
        expect(page.locator("[data-demand-list] .planner-group")).to_have_text(["Overdue1", "This week2", "Later1"])
        assert names()[0] == "Regional Wines summer order"
    finally:
        context.close()
