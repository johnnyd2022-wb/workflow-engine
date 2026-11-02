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


def _open(page, style=None, payload=None):
    page.route("**/api/core/planner/demands", lambda route: route.fulfill(json=payload or _demands()))
    page.goto("/core/planner" + (f"?style={style}" if style else ""))
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


@pytest.mark.parametrize("width", [390, 1024, 1440, 1920])
def test_planner_fits_every_width_and_keeps_every_region(browser, app_url, workspace_user, width):
    context, page = _page(browser, app_url, workspace_user, width)
    try:
        _open(page)
        expect(page.locator("[data-demand-list] .planner-row")).to_have_count(4)
        expect(page.get_by_role("region", name="To make", exact=True)).to_be_visible()
        expect(page.locator("[data-closed] > summary")).to_be_visible()
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1")
        card = page.locator(".planner-demand").bounding_box()
        for row in page.locator("[data-demand-list] .planner-row").all():
            box = row.bounding_box()
            assert box["x"] >= card["x"] and box["x"] + box["width"] <= card["x"] + card["width"] + 1
        # The board: figures beside what to make where there is room, one above the other where not.
        glance = page.get_by_role("region", name="At a glance", exact=True).bounding_box()
        make = page.get_by_role("region", name="To make", exact=True).bounding_box()
        if width >= 1440:
            assert abs(glance["y"] - make["y"]) < 2 and glance["x"] + glance["width"] <= make["x"]
        else:
            assert make["y"] >= glance["y"] + glance["height"]
    finally:
        context.close()


def test_planner_has_no_layout_preview_left(browser, app_url, workspace_user):
    context, page = _page(browser, app_url, workspace_user, 1440)
    try:
        page.goto("/core/planner")
        page.evaluate('sessionStorage.setItem("planner-design-style", "2")')
        _open(page, "3")
        # CONCEPT ONLY (GL-P07 B3 draft): the stock cover layout switch is in until a style is
        # picked; restore `to_have_count(0)` with it.
        expect(page.locator("[data-style-pick]")).to_have_count(3)
        expect(page.locator(".planner-row__rank")).to_have_count(0)
        expect(page.locator(".planner-group")).to_have_count(0)
        # Soonest due first, as the board orders it.
        assert page.locator("[data-demand-list] .planner-row h3").first.inner_text() == "Regional Wines summer order"
    finally:
        context.close()


def _forecast():
    """Two products: one to plan now, one with cover to spare."""
    weeks = [{"week_ending": _due(7 * week), "stock": str(220 - 40 * week)} for week in range(1, 13)]
    return {
        "products": [
            {
                "output_id": GIN,
                "name": "Navy Strength Gin",
                "unit": "L",
                "process_id": GIN,
                "weekly_rate": "39.2",
                "window_weeks": 12,
                "seasonal_factor": None,
                "history_weeks": 70,
                "on_hand": "221",
                "planned": "0",
                "waiting": "0",
                "runs_out": _due(39),
                "projection": weeks,
                "weeks_of_cover": "5.6",
                "target_weeks": "10",
                "suggestion": {
                    "quantity": "160",
                    "batches": 4,
                    "need_by": _due(39),
                    "plan_by": _due(37),
                    "late": False,
                },
                "sentence": "Navy Strength Gin runs out soon at 39 L a week; plan 4 batches to keep 10 weeks' cover.",
            },
            {
                "output_id": PINK,
                "name": "Pink Gin",
                "unit": "L",
                "process_id": PINK,
                "weekly_rate": "12.8",
                "window_weeks": 12,
                "seasonal_factor": None,
                "history_weeks": 70,
                "on_hand": "300",
                "planned": "0",
                "waiting": "0",
                "runs_out": _due(160),
                "projection": [{"week_ending": w["week_ending"], "stock": "250"} for w in weeks],
                "weeks_of_cover": "22.9",
                "target_weeks": None,
                "suggestion": None,
                "sentence": "Pink Gin runs out later at 13 L a week.",
            },
        ]
    }


def _open_with_forecast(page, style):
    page.route("**/api/core/planner/forecast", lambda route: route.fulfill(json=_forecast()))
    page.route(
        "**/api/core/planner/contract-demand/sync",
        lambda route: route.fulfill(json={"added": 0, "updated": 0, "cancelled": 0}),
    )
    _open(page, style)
    expect(page.get_by_role("region", name="Stock cover", exact=True)).to_be_visible()


@pytest.mark.parametrize("width", [390, 1024, 1440])
@pytest.mark.parametrize("style", ["1", "2", "3"])
def test_concept_stock_cover_fits_every_width(browser, app_url, workspace_user, width, style):
    """CONCEPT ONLY: each stock cover layout at phone, laptop and wide; deleted with the losing two."""
    context, page = _page(browser, app_url, workspace_user, width)
    try:
        _open_with_forecast(page, style)
        expect(page.locator("[data-cover-brief]")).to_have_text(
            "1 product needs planning. Navy Strength Gin first, by "
            + page.evaluate(
                f"new Date('{_due(37)}T00:00:00').toLocaleDateString('en-NZ', {{day: 'numeric', month: 'short'}})"
            )
            + "."
        )
        if style != "2" or width > 390:  # the projection's Plan column scrolls into view on a phone
            expect(page.get_by_role("button", name="Plan 4 batches of Navy Strength Gin")).to_be_visible()
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1")
    finally:
        context.close()


def test_plan_it_in_one_click(browser, app_url, workspace_user):
    context, page = _page(browser, app_url, workspace_user, 1440)
    calls = []
    try:
        page.route(
            f"**/api/core/planner/forecast/{GIN}/plan",
            lambda route: (
                calls.append(route.request.method),
                route.fulfill(status=201, json={"demand": {}, "batches": [{}, {}, {}, {}]}),
            ),
        )
        _open_with_forecast(page, "1")
        page.get_by_role("button", name="Plan 4 batches of Navy Strength Gin").click()
        expect(page.locator("[data-cover-brief]")).to_have_text(
            "4 batches of Navy Strength Gin planned. They are on the production board."
        )
        assert calls == ["POST"]
    finally:
        context.close()
