"""AC1–5: quiet workspaces, real HTTPS login, contextual navigation and health states."""

import json
import os
import re
from datetime import date, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from playwright.sync_api import expect

from app.core.db.models.user import UserRole
from app.core.db.repositories.feature_subscription_repo import FeatureSubscriptionRepository
from app.features.crm.models.crm_task import CRMTask
from app.features.crm.models.xero_contact import XeroContact
from app.features.crm.models.xero_invoice import XeroInvoice
from tests.e2e.conftest import csrf_headers, login_through_ui
from tests.factories import ExecutionFactory, InventoryItemFactory, ProcessFactory

pytestmark = pytest.mark.e2e


@pytest.fixture
def workspace_user(fresh_user, db):
    user = fresh_user(UserRole.ADMIN)
    org_id = UUID(user["org_id"])
    FeatureSubscriptionRepository(db).grant(org_id, "compliant")
    InventoryItemFactory(org_id=org_id, name="Botanical blend", quantity="240")
    process = ProcessFactory(org_id=org_id, name="Gin distillation")
    ExecutionFactory(org_id=org_id, process_id=process.id)
    db.commit()
    return user


def _page(browser, app_url, user, width):
    context = browser.new_context(base_url=app_url, ignore_https_errors=True, viewport={"width": width, "height": 1000})
    page = context.new_page()
    login_through_ui(page, user["email"], user["password"])
    return context, page


def _capture(page, name, width):
    directory = os.environ.get("UI_SCREENSHOT_DIR")
    if directory:
        Path(directory).mkdir(parents=True, exist_ok=True)
        page.wait_for_load_state("networkidle")
        page.screenshot(path=str(Path(directory) / f"{name}-{width}.png"), full_page=True)


@pytest.mark.parametrize("width", [390, 1440])
def test_ac1_ac4_ac5_four_primary_destinations_and_context_actions(browser, app_url, workspace_user, width):
    context, page = _page(browser, app_url, workspace_user, width)
    try:
        saved = page.request.put(
            "/api/compliant/profile",
            headers=csrf_headers(page),
            data={"enabled": True, "settings": {"food_control_programme": "np3", "liquor_licence_types": ["on"]}},
        )
        assert saved.ok, saved.text()
        for name, path, labels, secondary in [
            ("production", "/core", ["Overview", "Planner", "Workflows", "Inventory"], "Contract orders"),
            ("compliance", "/compliant/nz-alcohol", ["Overview", "NP3", "Customs", "Licensing"], "Premises"),
            ("sales", "/crm", ["Overview", "Customers", "Tasks", "Analytics"], "Batch matching"),
        ]:
            page.goto(path)
            nav = page.get_by_role("navigation", name=f"{name.title()} sections", exact=True)
            expect(nav.get_by_role("tab")).to_have_count(4)
            expect(nav.get_by_role("tab")).to_have_text(labels)
            expect(page.get_by_role("heading", name=name.title(), exact=True)).to_be_visible()
            actions = page.get_by_role("region", name=f"{name.title()} workspace actions", exact=True)
            expect(actions.get_by_role("link", name=secondary)).to_be_visible()
            assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth + 1")
            _capture(page, f"after-{name}", width)
            actions.get_by_role("link", name=secondary).click()
            expect(page.get_by_role("navigation", name=f"{name.title()} sections", exact=True)).to_be_visible()
            parent = {"production": "Planner", "compliance": "Overview", "sales": "Analytics"}[name]
            expect(page.get_by_role("tab", name=parent, exact=True)).to_have_attribute("aria-selected", "true")
        page.evaluate("localStorage.setItem('spa-theme', 'dark')")
        for name, path in [("production", "/core"), ("compliance", "/compliant/nz-alcohol"), ("sales", "/crm")]:
            page.goto(path)
            expect(page.get_by_role("heading", name=name.title(), exact=True)).to_be_visible()
            assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth + 1")
            _capture(page, f"after-{name}-dark", width)
        page.evaluate("localStorage.removeItem('spa-theme')")
        page.goto("/core?tab=inventory")
        expect(page.get_by_role("region", name="Inventory workspace", exact=True)).to_be_visible()
        expect(page.get_by_role("tab", name="Inventory", exact=True)).to_have_attribute("aria-selected", "true")
        page.get_by_role("link", name="Back to overview").click()
        expect(page.get_by_role("heading", name="Production", exact=True)).to_be_visible()
        expect(page.get_by_role("tablist", name="Production pages")).to_have_count(1)
    finally:
        context.close()


