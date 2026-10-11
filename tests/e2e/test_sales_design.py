"""Sales concepts preserve the dashboard while matching the settled section head."""

import json
import re

import pytest
from playwright.sync_api import expect

from tests.e2e.test_workspace_overviews import _page
from tests.e2e.test_workspace_overviews import workspace_user as _workspace_user

workspace_user = _workspace_user

pytestmark = pytest.mark.e2e

OVERVIEW = {
    "current_month_revenue": 12450,
    "current_month_invoice_count": 6,
    "outstanding_receivables": 3250,
    "outstanding_invoice_count": 2,
    "top_products": [],
    "top_customers": [],
    "overview_tasks": [
        {
            "id": "task-one",
            "title": "Confirm Regional Wines order",
            "status": "pending",
            "priority": "high",
            "due_date": "2026-10-14",
        },
    ],
}
MONTHLY = {"monthly_sales": [{"month": "2026-08", "total": 10000}, {"month": "2026-09", "total": 12450}]}


def _data(page):
    page.route("**/api/crm/overview", lambda route: route.fulfill(json=OVERVIEW))
    page.route("**/api/crm/analytics/monthly-sales*", lambda route: route.fulfill(json=MONTHLY))


def _ready(page, style="1"):
    page.goto(f"/crm?style={style}")
    expect(page.get_by_role("heading", name="Sales Trend", exact=True)).to_be_visible()


# CONCEPT ONLY — deleted with the losing layouts.
@pytest.mark.parametrize("style", ["1", "2", "3"])
@pytest.mark.parametrize("width", [390, 1024, 1440, 1920])
def test_concepts_preserve_regions_and_header_without_overflow(browser, app_url, workspace_user, style, width):
    context, page = _page(browser, app_url, workspace_user, width)
    try:
        _data(page)
        _ready(page, style)
        expect(page.locator(".sales-overview")).to_have_attribute("data-sales-style", style)
        expect(page.get_by_role("heading", level=1)).to_have_text("Sales")
        title = page.get_by_role("heading", level=1).bounding_box()
        tabs = page.get_by_role("navigation", name="Sales sections", exact=True).bounding_box()
        glance = page.get_by_role("region", name="At a glance", exact=True).bounding_box()
        assert title["y"] < tabs["y"] < glance["y"]
        expect(page.get_by_role("link", name="Open tasks", exact=True)).to_be_visible()
        expect(page.get_by_role("button", name="Add widget", exact=True)).to_be_visible()
        for name in ["Sales Trend", "Task Board", "Top Products", "Top Customers"]:
            expect(page.get_by_role("heading", name=name, exact=True)).to_be_visible()
        if width >= 1280 and style == "1":
            trend = page.locator('[data-widget-type="sales_trend"]').bounding_box()
            assert abs(glance["y"] - trend["y"]) < 2
            assert glance["x"] + glance["width"] <= trend["x"]
        page.wait_for_timeout(100)
        assert page.locator("#crmOverviewSalesChart").evaluate(
            "canvas => Math.abs(canvas.width / devicePixelRatio - canvas.parentElement.getBoundingClientRect().width) < 2"
        )
        headings = page.locator(".crm-widget-card h2").all_text_contents()
        if style == "2":
            assert headings == ["Sales Trend", "Top Products", "Top Customers", "Task Board"]
        elif style == "3":
            assert headings == ["Task Board", "Sales Trend", "Top Products", "Top Customers"]
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth + 1")
    finally:
        context.close()


def test_initial_load_requests_overview_once(browser, app_url, workspace_user):
    context, page = _page(browser, app_url, workspace_user, 1440)
    try:
        _data(page)
        calls = []
        page.on(
            "request", lambda request: calls.append(request.url) if request.url.endswith("/api/crm/overview") else None
        )
        _ready(page)
        page.wait_for_load_state("networkidle")
        assert len(calls) == 1, calls
    finally:
        context.close()


