"""Every page behind the Production tabs uses the shared header, stack and cards (see
docs/production-pages-cleanup-plan.md), and holds together at phone, laptop and desktop widths."""

import os
from pathlib import Path
from uuid import UUID

import pytest
from playwright.sync_api import expect

from app.core.db.models.user import UserRole
from tests.e2e.conftest import login_through_ui
from tests.factories import ExecutionFactory, InventoryItemFactory, ProcessFactory

pytestmark = pytest.mark.e2e

# path -> (page heading, a card heading that must be present)
PAGES = {
    "/core/planner": ("Planner", "Production demand"),
    "/core/planner/board": ("Production board", "Rough site capacity"),
    "/core/contracts": ("Contract orders", "Orders"),
    "/core/contracts/materials": ("Customer materials", "Materials held"),
    "/core/processes": ("Workflows", "Product workflows"),
    "/core/executions/live": ("Batches", "Production board"),
    "/core/inventory/view": ("Inventory", "Stock on hand"),
    "/core/inventory/live": ("Live inventory", "Stock"),
    "/core/inventory/add": ("Add to inventory", "How would you like to add it?"),
    "/core/inventory/dispose": ("Record disposal", "What are you disposing of?"),
    "/core/stocktake": ("Stocktake", "Schedule"),
    "/core/sourcemap": ("Trace and recall", "Source map"),
    "/core/site-transfers": ("Stock transfers", "Transfers"),
    "/core/suppliers": ("Suppliers", "At a glance"),
    "/core/tasks": ("Production tasks", "Task board"),
    "/core/cases": ("Cases", "Case queue"),
}


@pytest.fixture
def production_user(fresh_user, db):
    user = fresh_user(UserRole.ADMIN)
    org_id = UUID(user["org_id"])
    InventoryItemFactory(org_id=org_id, name="Botanical blend", quantity="240")
    process = ProcessFactory(org_id=org_id, name="Gin distillation")
    ExecutionFactory(org_id=org_id, process_id=process.id)
    db.commit()
    return user


@pytest.mark.parametrize("width", [390, 1024, 1440])
def test_production_pages_share_the_header_and_card_layout(browser, app_url, production_user, width):
    context = browser.new_context(base_url=app_url, ignore_https_errors=True, viewport={"width": width, "height": 1000})
    page = context.new_page()
    login_through_ui(page, production_user["email"], production_user["password"])
    directory = os.environ.get("UI_SCREENSHOT_DIR")
    try:
        for path, (title, card_title) in PAGES.items():
            page.goto(path)
            column = page.locator("#page-content .workspace-page")
            expect(column, path).to_have_count(1)
            expect(column.locator(".workspace-header h1"), path).to_have_text(title)
            expect(column.get_by_role("heading", name=card_title, exact=True).first, path).to_be_visible()
            page.wait_for_load_state("networkidle")

            cards = [card for card in column.locator(".workspace-stack > .workspace-card").all() if card.is_visible()]
            assert cards, f"{path}: no cards"
            outer = column.bounding_box()
            lefts, rights = set(), set()
            for card in cards:
                box = card.bounding_box()
                lefts.add(round(box["x"]))
                rights.add(round(box["x"] + box["width"]))
                assert box["x"] >= outer["x"] and box["x"] + box["width"] <= outer["x"] + outer["width"] + 1, path
            assert len(lefts) == 1 and len(rights) == 1, f"{path}: cards do not share one column ({lefts}, {rights})"
            # Health and next-step cards belong to the overview only.
            expect(page.get_by_role("region", name="Production health", exact=True), path).to_have_count(
                0
            ) if path != "/core/tasks" else expect(
                page.get_by_role("region", name="Production health", exact=True), path
            ).not_to_be_visible()
            assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth + 1"), (
                f"{path} scrolls sideways"
            )
            if directory:
                Path(directory).mkdir(parents=True, exist_ok=True)
                name = path.strip("/").replace("/", "-")
                page.screenshot(path=str(Path(directory) / f"{name}-{width}.png"), full_page=True)
    finally:
        context.close()


def test_planner_links_to_the_board_and_back(browser, app_url, production_user):
    context = browser.new_context(base_url=app_url, ignore_https_errors=True, viewport={"width": 1440, "height": 1000})
    page = context.new_page()
    login_through_ui(page, production_user["email"], production_user["password"])
    try:
        page.goto("/core/planner")
        page.get_by_role("link", name="Production board", exact=True).click()
        expect(page.locator(".workspace-header h1")).to_have_text("Production board")
        page.get_by_role("link", name="Production demand", exact=True).click()
        expect(page.locator(".workspace-header h1")).to_have_text("Planner")
        page.goto("/core/inventory/view")
        tools = page.get_by_role("region", name="Inventory tools", exact=True)
        for name in ["Trace and recall", "Stocktake", "Stock transfers", "Record disposal", "Suppliers"]:
            expect(tools.get_by_role("link", name=name)).to_be_visible()
    finally:
        context.close()