@pytest.mark.parametrize(
    "state,title",
    [
        ("healthy", "Production healthy"),
        ("degraded", "Needs attention"),
        ("critical", "Action required"),
        ("unavailable", "Health check unavailable"),
    ],
)
@pytest.mark.parametrize("width", [390, 1440])
def test_ac2_ac3_health_card_and_inventory_menu(browser, app_url, workspace_user, width, state, title):
    context, page = _page(browser, app_url, workspace_user, width)
    signals = (
        []
        if state == "healthy"
        else [
            {
                "category": "traceability",
                "has_issue": True,
                "in_active_use": state == "critical",
                "message": "Review the production trace links",
            }
        ]
    )
    payload = {"findings": [], "system_status": {"mode": "health", "state": state, "signals": signals}}
    page.route(
        "**/api/core/system-findings*",
        lambda route: route.fulfill(status=503)
        if state == "unavailable"
        else route.fulfill(content_type="application/json", body=json.dumps(payload)),
    )
    try:
        page.goto("/core")
        health = page.get_by_role("region", name="Production health", exact=True)
        expect(health.get_by_text(title, exact=True)).to_be_visible()
        expected_colours = {
            "healthy": "rgb(21, 149, 112)",
            "degraded": "rgb(217, 134, 8)",
            "critical": "rgb(220, 59, 59)",
            "unavailable": "rgb(148, 163, 184)",
        }
        expect(health.get_by_test_id("production-health-bar").locator("span")).to_have_css(
            "background-color", expected_colours[state]
        )
        _capture(page, f"health-{state}", width)
        if state != "unavailable":
            detail = health.get_by_role("button", name="View health details")
            detail.focus()
            page.keyboard.press("Enter")
            expect(page.get_by_role("dialog")).to_be_visible()
            page.keyboard.press("Escape")
            expect(page.get_by_role("dialog")).not_to_be_visible()
            expect(detail).to_be_focused()
        actions = page.get_by_role("region", name="Get to work", exact=True)
        actions.get_by_role("button", name="Add to inventory, choose how").click()
        for label in ["Manual entry", "CSV upload"]:
            expect(actions.get_by_role("menuitem", name=label, exact=True)).to_be_visible()
        expect(actions.get_by_role("menuitem", name="Barcode / camera scan", include_hidden=True)).to_have_attribute(
            "href", "/core/inventory/add/barcode"
        )
        page.keyboard.press("Escape")
        expect(actions.get_by_role("menu")).not_to_be_visible()
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth + 1")
    finally:
        context.close()


@pytest.mark.parametrize("width", [390, 1440])
def test_ac3_setup_and_pending_never_claim_healthy(browser, app_url, workspace_user, fresh_user, width):
    empty_user = fresh_user(UserRole.ADMIN)
    context, page = _page(browser, app_url, empty_user, width)
    try:
        page.goto("/core")
        health = page.get_by_role("region", name="Production health", exact=True)
        expect(health.get_by_text("Finish your setup", exact=True)).to_be_visible()
        expect(health.get_by_role("progressbar", name="Traceability setup")).to_have_attribute("aria-valuenow", "0")
        _capture(page, "production-empty", width)
        page.get_by_role("button", name="Add to inventory, choose how").click()
        page.get_by_role("menuitem", name="Manual entry", exact=True).click()
        expect(page).to_have_url(f"{app_url}/core/inventory/add/manual")
    finally:
        context.close()
    context, page = _page(browser, app_url, workspace_user, width)
    # Hold only the health response: the real hub still loads its aggregate and actions.
    page.route("**/api/core/system-findings*", lambda route: None)
    try:
        page.goto("/core")
        health = page.get_by_role("region", name="Production health", exact=True)
        expect(health.get_by_text("Your latest checks are on their way.", exact=True)).to_be_visible()
        expect(health.get_by_text("Production healthy", exact=True)).to_have_count(0)
        expect(health.get_by_role("button", name="View health details")).to_have_count(0)
        directory = os.environ.get("UI_SCREENSHOT_DIR")
        if directory:
            page.screenshot(path=str(Path(directory) / f"production-pending-{width}.png"), full_page=True)
    finally:
        context.close()


