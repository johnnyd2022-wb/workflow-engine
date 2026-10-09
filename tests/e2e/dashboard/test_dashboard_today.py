"""The dashboard leads with a health band and what needs attention, then one row of figures
for the week, every block the full width of the column (docs/dashboard-redesign-plan.md)."""

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


def test_production_health_shows_the_score_its_state_and_what_is_driving_it(expired_stock_page):
    page = expired_stock_page

    def degraded(body):
        body["compliance"].update(
            {
                "score": 81.6,
                "state": "degraded",
                "top_drivers": [
                    {"key": "expired_materials", "label": "Expired materials", "penalty": 12},
                    {"key": "output_ready_date", "label": "Outputs past ready date", "penalty": 6},
                ],
            }
        )

    _serve(page, degraded)
    _open(page)

    health = page.get_by_role("region", name="Production health", exact=True)
    expect(health.locator("[data-health-score]")).to_have_text("82")
    expect(health.locator("[data-health-state]")).to_have_text("Needs attention")
    expect(health.locator("[data-health-drivers] li")).to_have_text(
        [re.compile(r"Expired materials\s*−12"), re.compile(r"Outputs past ready date\s*−6")]
    )
    # Health is a band across the page above the attention list, the same width as it.
    band, attention = (
        health.bounding_box(),
        page.get_by_role("region", name="Needs attention", exact=True).bounding_box(),
    )
    assert band["y"] + band["height"] <= attention["y"]
    assert (round(band["x"]), round(band["width"])) == (round(attention["x"]), round(attention["width"]))
    assert band["height"] < 110, "one line, not a card"
    assert_clean_page(page)


def test_an_org_with_no_health_state_yet_gets_no_health_card(expired_stock_page):
    """A new org's score has state "unknown": show nothing rather than a number with no meaning."""
    page = expired_stock_page
    _serve(page, lambda body: body["compliance"].update({"state": "unknown"}))
    _open(page)

    expect(page.locator("[data-dashboard-health]")).to_be_hidden()
    expect(page.get_by_role("region", name="Needs attention", exact=True)).to_be_visible()


def test_a_quiet_day_says_so_instead_of_showing_an_empty_list(expired_stock_page):
    page = expired_stock_page

    def quiet(body):
        body["action_board"] = {"critical_actions_total": 0, "items": []}
        body["compliance"].update({"score": 100, "state": "healthy", "top_drivers": []})

    _serve(page, quiet)
    _open(page)

    attention = page.get_by_role("region", name="Needs attention", exact=True)
    expect(attention.get_by_role("link")).to_have_text(["Review findings"])
    expect(attention).to_contain_text("Nothing needs you right now")
    health = page.get_by_role("region", name="Production health", exact=True)
    expect(health.locator("[data-health-state]")).to_have_text("Production healthy")
    expect(health).to_contain_text("Nothing is pulling the score down.")


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
