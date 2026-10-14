"""The Production board's redesign (docs/production-board-redesign-plan.md): compact batch cards
with their actions behind Details, period stepping, the at-a-glance figures, a calendar-aligned
month, and the three CONCEPT ONLY layouts. Actions themselves are covered in test_board_phone.py."""

from datetime import timedelta
from urllib.parse import urlsplit

import pytest
from playwright.sync_api import expect

from tests.features.planning import test_batches as fixtures

board_clients = fixtures.board_clients
demand_clients = fixtures.demand_clients
flask_app = fixtures.flask_app
TODAY = fixtures.TODAY

pytestmark = pytest.mark.e2e


@pytest.fixture
def planned(board_clients, db):
    """Three batches of one demand, planned through the API."""
    client, _, output = board_clients[0]
    demand = fixtures.configure_http(db, client, output)
    response = client.post(f"/api/core/planner/demands/{demand['id']}/plan", json={})
    assert response.status_code == 201, response.get_json()
    return client, demand, response.get_json()["batches"]


def _open(browser, client, width=1440, path="/core/planner/board"):
    page = browser.new_page(viewport={"width": width, "height": 900})

    def proxy(route):
        parsed = urlsplit(route.request.url)
        if parsed.netloc != "planner.test":
            route.abort()
            return
        response = client.open(
            parsed.path + ("?" + parsed.query if parsed.query else ""),
            method=route.request.method,
            data=route.request.post_data,
            headers={
                "Content-Type": route.request.headers.get("content-type", "application/json"),
                **({"HX-Request": "true"} if route.request.headers.get("hx-request") else {}),
                **({"HX-Boosted": "true"} if route.request.headers.get("hx-boosted") else {}),
            },
        )
        route.fulfill(status=response.status_code, body=response.data, headers={"Content-Type": response.content_type})

    page.route("**/*", proxy)
    page.goto("https://planner.test" + path)
    page.locator('[data-board-root][data-state="ready"]').wait_for()
    return page


def _monday(day):
    return day - timedelta(days=day.weekday())


def test_card_shows_what_and_whether_it_can_start_with_actions_behind_details(planned, browser):
    client, demand, batches = planned
    page = _open(browser, client)
    try:
        page.locator('[name="view"]').select_option("day")
        page.locator('[data-board-range] [name="date"]').fill(batches[0]["proposed_start_date"])
        page.get_by_role("button", name="Show board").click()
        card = page.locator(f'[data-batch-id="{batches[0]["id"]}"]')
        expect(card.get_by_role("heading", name=demand["reference"] + " · Batch 1", exact=True)).to_be_visible()
        # Quantities lose their padding zeros, and the state is words, not colour alone.
        expect(card.locator(".board-batch__what")).to_contain_text("250 ")
        expect(card.locator(".board-batch__what")).not_to_contain_text("250.0000")
        expect(card.locator(".board-batch__state")).to_have_text(f"{len(batches[0]['blockers'])} checks to clear")
        expect(card.get_by_role("button", name="Pin batch", exact=True)).to_be_visible()
        expect(card.get_by_role("button", name="Set priority")).to_be_hidden()

        card.locator(".board-batch__details > summary").click()
        card.locator('[name="priority"]').fill("70")
        card.get_by_role("button", name="Set priority").click()
        expect(page.locator("[data-board-notice]")).to_have_text("Plan updated")
        # The board re-renders after the action; the card the user is working in stays open.
        expect(card.get_by_text("Main site · Priority 70", exact=True)).to_be_visible()
        expect(card.get_by_role("button", name="Set priority")).to_be_visible()
    finally:
        page.close()


