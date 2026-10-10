"""The dashboard is the whole business on one page: the compliance score and its parts, the
week as a grid of figures, then what needs attention and the day's plan, every block the
full width of the column (docs/dashboard-redesign-plan.md)."""

import json
import re
from datetime import date, timedelta
from uuid import UUID

import pytest
from playwright.sync_api import expect

from app.core.db.models.user import UserRole
from tests.e2e.conftest import assert_clean_page, attach_probe, login_through_ui
from tests.factories import InventoryItemFactory

pytestmark = pytest.mark.e2e

SUMMARY = "**/api/core/dashboard/summary*"


@pytest.fixture
def expired_stock_page(browser, app_url, fresh_user, db):
    """An admin's page on an org holding eight raw lines, one of them expired."""
    user = fresh_user(UserRole.ADMIN)
    org_id = UUID(user["org_id"])
    InventoryItemFactory(org_id=org_id, name="Angelica root", expiry_date=date.today() - timedelta(days=6))
    for index in range(7):
        InventoryItemFactory(org_id=org_id, name=f"Botanical {index}")
    db.commit()
    context = browser.new_context(base_url=app_url, ignore_https_errors=True, viewport={"width": 1440, "height": 900})
    page = context.new_page()
    attach_probe(page)
    login_through_ui(page, user["email"], user["password"])
    try:
        yield page
    finally:
        context.close()


def _open(page):
    page.goto("/core/dashboard")
    expect(page.locator(".dash-footer-note[data-dashboard-loading]")).to_be_hidden()


def _serve(page, change):
    """Serve the real summary with some fields changed, for states a seed cannot reach cheaply."""

    def handle(route):
        response = route.fetch()
        body = response.json()
        change(body)
        route.fulfill(response=response, body=json.dumps(body))

    page.route(SUMMARY, handle)


def test_an_attention_row_is_one_link_to_where_the_problem_is(expired_stock_page):
    page = expired_stock_page
    _open(page)

    attention = page.get_by_role("region", name="Needs attention", exact=True)
    row = attention.get_by_role("link", name=re.compile("Expired raw materials with stock"))
    expect(row).to_have_count(1)
    expect(row).to_contain_text("Production · Critical priority")
    expect(row.locator(".dash-attention__count")).to_have_text("1")

    row.click()
    expect(page).to_have_url(re.compile(r"/core/inventory/view$"))
    assert_clean_page(page)


OVERALL = {
    "score": 80,
    "state": "degraded",
    "components": [
        {
            "key": "production",
            "label": "Production checks",
            "score": 82,
            "state": "degraded",
            "href": "/core",
            "detail": "Expired materials −12, Output ready-date −6",
        },
        {
            "key": "module:NP3",
            "label": "NP3",
            "score": 78,
            "state": "healthy",
            "href": "/compliant/nz-alcohol/food-safety",
            "detail": "36 of 46 evidence controls current · Next verification: 18 Nov 2026",
        },
    ],
}


def test_the_compliance_score_shows_the_figure_its_state_and_the_parts_it_is_made_of(expired_stock_page):
    page = expired_stock_page
    _serve(page, lambda body: body.update({"compliance_overall": OVERALL}))
    _open(page)

    card = page.get_by_role("region", name="Compliance score", exact=True)
    expect(card.locator("[data-compliance-score]")).to_have_text("80")
    expect(card.locator("[data-compliance-state]")).to_have_text("Needs attention")
    expect(card.get_by_role("img", name="Compliance score 80 out of 100, needs attention")).to_be_visible()
    # The ring is filled to the score.
    assert card.locator("[data-compliance-arc]").evaluate("el => getComputedStyle(el).strokeDasharray") in (
        "80, 100",
        "80px, 100px",
    )

    parts = card.locator("[data-compliance-parts] a")
    expect(parts).to_have_count(2)
    expect(parts.nth(0)).to_have_attribute("href", "/core")
    expect(parts.nth(0)).to_contain_text("Production checks")
    expect(parts.nth(0).locator(".dash-part__score")).to_have_text("82")
    expect(parts.nth(0)).to_contain_text("Expired materials −12, Output ready-date −6")
    expect(parts.nth(1)).to_have_attribute("href", "/compliant/nz-alcohol/food-safety")
    expect(parts.nth(1)).to_contain_text("Next verification: 18 Nov 2026")
    assert parts.nth(1).locator(".dash-part__bar span").evaluate("el => el.style.width") == "78%"

    # First on the page, the full width of the column.
    band, week = card.bounding_box(), page.get_by_role("region", name="This week", exact=True).bounding_box()
    assert band["y"] + band["height"] <= week["y"]
    assert (round(band["x"]), round(band["width"])) == (round(week["x"]), round(week["width"]))
    assert_clean_page(page)


