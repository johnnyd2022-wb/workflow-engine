"""Responsive board actions; real CSRF boundaries live in test_batches.py."""

from datetime import timedelta
from urllib.parse import urlsplit

import pytest
from playwright.sync_api import expect

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


def _drag_between_days(page, handle, target):
    # Start the native drag before scrolling: Playwright's drag_to scrolls both ends
    # before mouse-down, which can move the source off-screen in the narrow layout.
    handle.scroll_into_view_if_needed()
    source = handle.bounding_box()
    x, y = source["x"] + source["width"] / 2, source["y"] + source["height"] / 2
    page.mouse.move(x, y)
    page.mouse.down()
    page.mouse.move(x + 12, y + 12, steps=3)
    target.scroll_into_view_if_needed()
    destination = target.bounding_box()
    tx = destination["x"] + destination["width"] / 2
    ty = destination["y"] + destination["height"] / 2
    page.mouse.move(tx, ty, steps=10)
    page.mouse.move(tx + 1, ty + 1)
    page.mouse.up()


@pytest.mark.parametrize("width", [390, 1440])
def test_drag_batch_to_day_and_refresh_after_a_concurrent_pin(board_clients, db, browser, width):
    client, _, output = board_clients[0]
    demand = fixtures.configure_http(db, client, output)
    planned = client.post(f"/api/core/planner/demands/{demand['id']}/plan", json={})
    assert planned.status_code == 201, planned.get_json()
    batch = planned.get_json()["batches"][0]
    page = browser.new_page(viewport={"width": width, "height": 900})
    posted = []

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
        if parsed.path.endswith("/action"):
            posted.append(response.status_code)
        route.fulfill(status=response.status_code, body=response.data, headers={"Content-Type": response.content_type})

    page.route("**/*", proxy)
    try:
        page.goto("https://planner.test/core/planner/board")
        # First check the day view, then a month containing the source and target.
        page.locator('[data-board-range] [name="date"]').fill(TODAY.isoformat())
        page.locator('[name="view"]').select_option("day")
        page.get_by_role("button", name="Show board").click()
        card = page.locator(f'[data-batch-id="{batch["id"]}"]')
        expect(card.get_by_role("button", name="Drag to move", exact=True)).to_be_visible()
        # The day form remains the keyboard/phone alternative. To exercise actual HTML5
        # drag events across dates, ask for a month containing both future dates.
        target_day = TODAY + timedelta(days=1)
        if target_day.month != TODAY.month:
            # Move to next month through the existing API, then render that month.
            moved = client.post(
                f"/api/core/planner/batches/{batch['id']}/action",
                json={
                    "action": "reschedule",
                    "expected_revision": batch["revision"],
                    "start_date": target_day.isoformat(),
                },
            )
            assert moved.status_code == 200
            batch = moved.get_json()
            target_day += timedelta(days=1)
        page.locator('[data-board-range] [name="date"]').fill(target_day.isoformat())
        page.locator('[name="view"]').select_option("month")
        page.get_by_role("button", name="Show board").click()
        target = page.locator(f'[data-board-date="{target_day.isoformat()}"]')
        expect(target).to_be_attached()
        handle = card.get_by_role("button", name="Drag to move", exact=True)
        expect(handle).to_be_visible()
        _drag_between_days(page, handle, target.locator("h3"))
        expect(target.locator(f'[data-batch-id="{batch["id"]}"]')).to_have_count(1)
        expect(page.locator("[data-board-notice]")).to_have_text("Batch moved to " + target_day.isoformat())
        assert posted == [200]
        current = next(
            row
            for row in client.get(
                "/api/core/planner/batches",
                query_string={"start": target_day.isoformat(), "end": target_day.isoformat()},
            ).get_json()["batches"]
            if row["id"] == batch["id"]
        )
        assert current["proposed_start_date"] == target_day.isoformat()
        # Pin from another session after rendering the draggable card.
        pinned = client.post(
            f"/api/core/planner/batches/{batch['id']}/action",
            json={"action": "pin", "expected_revision": current["revision"], "pinned": True},
        )
        assert pinned.status_code == 200
        another_day = target_day + timedelta(days=1)
        _drag_between_days(page, handle, page.locator(f'[data-board-date="{another_day.isoformat()}"] h3'))
        expect(page.locator("[data-board-error]")).to_contain_text("This batch changed")
        expect(card.get_by_role("button", name="Unpin batch", exact=True)).to_be_visible()
        expect(card.get_by_role("button", name="Drag to move", exact=True)).to_have_count(0)
        assert posted == [200, 409]
        observed = client.get(
            "/api/core/planner/batches", query_string={"start": target_day.isoformat(), "end": target_day.isoformat()}
        ).get_json()["batches"]
        assert any(row["id"] == batch["id"] and row["pinned"] for row in observed)
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    finally:
        page.close()
