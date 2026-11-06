"""GL-P07 B3 on a phone: what to make shows where each demand came from, stock cover says when a
product runs out, a target is set inline, and "Plan" plans the suggestion with a retry key."""

import json
from datetime import date, timedelta

import pytest
from playwright.sync_api import expect

from tests.e2e.test_planner_design import GIN, PINK, _demands
from tests.e2e.test_workspace_overviews import _page
from tests.e2e.test_workspace_overviews import workspace_user as _workspace_user

workspace_user = _workspace_user

pytestmark = pytest.mark.e2e


def _cover(gin_target="6"):
    def product(output, name, sentence, target, suggestion):
        return {
            "source_output_id": output,
            "name": name,
            "unit": "L",
            "window_weeks": 12,
            "weekly_rate": "38",
            "seasonality_factor": None,
            "seasonality": "Less than 12 months of sales, so no seasonal adjustment",
            "on_hand": "90",
            "planned": "0",
            "ordered": "0",
            "available": "90",
            "runs_out_on": (date.today() + timedelta(days=16)).isoformat(),
            "target_weeks": target,
            "batch_quantity": "120",
            "elapsed_days": 2,
            "suggestion": suggestion,
            "summary": sentence,
            "sentence": f"{name} {sentence}",
            "unknowns": [],
        }

    return {
        "window_weeks": 12,
        "sales_connected": True,
        "seasonal": False,
        "products": [
            product(
                GIN,
                "Navy Strength Gin",
                "Runs out 23 Nov at 38 L a week; plan 2 batches by 21 Nov.",
                gin_target,
                {
                    "batches": 2,
                    "quantity": "240",
                    "plan_by": date.today().isoformat(),
                    "due_date": date.today().isoformat(),
                },
            ),
            product(PINK, "Pink Gin", "Runs out 23 Nov at 38 L a week.", None, None),
        ],
        "unmapped_products": [
            {"product_name": "Gift voucher", "reason": "Sold, but its product mapping has no workflow output"}
        ],
    }


def _demands_with_sources():
    payload = _demands()
    payload["demands"][0].update(source="contract", reference="HS-1042 · Harbour Navy Gin")
    payload["demands"][1].update(
        source="contract",
        source_note="The order now asks for 200 L by 2026-12-01, but a batch has started; review the plan",
    )
    payload["demands"][3].update(source="forecast", reference="Stock target: Pink Gin")
    return payload


def test_phone_shows_sources_stock_cover_and_plans_a_suggestion(browser, app_url, workspace_user):
    context, page = _page(browser, app_url, workspace_user, 390)
    sent = {"sync": 0, "targets": [], "plans": []}

    def sync(route):
        sent["sync"] += 1
        route.fulfill(
            json={
                "changes": {},
                "held": [],
                "unmapped": [
                    {
                        "line_id": "l1",
                        "order_id": "o1",
                        "order_reference": "KB-0217",
                        "product_name": "Kawakawa Bitters",
                        "quantity": "240",
                        "unit": "bottles",
                        "reason": "Choose the workflow output this product is made by",
                    }
                ],
            }
        )

    def targets(route):
        sent["targets"].append(json.loads(route.request.post_data))
        route.fulfill(json={"target": {"weeks_of_cover": "8"}})

    def plan(route):
        sent["plans"].append((route.request.headers.get("idempotency-key"), json.loads(route.request.post_data)))
        route.fulfill(
            status=201,
            json={
                "demand": {},
                "batches": [
                    {"proposed_start_date": date.today().isoformat()},
                    {"proposed_start_date": date.today().isoformat()},
                ],
            },
        )

    try:
        page.route("**/api/core/planner/demands", lambda route: route.fulfill(json=_demands_with_sources()))
        page.route("**/api/core/planner/demand/sync", sync)
        page.route("**/api/core/planner/cover*", lambda route: route.fulfill(json=_cover()))
        page.route("**/api/core/planner/targets", targets)
        page.route("**/api/core/planner/cover/plan", plan)
        page.goto("/core/planner")
        expect(page.locator("[data-planner-layout]")).to_have_attribute("aria-busy", "false")
        assert sent["sync"] == 1  # the page brings contract orders up to date as it loads

        demand = page.locator("[data-demand-list] .planner-row")
        expect(demand.nth(0).locator(".planner-source")).to_have_text("Contract")
        expect(demand.nth(1)).to_contain_text("a batch has started; review the plan")
        expect(demand.nth(3).locator(".planner-source")).to_have_text("Stock target")
        expect(demand.nth(2).locator(".planner-source")).to_have_text("Order")
        expect(page.locator("[data-contract-unmapped]")).to_contain_text("KB-0217 · Kawakawa Bitters")
        expect(page.locator("[data-sales-unmapped]")).to_contain_text("Gift voucher")

        cover = page.locator("[data-cover-list] .planner-cover-row")
        expect(cover).to_have_count(2)
        expect(page.locator("[data-cover-site]")).to_be_hidden()  # one site: no picker
        expect(cover.nth(0)).to_contain_text("Runs out 23 Nov at 38 L a week; plan 2 batches by 21 Nov.")
        expect(cover.nth(1).get_by_role("button")).to_have_count(0)  # no target, nothing to plan

        target = page.get_by_label("Weeks of cover to keep: Navy Strength Gin")
        expect(target).to_have_value("6")
        target.fill("8")
        target.press("Tab")
        expect(page.locator("[data-planning-status]")).to_have_text("Keeping 8 weeks of Navy Strength Gin.")
        assert sent["targets"] == [{"source_output_id": GIN, "weeks_of_cover": "8", "site_id": None}]

        page.get_by_role("button", name="Plan 2 batches of Navy Strength Gin").click()
        expect(page.locator("[data-planning-status]")).to_contain_text("Planned 2 batches of Navy Strength Gin")
        key, body = sent["plans"][0]
        assert body == {"source_output_id": GIN, "site_id": None}
        assert key and len(key) >= 8

        # Nothing on a phone scrolls sideways.
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    finally:
        context.close()