def test_the_compliance_score_comes_from_the_summary_for_a_real_org(expired_stock_page):
    """Unserved: the card shows what the API returned for this org, whatever that is."""
    page = expired_stock_page
    overall = page.request.get("/api/core/dashboard/summary?window_days=30").json()["compliance_overall"]
    assert overall["components"][0]["label"] == "Production checks"
    _open(page)

    card = page.get_by_role("region", name="Compliance score", exact=True)
    expect(card.locator("[data-compliance-score]")).to_have_text(str(overall["score"]))
    expect(card.locator("[data-compliance-parts] a")).to_have_count(len(overall["components"]))


def test_an_org_whose_checks_have_not_run_is_told_so(expired_stock_page):
    page = expired_stock_page

    def unknown(body):
        body["compliance_overall"]["state"] = "unknown"
        for part in body["compliance_overall"]["components"]:
            part["state"] = "unknown"

    _serve(page, unknown)
    _open(page)

    card = page.get_by_role("region", name="Compliance score", exact=True)
    expect(card.locator("[data-compliance-state]")).to_have_text("No checks run yet")


def test_this_week_is_a_full_grid_of_bordered_figures_above_the_days_plan(expired_stock_page):
    page = expired_stock_page

    def actions(body):
        body["action_board"]["critical_actions_total"] = 9

    _serve(page, actions)
    _open(page)

    week = page.get_by_role("region", name="This week", exact=True)
    figures = week.locator("a.dash-figure")
    expect(figures).to_have_count(8)  # an admin with Sales enabled sees every figure

    open_actions = week.get_by_role("link", name=re.compile("Open action items"))
    expect(open_actions).to_have_attribute("href", "/core/notifications")
    expect(open_actions.locator("[data-kpi-open-action-items]")).to_have_text("9")

    boxes = [figure.bounding_box() for figure in figures.all()]
    # Two full rows of four: no orphan tile, every tile the same size, each with its own border.
    assert sorted({round(box["y"]) for box in boxes}) == sorted({round(boxes[0]["y"]), round(boxes[4]["y"])})
    assert len({round(box["width"]) for box in boxes}) == 1
    assert len({round(box["height"]) for box in boxes}) == 1
    assert all(
        width == "1px" for width in figures.evaluate_all("els => els.map(el => getComputedStyle(el).borderTopWidth)")
    )

    planned = page.get_by_role("region", name="Today's planned production", exact=True).bounding_box()
    attention = page.get_by_role("region", name="Needs attention", exact=True).bounding_box()
    bottom = week.bounding_box()["y"] + week.bounding_box()["height"]
    assert bottom <= attention["y"] <= planned["y"]


def test_a_quiet_day_says_so_instead_of_showing_an_empty_list(expired_stock_page):
    page = expired_stock_page

    def quiet(body):
        body["action_board"] = {"critical_actions_total": 0, "items": []}
        body["compliance_overall"] = {
            "score": 100,
            "state": "healthy",
            "components": [{**OVERALL["components"][0], "score": 100, "state": "healthy", "detail": "No findings"}],
        }

    _serve(page, quiet)
    _open(page)

    attention = page.get_by_role("region", name="Needs attention", exact=True)
    expect(attention.get_by_role("link")).to_have_text(["Review findings"])
    expect(attention).to_contain_text("Nothing needs you right now")
    card = page.get_by_role("region", name="Compliance score", exact=True)
    expect(card.locator("[data-compliance-state]")).to_have_text("On track")
    expect(card).to_contain_text("No findings")