@pytest.mark.parametrize("width", [390, 1024, 1440])
def test_production_overview_reads_health_first_and_opens_a_batch(browser, app_url, workspace_user, width):
    context, page = _page(browser, app_url, workspace_user, width)
    try:
        page.goto("/core")
        tabs = page.get_by_role("navigation", name="Production sections", exact=True).get_by_role("tab")
        fills = tabs.evaluate_all("tabs => tabs.map(tab => getComputedStyle(tab).backgroundColor)")
        assert fills[0] != "rgba(0, 0, 0, 0)" and set(fills[1:]) == {"rgba(0, 0, 0, 0)"}, (
            "only the current page is filled"
        )
        widths = {round(tab.bounding_box()["width"]) for tab in tabs.all()}
        assert len(widths) == 1, "the selector spans the column in equal segments"

        health = page.get_by_role("region", name="Production health", exact=True)
        expect(health.get_by_role("group", name="At a glance")).to_be_visible()
        expect(health.get_by_role("group", name="Operational status").get_by_role("link")).to_have_count(5)
        manage = page.get_by_role("region", name="Production workspace actions", exact=True)
        expect(manage.get_by_role("link")).to_have_count(5)
        board = manage.get_by_role("link", name="View production board", exact=True)
        expect(board).to_have_attribute("href", "/core/executions/live")
        active = page.get_by_role("region", name="Active production", exact=True)
        stack = [
            health,
            page.get_by_role("region", name="Get to work", exact=True),
            manage,
            active,
        ]
        boxes = [item.bounding_box() for item in stack]
        assert [box["y"] for box in boxes] == sorted(box["y"] for box in boxes)
        assert len({round(box["width"]) for box in boxes}) == 1, "every block spans the content column"
        links = [link.bounding_box() for link in manage.get_by_role("link").all()]
        assert links[0]["y"] == links[1]["y"] and links[2]["y"] == links[3]["y"] > links[0]["y"]
        assert len({round(link["width"]) for link in links[:4]}) == 1
        assert links[4]["y"] > links[3]["y"] and links[4]["width"] > links[0]["width"] * 2
        plain = manage.get_by_role("link").first.evaluate("link => getComputedStyle(link).backgroundColor")
        expect(board).to_have_css("background-color", plain)

        batch = active.locator("details").first
        record = batch.get_by_role("link", name="Record next step", exact=True)
        expect(record).not_to_be_visible()
        batch.locator("summary").click()
        for label in ["Status", "Next step", "Progress", "Started"]:
            expect(batch.get_by_text(label, exact=True)).to_be_visible()
        expect(batch.get_by_role("link")).to_have_count(1)
        assert "/core/flows/batches/start?id=" in record.get_attribute("href")
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth + 1")
        _capture(page, "production-layout", width)
        batch.locator("summary").click()
        expect(record).not_to_be_visible()
        batch.locator("summary").click()
        record.click()
        expect(page).to_have_url(re.compile(r"/core/flows/batches/start\?.*execution_id="))
    finally:
        context.close()


@pytest.mark.parametrize("width", [390, 1024, 1440])
def test_compliance_overview_groups_obligations_and_actions_in_cards(browser, app_url, workspace_user, width):
    context, page = _page(browser, app_url, workspace_user, width)
    try:
        saved = page.request.put(
            "/api/compliant/profile",
            headers=csrf_headers(page),
            data={"enabled": True, "settings": {"food_control_programme": "np3", "liquor_licence_types": ["on"]}},
        )
        assert saved.ok, saved.text()
        page.goto("/compliant/nz-alcohol")
        readiness = page.get_by_role("region", name="Evidence readiness", exact=True)
        obligations = page.get_by_role("region", name="Your obligations", exact=True)
        manage = page.get_by_role("region", name="Compliance workspace actions", exact=True)
        cards = obligations.get_by_role("article")
        expect(cards.first).to_be_visible()
        outer = obligations.bounding_box()
        for card in cards.all():
            box = card.bounding_box()
            assert outer["x"] < box["x"] and box["x"] + box["width"] < outer["x"] + outer["width"]
        boxes = [item.bounding_box() for item in [readiness, obligations, manage]]
        assert [box["y"] for box in boxes] == sorted(box["y"] for box in boxes)
        assert len({round(box["width"]) for box in boxes}) == 1, "every block spans the content column"
        links = [link.bounding_box() for link in manage.get_by_role("link").all()]
        assert len(links) >= 2 and links[0]["y"] == links[1]["y"]
        assert len({round(link["width"]) for link in links}) == 1
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth + 1")
        _capture(page, "compliance-layout", width)
    finally:
        context.close()


