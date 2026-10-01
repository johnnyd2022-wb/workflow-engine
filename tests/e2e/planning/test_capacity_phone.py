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
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    finally:
        page.close()
        db.rollback()
        db.query(PlanningBatch).filter(PlanningBatch.org_id == org_id).delete()
        db.query(PlanningCapacitySetting).filter(PlanningCapacitySetting.org_id == org_id).delete()
        db.query(Site).filter(Site.org_id == org_id).delete()
        db.commit()
