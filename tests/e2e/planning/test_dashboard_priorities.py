"""Planned priorities on the live dashboard, including real HTTPS and CSRF."""

from datetime import date
from uuid import UUID

import pytest
from playwright.sync_api import expect

from app.core.db.models.user import UserRole
from tests.e2e.conftest import csrf_headers, login_through_ui
from tests.test_contract_orders import _recipe

pytestmark = pytest.mark.e2e


@pytest.mark.parametrize("width", [390, 1440])
def test_live_dashboard_shows_planned_priorities_and_escapes_references(browser, app_url, fresh_user, db, width):
    user = fresh_user(UserRole.PRODUCTION)
    process, _, output = _recipe(db, UUID(user["org_id"]))
    db.commit()
    context = browser.new_context(base_url=app_url, ignore_https_errors=True, viewport={"width": width, "height": 900})
    page = context.new_page()
    try:
        login_through_ui(page, user["email"], user["password"])
        catalog = page.request.get("/api/core/planner/workflows").json()["workflows"]
        workflow = next(row for row in catalog if row["id"] == str(output))
        headers = csrf_headers(page)
        setting = page.request.post(
            f"/api/core/planner/workflows/{process.id}/settings",
            headers=headers,
            data={
                "source_output_id": str(output),
                "batch_quantity": "600",
                "expected_revision": 0,
                "steps": [
                    {"step_id": step["step_id"], "duration_minutes": 60, "waiting_minutes": 0}
                    for step in workflow["steps"]
                ],
            },
        )
        assert setting.status == 200, setting.text()
        hostile = '<img src="x" onerror="alert(1)"> priority order'
        demand = page.request.post(
            "/api/core/planner/demands",
            headers=headers,
            data={
                "reference": hostile,
                "source_output_id": str(output),
                "quantity": "1200",
                "due_date": date.today().isoformat(),
                "priority": 85,
            },
        )
        assert demand.status == 201, demand.text()
        demand_id = demand.json()["id"]
        planned = page.request.post(f"/api/core/planner/demands/{demand_id}/plan", headers=headers, data={})
        assert planned.status == 201, planned.text()
        page.goto("/core/dashboard")
        expect(page.locator("[data-planned-batch-id]")).to_have_count(2)
        expect(page.locator("[data-planned-work-summary]")).to_contain_text("2 batch(es)")
        expect(page.locator("[data-planned-work-list] strong").first).to_contain_text(hostile)
        expect(page.locator("[data-planned-work-list]")).to_contain_text("Priority 85")
        assert page.locator("[data-planned-work-list] img").count() == 0
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth + 1")
        page.get_by_role("link", name="Review production board", exact=True).click()
        expect(page.get_by_role("heading", name="Production board", exact=True)).to_be_visible()
        expect(page.locator(".board-batch")).to_have_count(2)
    finally:
        context.close()