@pytest.mark.parametrize("width", [390, 1024, 1440])
def test_sales_overview_groups_figures_and_tools_in_cards(browser, app_url, workspace_user, width):
    context, page = _page(browser, app_url, workspace_user, width)
    try:
        page.goto("/crm")
        glance = page.get_by_role("region", name="At a glance", exact=True)
        tools = page.get_by_role("region", name="Sales workspace actions", exact=True)
        expect(glance.get_by_role("button").first).to_be_visible()
        outer = glance.bounding_box()
        for figure in glance.get_by_role("button").all():
            if figure.is_visible():
                box = figure.bounding_box()
                assert outer["x"] < box["x"] and box["x"] + box["width"] < outer["x"] + outer["width"]
        assert glance.bounding_box()["y"] < tools.bounding_box()["y"]
        assert round(glance.bounding_box()["width"]) == round(tools.bounding_box()["width"])
        links = [link.bounding_box() for link in tools.get_by_role("link").all()]
        assert len(links) == 2 and links[0]["y"] == links[1]["y"]
        assert round(links[0]["width"]) == round(links[1]["width"])
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth + 1")
        _capture(page, "sales-layout", width)
    finally:
        context.close()


@pytest.mark.parametrize("width", [390, 1024, 1440])
def test_dashboard_leads_with_attention_and_health_then_the_week(browser, app_url, workspace_user, width):
    context, page = _page(browser, app_url, workspace_user, width)
    try:
        page.goto("/core/dashboard")
        expect(page.locator(".dash-footer-note[data-dashboard-loading]")).to_be_hidden()
        names = ["Needs attention", "Today's planned production", "This week", "Workspaces", "Recent activity"]
        regions = {name: page.get_by_role("region", name=name, exact=True) for name in names}
        boxes = {name: region.bounding_box() for name, region in regions.items()}
        assert [boxes[name]["y"] for name in names] == sorted(boxes[name]["y"] for name in names)
        # Attention and the day's plan share the left column beside Production health; the
        # blocks under them span the content column.
        top = {round(boxes[name]["width"]) for name in names[:2]}
        full = {round(boxes[name]["width"]) for name in names[2:]}
        assert len(top) == 1 and len(full) == 1, (top, full)
        health = page.get_by_role("region", name="Production health", exact=True)
        expect(health).to_be_visible()
        if width >= 1024:
            assert health.bounding_box()["x"] > boxes["Needs attention"]["x"] + boxes["Needs attention"]["width"]
        else:
            assert top == full, "one column on a narrow screen"
        for name, tiles in [("Workspaces", "a, article"), ("This week", "a.dash-figure")]:
            outer = boxes[name]
            visible = [tile.bounding_box() for tile in regions[name].locator(tiles).all() if tile.is_visible()]
            assert len(visible) >= 3
            for box in visible:
                assert outer["x"] < box["x"] and box["x"] + box["width"] < outer["x"] + outer["width"]
        expect(regions["This week"].locator("[data-kpi-active-batches]")).to_have_text("1")
        for hidden in page.locator(".dash-figure__meta[hidden], .dash-figure__spark[hidden]").all():
            expect(hidden).not_to_be_visible()
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth + 1")
        _capture(page, "dashboard-layout", width)
        page.evaluate("localStorage.setItem('spa-theme', 'dark')")
        page.goto("/core/dashboard")
        expect(page.locator(".dash-footer-note[data-dashboard-loading]")).to_be_hidden()
        _capture(page, "dashboard-layout-dark", width)
    finally:
        context.close()


@pytest.mark.parametrize("width", [390, 1024, 1440])
def test_settings_groups_account_security_and_organisation_in_cards(browser, app_url, workspace_user, width):
    context, page = _page(browser, app_url, workspace_user, width)
    try:
        page.goto("/core/settings")
        expect(page.get_by_role("heading", name="Settings", exact=True)).to_be_visible()
        sites = page.get_by_role("region", name="Manage sites", exact=True)
        people = page.get_by_role("region", name="People and roles", exact=True)
        expect(sites.get_by_role("link", name="View sites", exact=True)).to_have_attribute("href", "/core/sites")
        expect(people.get_by_role("link", name="Manage people", exact=True)).to_have_attribute("href", "/core/people")
        side_by_side = sites.bounding_box()["y"] == people.bounding_box()["y"]
        assert side_by_side == (width >= 1024)
        headings = page.locator(".settings-overview .workspace-card h2").all_inner_texts()
        expected = ["Account information", "Manage sites", "People and roles", "Security"]
        expected += ["Two-factor authentication", "Session settings"]
        assert [heading for heading in headings if heading in expected] == expected
        assert headings[-2:] == ["Notification preferences", "Appearance"]
        lefts = {round(card.bounding_box()["x"]) for card in page.locator(".settings-overview .workspace-card").all()}
        assert len(lefts) == (2 if side_by_side else 1)
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth + 1")
        _capture(page, "settings-layout", width)
        page.evaluate("localStorage.setItem('spa-theme', 'dark')")
        page.goto("/core/settings")
        expect(sites).to_be_visible()
        _capture(page, "settings-layout-dark", width)
        page.evaluate("localStorage.removeItem('spa-theme')")
    finally:
        context.close()


