"""A producer can observe a configured resource overload on the phone board."""

from datetime import timedelta
from urllib.parse import urlsplit

import pytest

from app.core.db.models.site import Site
from app.features.planning.batch_models import PlanningBatch
from app.features.planning.capacity_models import PlanningCapacitySetting
from tests.features.planning import test_batches as fixtures

board_clients = fixtures.board_clients
demand_clients = fixtures.demand_clients
flask_app = fixtures.flask_app
payload = fixtures.payload
TODAY = fixtures.TODAY

pytestmark = pytest.mark.e2e


@pytest.mark.parametrize("width", [390, 1440])
def test_phone_capacity_group_step_and_overload(db, board_clients, browser, width):
    client, org_id, output = board_clients[0]
    site = Site(org_id=org_id, name="Main", is_default=True)
    db.add(site)
    db.commit()
    client.post(
        "/api/core/planner/demands",
        json=payload(output, reference="Capacity order", due_date=(TODAY + timedelta(days=2)).isoformat()),
    )
    page = browser.new_page(viewport={"width": width, "height": 844})

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
        page.locator("[data-capacity-settings] summary").click()
        page.locator("[data-capacity-site] option").wait_for(state="attached")
        page.locator('[data-capacity-group-form] [name="name"]').fill("Bottling line")
        page.locator('[data-capacity-group-form] [name="minutes_per_day"]').fill("120")
        page.get_by_role("button", name="Add group").click()
        page.get_by_text("Resource group saved; assign steps", exact=False).wait_for()
        page.locator("[data-capacity-group] option").wait_for(state="attached")
        page.get_by_role("button", name="Assign step").click()
        page.get_by_text("Step resource assignment saved", exact=False).wait_for()

        page.locator("[data-workflow-settings] summary").click()
        page.locator('[name="batch_quantity"]').fill("250")
        page.locator('[name="duration_minutes"]').fill("60")
        page.locator('[name="waiting_minutes"]').fill("2820")
        page.get_by_role("button", name="Save planning settings").click()
        page.get_by_text("Planning settings saved", exact=True).wait_for()
        page.get_by_role("button", name="Plan batches").click()
        page.get_by_text("1 overloaded resource-day(s) in this view.", exact=True).wait_for()
        page.get_by_text("180/120 minutes", exact=False).wait_for()
        calendar = page.locator("[data-capacity-calendar]")
        today_checkbox = calendar.locator(f'[name="working_days"][value="{TODAY.weekday()}"]')
        today_checkbox.uncheck()
        calendar.get_by_role("button", name="Save calendar").click()
        page.get_by_text("Resource calendar saved", exact=True).wait_for()
        page.get_by_text("180/0 minutes", exact=False).wait_for()
        page.get_by_text("resource closed", exact=False).wait_for()
        today_checkbox.check()
        calendar.locator('[name="closed_dates"]').fill(TODAY.isoformat())
        calendar.get_by_role("button", name="Save calendar").click()
        page.get_by_text("Resource calendar saved", exact=True).wait_for()
        page.get_by_text("180/0 minutes", exact=False).wait_for()
        calendar.locator('[name="closed_dates"]').fill("")
        calendar.get_by_role("button", name="Save calendar").click()
        page.get_by_text("Resource calendar saved", exact=True).wait_for()
        page.get_by_text("180/120 minutes", exact=False).wait_for()
        page.get_by_role("button", name="Review and move suggested batch").first.click()
        page.get_by_text("Choose a new start date, then move the suggested batch.", exact=True).wait_for()
        focused = page.locator('[name="start_date"]:focus')
        assert focused.count() == 1
        next_day = (TODAY + timedelta(days=1)).isoformat()
        focused.fill(next_day)
        focused.locator("..").locator("..").get_by_role("button", name="Move batch", exact=True).click()
        page.get_by_text("Plan updated", exact=True).wait_for()
        page.get_by_text("No overload in configured groups for this view.", exact=False).wait_for()
        # A two-day resource load still appears on tomorrow even when its batch
        # starts outside the selected day. The review action must open its start day.
        catalog = client.get("/api/core/planner/workflows").get_json()["workflows"]
        workflow = next(row for row in catalog if row["id"] == str(output))
        updated = client.post(
            f"/api/core/planner/workflows/{workflow['process_id']}/settings",
            json={
                "source_output_id": str(output),
                "batch_quantity": "250",
                "expected_revision": workflow["setting"]["revision"],
                "steps": [
                    {"step_id": step["step_id"], "duration_minutes": 2880, "waiting_minutes": 0}
                    for step in workflow["steps"]
                ],
            },
        )
        assert updated.status_code == 200, updated.get_json()
        demand = client.post(
            "/api/core/planner/demands",
            json=payload(
                output,
                quantity="250",
                priority=0,
                reference="Two-day bottling run",
                due_date=(TODAY + timedelta(days=2)).isoformat(),
            ),
        ).get_json()
        planned = client.post(f"/api/core/planner/demands/{demand['id']}/plan", json={})
        assert planned.status_code == 201, planned.get_json()
        long_batch = planned.get_json()["batches"][0]
        assert long_batch["proposed_start_date"] == TODAY.isoformat()
        page.locator('[data-board-range] [name="date"]').fill(next_day)
        page.locator('[data-board-range] [name="view"]').select_option("day")
        page.get_by_role("button", name="Show board").click()
        page.get_by_text(next_day + " – " + next_day, exact=True).wait_for()
        assert page.locator(f'[data-batch-id="{long_batch["id"]}"]').count() == 0
        page.get_by_role("button", name="Review and move suggested batch").first.click()
        page.get_by_text(TODAY.isoformat() + " – " + TODAY.isoformat(), exact=True).wait_for()
        page.get_by_text("Choose a new start date, then move the suggested batch.", exact=True).wait_for()
        assert (
            page.locator('[name="start_date"]:focus').evaluate("el => el.closest('[data-batch-id]').dataset.batchId")
            == long_batch["id"]
        )
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    finally:
        page.close()
        db.rollback()
        db.query(PlanningBatch).filter(PlanningBatch.org_id == org_id).delete()
        db.query(PlanningCapacitySetting).filter(PlanningCapacitySetting.org_id == org_id).delete()
        db.query(Site).filter(Site.org_id == org_id).delete()
        db.commit()