def test_tasks_expand_with_keyboard_and_filter_to_nothing(browser, app_url, workspace_user):
    context, page = _page(browser, app_url, workspace_user, 1440)
    try:
        _data(page)
        _ready(page)
        task = page.get_by_role("button", name="Confirm Regional Wines order", exact=True)
        task.focus()
        task.press("Enter")
        expect(task).to_have_attribute("aria-expanded", "true")
        expect(task.get_by_role("button", name="Open in Tasks", exact=True)).to_be_visible()
        task.press("Space")
        expect(task).to_have_attribute("aria-expanded", "false")
        operator = page.get_by_label("Filter tasks by operator")
        operator_id = operator.locator("option").nth(1).get_attribute("value")
        operator.select_option(operator_id)
        expect(task).to_be_hidden()
        operator.select_option("")
        expect(task).to_be_visible()
    finally:
        context.close()


def test_expanded_task_action_works_with_keyboard(browser, app_url, workspace_user):
    context, page = _page(browser, app_url, workspace_user, 1440)
    try:
        _data(page)
        _ready(page)
        task = page.get_by_role("button", name="Confirm Regional Wines order", exact=True)
        task.press("Enter")
        task.get_by_role("button", name="Open in Tasks", exact=True).press("Enter")
        expect(page).to_have_url(re.compile(r"/crm/tasks(?:\?|$)"))
    finally:
        context.close()


@pytest.mark.parametrize("status", [401, 403, 503])
def test_initial_error_never_looks_like_zero_sales(browser, app_url, workspace_user, status):
    context, page = _page(browser, app_url, workspace_user, 1440)
    try:
        _data(page)
        page.unroute("**/api/crm/overview")
        page.route(
            "**/api/crm/overview", lambda route: route.fulfill(status=status, json={"error": "Sales unavailable"})
        )
        page.goto("/crm")
        expect(page.get_by_role("region", name="Sales unavailable", exact=True)).to_be_visible()
        expect(page.get_by_role("region", name="At a glance", exact=True)).to_be_hidden()
        if status == 503:
            page.unroute("**/api/crm/overview")
            page.route("**/api/crm/overview", lambda route: route.fulfill(json=OVERVIEW))
            page.get_by_role("button", name="Retry", exact=True).click()
            expect(page.get_by_role("region", name="At a glance", exact=True)).to_be_visible()
            expect(page.get_by_role("region", name="Sales unavailable", exact=True)).to_be_hidden()
        else:
            expect(page.get_by_role("button", name="Retry", exact=True)).to_be_hidden()
    finally:
        context.close()


def test_header_add_widget_and_saved_layout_survive_concept_switch(browser, app_url, workspace_user):
    context, page = _page(browser, app_url, workspace_user, 1440)
    try:
        _data(page)
        page.evaluate(
            "localStorage.setItem('crm_overview_widgets_v3', JSON.stringify([{id:'top-customers',kind:'system',size:'full',locked:false}]))"
        )
        _ready(page, "3")
        expect(page.locator(".crm-widget-card h2").first).to_have_text("Top Customers")
        page.get_by_role("button", name="Add widget", exact=True).click()
        expect(page.get_by_role("heading", name="Add Custom Widget", exact=True)).to_be_visible()
        page.get_by_role("button", name="Cancel", exact=True).first.click()
        page.get_by_role("button", name="1 · Board", exact=True).click()
        expect(page.locator(".sales-overview")).to_have_attribute("data-sales-style", "1")
        assert json.loads(page.evaluate("localStorage.getItem('crm_overview_widgets_v3')"))[0]["id"] == "top-customers"
        page.get_by_role("tab", name="Customers", exact=True).click()
        expect(page.get_by_role("tab", name="Customers", exact=True)).to_have_attribute("aria-selected", "true")
        page.get_by_role("tab", name="Overview", exact=True).click()
        expect(page.locator(".sales-overview")).to_have_attribute("data-sales-style", "1")
        expect(page.locator(".crm-widget-card h2").first).to_have_text("Top Customers")
    finally:
        context.close()
