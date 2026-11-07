"""Real phone rendering; real Flask-WTF coverage is in test_material_adapter."""

from urllib.parse import urlsplit

import pytest

from app.core.db.models.step import Step
from tests.features.planning import test_material_adapter as fixtures

board_clients = fixtures.board_clients
base_board_clients = fixtures.base_board_clients
demand_clients = fixtures.demand_clients
flask_app = fixtures.flask_app
pytestmark = pytest.mark.e2e


def test_phone_binds_raw_lot_and_shows_what_it_holds_for_each_batch(db, board_clients, browser):
    client, org_id, output = board_clients[0]
    step = db.query(Step).filter(Step.org_id == org_id).one()
    step.inputs = [{"name": "Sugar <script>alert(1)</script>", "quantity": "2", "unit": "kg"}]
    lot = fixtures.lot(db, org_id, name="Sugar <img src=x onerror=alert(1)>")
    fixtures.fixtures.native_recipe(db, org_id, step.process_id)
    db.commit()
    client.post("/api/core/planner/demands", json=fixtures.fixtures.payload(output))
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
        page.locator('[name="waiting_minutes"]').fill("0")
        page.locator("[data-material-step]").select_option(str(lot.id))
        page.get_by_role("button", name="Save planning settings").click()
        page.get_by_text("Planning settings saved", exact=True).wait_for()
        page.get_by_role("button", name="Plan batches").click()
        page.locator(".board-batch").first.wait_for()
        page.get_by_role("button", name="Check materials").click()
        page.get_by_text(
            "Materials observed. Refresh after stock changes; delivery and start checks remain pending.", exact=True
        ).wait_for()
        assert page.locator(".board-batch").count() == 3
        # GL-P07 B2: the 5 kg lot covers two 2 kg batches and is held for them; the third is 1 kg short.
        assert page.get_by_text("There isn't enough in stock for this batch yet", exact=True).count() == 1
        held = page.get_by_text("Sugar <img src=x onerror=alert(1)> · 2 kg held", exact=True)
        assert held.count() == 2
        assert page.get_by_text("Short of the chosen lot: 1 kg", exact=True).count() == 1
        # A batch that cannot start (the short third one) keeps its disabled Start button in its
        # Details. Since B4 the first two, their materials held, really can start.
        short = page.locator(".board-batch").nth(2)
        short.locator(".board-batch__details > summary").click()
        assert short.get_by_role("button", name="Start batch").is_disabled()
        assert page.locator(".board-batch").first.get_by_role("button", name="Start batch").is_enabled()
        assert page.locator("[data-board-root] script, [data-board-root] img").count() == 0
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
        assert page.locator("[data-board-root] input, [data-board-root] select").evaluate_all(
            "els => els.every(el => {const r=el.getBoundingClientRect(); return r.left >= 0 && r.right <= innerWidth;})"
        )
        assert page.locator("[data-material-step]").input_value() == str(lot.id)
    finally:
        page.close()