MAIN, CELLAR = "aaaaaaaa-0000-4000-8000-000000000001", "aaaaaaaa-0000-4000-8000-000000000002"


def test_phone_site_picker_drives_cover_targets_and_plan(browser, app_url, workspace_user):
    """With several sites, stock cover, a target and Plan are all for the site chosen."""
    context, page = _page(browser, app_url, workspace_user, 390)
    asked, sent = [], {"targets": [], "plans": []}

    def cover(route):
        site = route.request.url.partition("site_id=")[2] or MAIN
        asked.append(site)
        body = _cover()
        body.update(
            site_id=site,
            sites=[
                {"id": MAIN, "name": "Main distillery", "is_default": True},
                {"id": CELLAR, "name": "Cellar door", "is_default": False},
            ],
        )
        route.fulfill(json=body)

    try:
        page.route("**/api/core/planner/demands", lambda route: route.fulfill(json=_demands()))
        page.route(
            "**/api/core/planner/demand/sync",
            lambda route: route.fulfill(json={"changes": {}, "held": [], "unmapped": []}),
        )
        page.route("**/api/core/planner/cover*", cover)
        page.route(
            "**/api/core/planner/targets",
            lambda route: (
                sent["targets"].append(json.loads(route.request.post_data)),
                route.fulfill(json={"target": None}),
            ),
        )
        page.route(
            "**/api/core/planner/cover/plan",
            lambda route: (
                sent["plans"].append(json.loads(route.request.post_data)),
                route.fulfill(
                    status=201, json={"demand": {}, "batches": [{"proposed_start_date": date.today().isoformat()}]}
                ),
            ),
        )
        page.goto("/core/planner")
        picker = page.get_by_label("Site")
        expect(picker).to_have_value(MAIN)
        picker.select_option(label="Cellar door")
        expect(picker).to_have_value(CELLAR)
        assert asked[-1] == CELLAR

        target = page.get_by_label("Weeks of cover to keep: Navy Strength Gin")
        target.fill("")
        target.press("Tab")
        expect(page.locator("[data-planning-status]")).to_contain_text("Stock target cleared")
        assert sent["targets"] == [{"source_output_id": GIN, "weeks_of_cover": None, "site_id": CELLAR}]

        page.get_by_role("button", name="Plan 2 batches of Navy Strength Gin").click()
        expect(page.locator("[data-planning-status]")).to_contain_text("Planned 1 batch")
        assert sent["plans"] == [{"source_output_id": GIN, "site_id": CELLAR}]
        assert asked[-1] == CELLAR  # the reload after planning stays on the chosen site
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    finally:
        context.close()