def test_period_steps_by_view_and_month_starts_under_its_weekday(planned, browser):
    client, _, _ = planned
    page = _open(browser, client)
    title = page.locator("[data-board-title]")
    try:
        monday = _monday(TODAY)
        expect(title).to_have_attribute("data-start", monday.isoformat())
        expect(title).to_have_attribute("data-end", (monday + timedelta(days=6)).isoformat())
        page.get_by_role("button", name="Next period").click()
        expect(title).to_have_attribute("data-start", (monday + timedelta(days=7)).isoformat())
        page.get_by_role("button", name="Previous period").click()
        page.get_by_role("button", name="Previous period").click()
        expect(title).to_have_attribute("data-start", (monday - timedelta(days=7)).isoformat())
        page.get_by_role("button", name="Today").click()
        expect(title).to_have_attribute("data-start", monday.isoformat())

        page.locator('[name="view"]').select_option("month")
        first = TODAY.replace(day=1)
        expect(title).to_have_attribute("data-start", first.isoformat())
        day_one = page.locator(f'[data-board-date="{first.isoformat()}"]')
        assert day_one.evaluate("el => el.style.gridColumnStart") == str(first.weekday() + 1)
        page.get_by_role("button", name="Next period").click()
        following = (first + timedelta(days=32)).replace(day=1)
        expect(title).to_have_attribute("data-start", following.isoformat())
    finally:
        page.close()


def test_figures_count_the_period_and_an_empty_period_says_so(planned, browser):
    client, _, batches = planned
    page = _open(browser, client)
    try:
        page.locator('[data-board-range] [name="date"]').fill(batches[0]["proposed_start_date"])
        page.get_by_role("button", name="Show board").click()
        expect(page.locator('[data-figure="batches"]')).to_have_text(str(len(batches)))
        expect(page.locator('[data-figure="blocked"]')).to_have_text(str(len(batches)))
        expect(page.locator('[data-figure="ready"]')).to_have_text("0")
        start = TODAY.fromisoformat(batches[0]["proposed_start_date"])
        expect(page.locator("[data-board-days]")).to_have_attribute(
            "data-weekend", "busy" if start.weekday() >= 5 else "quiet"
        )

        page.locator('[data-board-range] [name="date"]').fill((TODAY + timedelta(days=400)).isoformat())
        page.get_by_role("button", name="Show board").click()
        expect(page.locator("[data-board-empty]")).to_be_visible()
        expect(page.locator(".board-figures")).to_be_hidden()
    finally:
        page.close()


def test_arriving_by_an_in_app_link_renders_the_board(planned, browser):
    client, _, batches = planned
    page = _open(browser, client, path="/core/planner/board")
    try:
        page.locator(".workspace-header").get_by_role("link", name="Production demand").click()
        page.locator("[data-planning-root]").wait_for()
        page.locator(".workspace-header").get_by_role("link", name="Production board").click()
        page.locator('[data-board-root][data-state="ready"]').wait_for()
        page.locator('[data-board-range] [name="date"]').fill(batches[0]["proposed_start_date"])
        page.get_by_role("button", name="Show board").click()
        expect(page.locator(f'[data-batch-id="{batches[0]["id"]}"]')).to_be_visible()
    finally:
        page.close()


# CONCEPT ONLY: remove with the losing styles once one is picked.
@pytest.mark.parametrize("width", [390, 1024, 1440, 1920])
@pytest.mark.parametrize("style", ["1", "2", "3"])
def test_concept_styles_fit_the_width_and_arrange_the_batches(planned, browser, style, width):
    client, demand, batches = planned
    page = _open(browser, client, width=width, path=f"/core/planner/board?style={style}")
    try:
        page.locator('[data-board-range] [name="date"]').fill(batches[0]["proposed_start_date"])
        page.get_by_role("button", name="Show board").click()
        expect(page.locator(".board-batch")).to_have_count(len(batches))
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
        if style == "1":
            expect(page.locator(".board-figures")).to_be_visible()
        else:
            expect(page.locator("[data-board-brief]")).to_contain_text(f"{len(batches)} batches planned")
            expect(page.locator(".board-figures")).to_be_hidden()
        if style == "3":
            lanes = page.locator(".board-lane:not(.board-lane--head)")
            expect(lanes).to_have_count(1)
            expect(lanes.first.locator(".board-lane__label strong")).to_have_text(demand["reference"])
            expect(page.locator(".board-batch h4").first).to_have_text("Batch 1")
    finally:
        page.close()