def test_a_figure_draws_a_trend_only_when_its_series_moves(expired_stock_page):
    page = expired_stock_page

    def series(body):
        flat = body["insight_series"]["active_batches_week"]["points"]
        moving = body["insight_series"]["operator_actions_week"]["points"]
        for point in flat:
            point["value"] = 0
        for index, point in enumerate(moving):
            point["value"] = index * 3

    _serve(page, series)
    _open(page)

    expect(page.locator('[data-kpi-spark="active_batches"]')).to_be_hidden()
    moving = page.locator('[data-kpi-spark="operator_actions"]')
    expect(moving).to_be_visible()
    expect(moving.locator("path.dash-kpi-trend-line")).to_have_attribute("d", re.compile(r"^M[\d.]+ [\d.]+ L"))


def test_recent_activity_shows_six_rows_then_the_rest_on_request(expired_stock_page):
    page = expired_stock_page

    # The page's own events, served under both periods. Which calendar day the server files
    # them under depends on its clock's timezone (see the plan's follow-ups); this test is
    # about the list, so it does not depend on that.
    def both_periods(body):
        items = body["audit_log"]["week"]["items"]
        assert len(items) == 8, "one 'added' event per seeded line"
        body["audit_log"]["day"] = {"total": 8, "items": items}
        body["audit_log"]["week"] = {"total": 23, "items": items}

    _serve(page, both_periods)
    _open(page)

    activity = page.get_by_role("region", name="Recent activity", exact=True)
    rows = activity.locator(".dash-activity__row")
    expect(rows).to_have_count(8)
    expect(activity.locator(".dash-activity__row:visible")).to_have_count(6)
    expect(activity.get_by_role("button", name="Today")).to_have_attribute("aria-pressed", "true")
    expect(activity.locator("[data-audit-meta]")).to_have_text("8 entries today.")

    activity.get_by_role("button", name="Show 2 more").click()
    expect(activity.locator(".dash-activity__row:visible")).to_have_count(8)
    expect(activity.get_by_role("button", name=re.compile("^Show"))).to_be_hidden()

    activity.get_by_role("button", name="This week").click()
    expect(activity.get_by_role("button", name="This week")).to_have_attribute("aria-pressed", "true")
    expect(activity.locator("[data-audit-meta]")).to_have_text("Latest 8 of 23 entries this week.")
    expect(activity.locator(".dash-activity__row:visible")).to_have_count(6)
    assert_clean_page(page)


def test_the_setup_strip_can_be_hidden_and_stays_hidden(expired_stock_page):
    page = expired_stock_page
    _open(page)
    strip = page.locator("[data-dashboard-go-live]")
    expect(strip).to_be_visible()
    expect(strip.get_by_role("link", name="Start the go-live stocktake")).to_have_attribute("href", "/core/go-live")

    strip.get_by_role("button", name="Hide").click()
    expect(strip).to_be_hidden()
    page.reload()
    expect(page.locator(".dash-footer-note[data-dashboard-loading]")).to_be_hidden()
    page.wait_for_load_state("networkidle")
    expect(page.locator("[data-dashboard-go-live]")).to_be_hidden()


def test_more_than_one_active_batch_is_spelled_batches(expired_stock_page):
    """[REGRESSION] The Production tile read "3 active batchs in progress."."""
    page = expired_stock_page
    _serve(page, lambda body: body["operations"].update({"active_executions": 3}))
    _open(page)
    expect(page.locator("[data-dashboard-core-summary]")).to_have_text("3 active batches in progress.")


