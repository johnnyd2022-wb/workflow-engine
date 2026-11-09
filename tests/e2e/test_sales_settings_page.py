"""Sales settings in a browser: one load, a Save per section that saves only that section, a failed
load that hides the settings, the overview's "Map" link, and the page's fit.

Requests are routed into the Flask test client (see test_crm_contact_sync_ui), and Xero is faked.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from playwright.sync_api import expect

from tests.e2e.test_crm_contact_sync_ui import client, sales_page, xero  # noqa: F401 -- fixture re-export
from tests.test_crm import db, org, user  # noqa: F401 -- fixture re-export

pytestmark = pytest.mark.e2e

PAGE = "https://crm.test/crm/configuration"
READY = ".sales-settings[aria-busy='false']"


def _open(page, width=1440, query=""):
    page.set_viewport_size({"width": width, "height": 900})
    page.goto(f"{PAGE}?{query.lstrip('&')}")
    page.locator(READY).wait_for()


def test_the_settings_load_once(xero, sales_page):  # noqa: F811
    # x-init="init()" on top of Alpine's own init() call loaded every setting twice.
    calls = []
    sales_page.on("request", lambda r: calls.append(r.url) if r.url.endswith("/traceability-config") else None)
    _open(sales_page)
    sales_page.wait_for_load_state("networkidle")
    assert len(calls) == 1, calls


def test_a_section_saves_only_itself(xero, sales_page, client):  # noqa: F811
    # All three Save buttons sent the whole form, so saving Tasks also saved a half-typed target.
    _open(sales_page)
    sales_page.locator("#ss-revenue-target").fill("42000")
    sales_page.locator("#ss-archive-days").fill("14")
    sales_page.locator("#tasks").get_by_role("button", name="Save").click()
    expect(sales_page.locator("#tasks .ss-saved")).to_have_text("Saved.")
    saved = client.get("/api/crm/traceability-config").get_json()
    assert saved["task_done_archive_days"] == 14
    assert saved["revenue_baseline_target_mtd"] is None
    # The unsaved target is still in its box, waiting for its own Save.
    expect(sales_page.locator("#ss-revenue-target")).to_have_value("42000")


def test_settings_that_did_not_load_cannot_be_saved_over(xero, sales_page):  # noqa: F811
    # The page used to show the defaults after a failed load, and saving them overwrote the real ones.
    sales_page.route(
        "**/api/crm/traceability-config",
        lambda route: route.fulfill(status=503, json={"error": "Sales settings could not load."}),
    )
    _open(sales_page)
    expect(sales_page.get_by_role("alert")).to_contain_text("Sales settings could not load.")
    expect(sales_page.locator("#matching")).to_be_hidden()
    sales_page.unroute("**/api/crm/traceability-config")
    sales_page.get_by_role("button", name="Try again").click()
    expect(sales_page.locator("#matching")).to_be_visible()


def test_the_overview_map_link_opens_the_form_for_that_line(xero, sales_page):  # noqa: F811
    _open(sales_page, query="&map=Wildflower%20Gin%20700ml")
    dialog = sales_page.get_by_role("dialog", name="Add a mapping")
    expect(dialog).to_be_visible()
    expect(dialog.locator("#ss-mapping-line")).to_have_value("Wildflower Gin 700ml")
    sales_page.keyboard.press("Escape")
    expect(dialog).to_be_hidden()


@pytest.mark.parametrize("width", [390, 1440, 1920], ids=["phone", "laptop", "wall"])
def test_the_page_fits_without_sideways_scroll(xero, sales_page, width):  # noqa: F811
    _open(sales_page, width=width)
    assert sales_page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    for section in ("#xero", "#mappings", "#matching", "#customers", "#revenue", "#tasks"):
        expect(sales_page.locator(section)).to_be_visible()


def test_phone_guidance_keeps_the_full_explanation_available(xero, sales_page):  # noqa: F811
    _open(sales_page, width=390)
    for section_id, summary, detail in (
        ("#matching", "When does this take effect?", "including sales already imported"),
        ("#customers", "How does this work?", "Each customer can override"),
    ):
        section = sales_page.locator(section_id)
        expect(section.locator(".ss-intro__desktop")).to_be_hidden()
        expect(section.locator(".ss-intro__mobile > p")).to_be_visible()
        explanation = section.locator(".ss-intro__mobile details")
        expect(explanation.locator("p")).to_be_hidden()
        explanation.get_by_text(summary).click()
        expect(explanation.locator("p")).to_contain_text(detail)
        explanation.get_by_text(summary).click()
    if folder := os.environ.get("CRM_SHOTS_DIR"):
        Path(folder).mkdir(parents=True, exist_ok=True)
        sales_page.screenshot(path=str(Path(folder) / "sales-settings-phone.png"), full_page=True)
    sales_page.set_viewport_size({"width": 1440, "height": 900})
    for section_id in ("#matching", "#customers"):
        section = sales_page.locator(section_id)
        expect(section.locator(".ss-intro__desktop")).to_be_visible()
        expect(section.locator(".ss-intro__mobile")).to_be_hidden()
    if folder := os.environ.get("CRM_SHOTS_DIR"):
        sales_page.screenshot(path=str(Path(folder) / "sales-settings-desktop.png"), full_page=True)


@pytest.fixture()
def without_stock_access(db, user):  # noqa: F811
    """The signed-in person configures sales (sales.manage) but cannot adjust stock."""
    from app.core.db.models.org_role import OrgRole
    from app.core.db.models.user import User, UserRole

    role = OrgRole(
        org_id=user.org_id,
        name="Sales manager (no stock)",
        base_role="sales",
        permissions=["sales.view", "sales.record", "sales.manage", "inventory.view"],
        site_access_mode="all",
    )
    db.add(role)
    db.flush()
    was = user.role
    user.role, user.custom_role_id = UserRole.SALES, role.id  # what assigning "custom:<id>" stores
    db.commit()
    role_id = role.id
    yield
    db.rollback()
    db.query(User).filter(User.custom_role_id == role_id).update(
        {User.role: was, User.custom_role_id: None}, synchronize_session=False
    )
    db.query(OrgRole).filter(OrgRole.id == role_id).delete(synchronize_session=False)
    db.commit()


def test_no_stock_access_locks_the_matching_mode(without_stock_access, xero, sales_page, client):  # noqa: F811
    # The rest of the section still saves.
    # SALES-PERM: switching the mode makes waiting sales take stock, so it needs inventory.adjust.
    _open(sales_page)
    matching = sales_page.locator("#matching")
    expect(matching.get_by_test_id("matching-mode-locked")).to_be_visible()
    for radio in matching.locator("input[name='matching_mode']").all():
        expect(radio).to_be_disabled()
    matching.get_by_text("Xero line must match exactly").click()
    matching.get_by_role("button", name="Save").click()
    expect(sales_page.locator("#matching .ss-saved")).to_have_text("Saved.")
    assert client.get("/api/crm/traceability-config").get_json()["strict_mapping"] is False


def test_with_stock_access_the_matching_mode_is_not_locked(xero, sales_page):  # noqa: F811
    _open(sales_page)
    matching = sales_page.locator("#matching")
    expect(matching.get_by_test_id("matching-mode-locked")).to_have_count(0)
    expect(matching.locator("input[value='manual']")).to_be_enabled()