@pytest.fixture
def sales_history(workspace_user, db):
    """Fourteen customers with sales across four months, one with only a task, one with nothing."""
    org_id = UUID(workspace_user["org_id"])
    today = date.today()
    for index in range(14):
        contact = XeroContact(
            org_id=org_id,
            xero_contact_id=f"e2e-contact-{uuid4()}",
            xero_tenant_id="e2e-tenant",
            name=f"Customer {index + 1:02d} with a long trading name Limited",
            email_address=None if index == 0 else f"customer{index}@example.test",
        )
        db.add(contact)
        db.flush()
        for age in (index * 9 + 2, index * 9 + 40):
            db.add(
                XeroInvoice(
                    org_id=org_id,
                    xero_invoice_id=f"e2e-invoice-{uuid4()}",
                    xero_tenant_id="e2e-tenant",
                    contact_id=contact.id,
                    invoice_type="ACCREC",
                    status="AUTHORISED",
                    date=today - timedelta(days=age),
                    total=1000 * (14 - index),
                )
            )
    task_only = XeroContact(
        org_id=org_id, xero_contact_id=f"e2e-contact-{uuid4()}", xero_tenant_id="e2e-tenant", name="Task only"
    )
    silent = XeroContact(
        org_id=org_id, xero_contact_id=f"e2e-contact-{uuid4()}", xero_tenant_id="e2e-tenant", name="Never contacted"
    )
    db.add_all([task_only, silent])
    db.flush()
    db.add(CRMTask(org_id=org_id, contact_id=task_only.id, title="Call about the spring order", status="pending"))
    db.commit()
    return workspace_user


@pytest.mark.parametrize("width", [390, 1024, 1440])
def test_sales_analytics_shows_ranked_customers_contact_groups_and_recall(browser, app_url, sales_history, width):
    context, page = _page(browser, app_url, sales_history, width)
    try:
        page.goto("/crm/analytics")
        top = page.get_by_role("region", name="Top customers", exact=True)
        churn = page.get_by_role("region", name="Churn risk", exact=True)
        contact = page.get_by_role("region", name="Customer contact", exact=True)
        for region, total in [(top, 14), (churn, 14), (contact, 16)]:
            expect(region.locator("tbody tr")).to_have_count(10)
            more = region.get_by_role("button", name=f"Show all {total}", exact=True)
            expect(more).to_have_attribute("aria-expanded", "false")
            more.click()
            expect(region.locator("tbody tr")).to_have_count(total)
            region.get_by_role("button", name=re.compile(r"^Show (top|first) 10$")).click()
            expect(region.locator("tbody tr")).to_have_count(10)
        expect(top.locator("tbody tr").first).to_contain_text("Customer 01")
        expect(top.locator("tbody tr").first).to_contain_text("$28,000")
        expect(churn.locator("tbody tr").first).to_contain_text("high")
        expect(contact.locator("tbody tr").first).to_contain_text("Never contacted")
        expect(contact.locator("tbody tr").first).to_contain_text("No contact recorded")

        groups = contact.get_by_role("group", name="Customers by last contact")
        counts = [int(text) for text in groups.locator("strong").all_inner_texts()]
        assert sum(counts) == 16 and counts[3] == 1
        groups.get_by_role("button", name=re.compile("No contact recorded")).click()
        expect(contact.locator("tbody tr")).to_have_count(1)
        groups.get_by_role("button", name=re.compile("Recent contact")).click()
        expect(contact.locator("tbody tr").filter(has_text="Task only")).to_have_count(1)
        groups.get_by_role("button", name=re.compile("Recent contact")).click()
        expect(contact.locator("tbody tr")).to_have_count(10)

        recall = page.get_by_role("region", name="Recall contact details", exact=True)
        expect(recall).to_contain_text("customers are missing a phone number or email")
        expect(page.get_by_role("region", name="Monthly sales", exact=True).locator("canvas")).to_be_visible()
        side_by_side = top.bounding_box()["y"] == churn.bounding_box()["y"]
        assert side_by_side == (width >= 1440), "the pair stacks until each table has a wide column"
        for region in (top, churn, contact):
            outer = region.bounding_box()
            table = region.locator("table").bounding_box()
            assert table["x"] >= outer["x"] and table["x"] + table["width"] <= outer["x"] + outer["width"] + 1
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth + 1")
        _capture(page, "sales-analytics", width)

        page.goto("/crm")
        expect(page.get_by_role("region", name="At a glance", exact=True)).to_be_visible()
        expect(page.get_by_text("Recall contact details")).to_have_count(0)
    finally:
        context.close()