# ── CONCEPT ONLY: the three styles on offer. Delete with the two styles not chosen. ──


def _serve_busy(page):
    def busy(body):
        body["compliance_overall"] = OVERALL
        body["action_board"]["critical_actions_total"] = 10
        body["operations"]["active_executions"] = 3

    _serve(page, busy)


@pytest.mark.parametrize("style", ["1", "2", "3"])
@pytest.mark.parametrize("width", [390, 1440, 1920])
def test_every_style_shows_the_whole_business_without_sideways_scrolling(expired_stock_page, style, width):
    page = expired_stock_page
    page.set_viewport_size({"width": width, "height": 1080 if width == 1920 else 900})
    _serve_busy(page)
    page.goto(f"/core/dashboard?style={style}")
    expect(page.locator(".dash-footer-note[data-dashboard-loading]")).to_be_hidden()

    expect(page.locator("[data-dashboard-root]")).to_have_attribute("data-dashboard-style", style)
    expect(page.get_by_role("button", name=f"Style {style}")).to_have_attribute("aria-pressed", "true")
    for name in ["Compliance score", "This week", "Needs attention", "Today's planned production"]:
        expect(page.get_by_role("region", name=name, exact=True)).to_be_visible()
    expect(page.locator("[data-compliance-score]")).to_have_text("80")
    expect(page.locator("[data-kpi-open-action-items]")).to_have_text("10")
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth + 1"), "scrolls sideways"
    # No figure's trend line is drawn over its number.
    overlaps = page.evaluate(
        """() => [...document.querySelectorAll('.dash-figure')].filter(tile => {
            const value = tile.querySelector('.dash-figure__value').getBoundingClientRect();
            const spark = tile.querySelector('.dash-figure__spark:not([hidden]) svg');
            if (!spark) return false;
            const s = spark.getBoundingClientRect();
            if (!s.width) return false;
            return !(s.left >= value.right - 1 || s.top >= value.bottom - 1 || s.bottom <= value.top + 1);
        }).length"""
    )
    assert overlaps == 0
    assert_clean_page(page)


def test_the_board_fits_the_first_wall_screen_and_keeps_its_two_lists_level(expired_stock_page):
    page = expired_stock_page
    page.set_viewport_size({"width": 1920, "height": 1080})
    _serve_busy(page)
    page.goto("/core/dashboard?style=2")
    expect(page.locator(".dash-footer-note[data-dashboard-loading]")).to_be_hidden()
    if page.locator("[data-dashboard-go-live-hide]").is_visible():
        page.locator("[data-dashboard-go-live-hide]").click()

    def box(name):
        return page.get_by_role("region", name=name, exact=True).bounding_box()

    compliance, week, attention, plan = (
        box("Compliance score"),
        box("This week"),
        box("Needs attention"),
        box("Today's planned production"),
    )
    # Two rows of two, each pair the same height, edges flush: no blank area beside a taller card.
    assert round(compliance["y"]) == round(week["y"]) and round(compliance["height"]) == round(week["height"])
    assert round(attention["y"]) == round(plan["y"]) and round(attention["height"]) == round(plan["height"])
    assert round(compliance["x"]) == round(attention["x"])
    assert round(week["x"] + week["width"]) == round(plan["x"] + plan["width"])
    assert attention["y"] + attention["height"] <= 1080, "score, week, attention and plan fit one wall screen"


def test_the_briefing_reads_the_page_out_in_one_sentence(expired_stock_page):
    page = expired_stock_page
    _serve_busy(page)
    page.goto("/core/dashboard?style=3")
    expect(page.locator(".dash-footer-note[data-dashboard-loading]")).to_be_hidden()

    brief = page.locator("[data-dashboard-brief]")
    expect(brief).to_be_visible()
    expect(brief).to_have_text(
        "10 things need attention, compliance is at 80 (needs attention) and 3 batches are in progress."
    )
    page.get_by_role("button", name="Style 1").click()
    expect(brief).to_be_hidden()
