"""Responsive board actions; real CSRF boundaries live in test_batches.py."""

from datetime import timedelta
from urllib.parse import urlsplit

import pytest

from tests.features.planning import test_batches as fixtures

board_clients = fixtures.board_clients
demand_clients = fixtures.demand_clients
flask_app = fixtures.flask_app
payload = fixtures.payload
TODAY = fixtures.TODAY

pytestmark = pytest.mark.e2e


def test_phone_board_settings_plan_pin_move_priority_and_month_day_views(board_clients, browser):
    client, _, output = board_clients[0]
    client.post(
        "/api/core/planner/demands",
        json=payload(
            output, reference="Phone <script>alert(1)</script>", due_date=(TODAY + timedelta(days=2)).isoformat()
        ),
    )
    page = browser.new_page(viewport={"width": 390, "height": 844})

    def proxy(route):
        request = route.request
        parsed = urlsplit(request.url)
        if parsed.netloc != "planner.test":
            route.abort()
            return
        response = client.open(
            parsed.path + ("?" + parsed.query if parsed.query else ""),
            method=request.method,
            data=request.post_data,
            headers={"Content-Type": request.headers.get("content-type", "application/json")},
        )
        route.fulfill(status=response.status_code, body=response.data, headers={"Content-Type": response.content_type})

    page.route("**/*", proxy)
    try:
        page.goto("https://planner.test/core/planner/board")
        page.locator("[data-workflow-output] option").wait_for(state="attached")
        page.locator("[data-workflow-settings] summary").click()
        page.locator('[name="batch_quantity"]').fill("250")
        page.locator('[name="duration_minutes"]').fill("60")
        page.locator('[name="waiting_minutes"]').fill("2820")
        page.get_by_role("button", name="Save planning settings").click()
        page.get_by_text("Planning settings saved", exact=True).wait_for()
        page.get_by_role("button", name="Plan batches").click()
        card = page.locator(".board-batch").first
        card.get_by_role("heading", name="Phone <script>alert(1)</script> · Batch 1", exact=True).wait_for()
        assert page.locator(".board-batch script").count() == 0
        assert card.get_by_role("button", name="Start batch").is_disabled()
        card.get_by_role("button", name="Pin batch", exact=True).click()
        card.get_by_role("button", name="Unpin batch", exact=True).wait_for()
        assert card.get_by_role("button", name="Move batch").count() == 0
        card.get_by_role("button", name="Unpin batch", exact=True).click()
        card.get_by_role("button", name="Move batch").wait_for()
        card.locator('[name="priority"]').fill("75")
        card.get_by_role("button", name="Set priority").click()
        page.get_by_text("Main site · Priority 75", exact=True).wait_for()
        next_day = (TODAY + timedelta(days=1)).isoformat()
        card.locator('[name="start_date"]').fill(next_day)
        card.get_by_role("button", name="Move batch").click()
        # A move can cross a week/month boundary; select its day explicitly.
        page.locator('[data-board-range] [name="date"]').fill(next_day)
        for view in ("month", "week", "day"):
            page.locator('[name="view"]').select_option(view)
            page.get_by_role("button", name="Show board").click()
            page.wait_for_timeout(100)
            assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
            assert page.locator("[data-board-root] input, [data-board-root] select").evaluate_all(
                "els => els.every(el => { const r = el.getBoundingClientRect(); return r.left >= 0 && r.right <= window.innerWidth; })"
            )
        page.get_by_text("Proposed start " + next_day, exact=True).wait_for()
        page.locator(".board-batch").first.get_by_role("button", name="Cancel batch").click()
        page.wait_for_function('document.querySelectorAll(".board-batch").length === 0')
    finally:
        page.close()
