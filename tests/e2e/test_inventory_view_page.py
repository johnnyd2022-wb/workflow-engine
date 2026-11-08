"""The Inventory page (/core/inventory/view): the stock table loads on every visit, filters
narrow it, and a line opens in the side panel with its details, history and edit form."""

import re
from datetime import date, timedelta
from uuid import UUID

import pytest
from playwright.sync_api import expect

from app.core.db.models.user import UserRole
from tests.e2e.conftest import assert_clean_page, attach_probe, login_through_ui
from tests.factories import InventoryItemFactory

pytestmark = pytest.mark.e2e


@pytest.fixture
def stocked_page(browser, app_url, fresh_user, db):
    """An admin's page on an org holding four lines: two raw lots of one product (one expired,
    one with no batch number), one more raw line, and one finished product."""
    user = fresh_user(UserRole.ADMIN)
    org_id = UUID(user["org_id"])
    today = date.today()
    InventoryItemFactory(
        org_id=org_id,
        name="Juniper berries",
        quantity="18.5",
        supplier="Davis Trading",
        supplier_batch_number="JB-2291",
        expiry_date=today + timedelta(days=300),
    )
    InventoryItemFactory(
        org_id=org_id,
        name="Juniper berries",
        quantity="4",
        supplier="Davis Trading",
        expiry_date=today - timedelta(days=6),
    )
    InventoryItemFactory(
        org_id=org_id,
        name="Coriander seed",
        quantity="9",
        supplier="Moore Wilson",
        supplier_batch_number="CS-0931",
        expiry_date=today + timedelta(days=12),
    )
    InventoryItemFactory(
        org_id=org_id, name="Dry Gin 700 mL", quantity="48", unit="units", inventory_type="final_product"
    )
    db.commit()

    context = browser.new_context(base_url=app_url, ignore_https_errors=True, viewport={"width": 1440, "height": 900})
    page = context.new_page()
    attach_probe(page)
    login_through_ui(page, user["email"], user["password"])
    try:
        yield page
    finally:
        context.close()


def _rows(page):
    return page.locator("#inv-view-tbody tr")


def test_stock_loads_again_after_leaving_and_returning_by_boosted_links(stocked_page):
    """[REGRESSION] The page's script ran once per browser session, so a second boosted visit
    swapped in a fresh, empty page that stayed on "Loading" until a full refresh."""
    page = stocked_page
    page.goto("/core/inventory/view")
    expect(_rows(page)).to_have_count(4)

    for _ in range(2):
        page.get_by_role("link", name="Live inventory", exact=True).click()
        expect(page.locator(".workspace-header h1")).to_have_text("Live inventory")
        page.get_by_role("link", name="Back to inventory", exact=True).click()
        expect(page.locator(".workspace-header h1")).to_have_text("Inventory")
        expect(_rows(page)).to_have_count(4)
        expect(page.locator("#inv-view-count")).to_have_text("4 lines on hand")
    assert_clean_page(page)


def test_search_and_filters_narrow_the_table_and_clear_restores_it(stocked_page):
    """[REGRESSION] Typing in Search threw a ReferenceError and left the table unfiltered."""
    page = stocked_page
    page.goto("/core/inventory/view")
    expect(_rows(page)).to_have_count(4)

    page.get_by_role("searchbox", name="Search inventory").fill("coriander")
    expect(_rows(page)).to_have_count(1)
    expect(page.get_by_role("row", name=re.compile("Coriander seed"))).to_be_visible()
    expect(page.locator("#inv-view-count")).to_have_text("1 of 4 lines")

    page.get_by_role("button", name="Clear filters").click()
    expect(_rows(page)).to_have_count(4)

    page.get_by_label("Supplier").select_option("Davis Trading")
    expect(_rows(page)).to_have_count(2)
    page.get_by_role("button", name=re.compile("^Final")).click()
    expect(_rows(page)).to_have_count(0)
    expect(page.get_by_text("No stock matches these filters")).to_be_visible()
    page.get_by_role("button", name="Remove filter: Supplier: Davis Trading").click()
    expect(page.get_by_role("row", name=re.compile("Dry Gin 700 mL"))).to_be_visible()
    expect(_rows(page)).to_have_count(1)
    assert_clean_page(page)


def test_status_tiles_count_and_filter_the_lines_that_need_attention(stocked_page):
    page = stocked_page
    page.goto("/core/inventory/view")
    glance = page.get_by_role("region", name="At a glance")
    expect(glance.get_by_role("button", name="4 Lines on hand")).to_have_attribute("aria-pressed", "true")
    expect(glance.get_by_role("button", name="1 Expiring in 30 days")).to_be_visible()
    expect(glance.get_by_role("button", name="1 Raw, no batch number")).to_be_visible()

    glance.get_by_role("button", name="1 Expired").click()
    expect(_rows(page)).to_have_count(1)
    row = _rows(page).first
    expect(row).to_contain_text("Juniper berries")
    expect(row).to_contain_text("Expired 6 days ago")
    # The filter is in the address, so a refresh or a shared link keeps it.
    expect(page).to_have_url(re.compile(r"[?&]status=expired"))
    page.reload()
    expect(_rows(page)).to_have_count(1)
    expect(page.get_by_role("region", name="At a glance").get_by_role("button", name="1 Expired")).to_have_attribute(
        "aria-pressed", "true"
    )
    assert_clean_page(page)


def test_grouping_lots_shows_one_row_per_product_with_its_total(stocked_page):
    page = stocked_page
    page.goto("/core/inventory/view")
    expect(_rows(page)).to_have_count(4)

    page.get_by_role("button", name="Group lots").click()
    expect(_rows(page)).to_have_count(3)
    group = page.get_by_role("row", name=re.compile("Juniper berries"))
    expect(group).to_contain_text("2 lots")
    expect(group).to_contain_text("22.5")

    group.get_by_role("button", name="Juniper berries").click()
    expect(_rows(page)).to_have_count(5)
    expect(page.get_by_role("row", name=re.compile("Batch JB-2291"))).to_be_visible()
    assert_clean_page(page)


def test_a_line_opens_in_the_side_panel_and_escape_returns_to_the_table(stocked_page):
    page = stocked_page
    page.goto("/core/inventory/view")
    opener = page.get_by_role("row", name=re.compile("Coriander seed")).get_by_role("button", name="Coriander seed")
    opener.click()

    panel = page.get_by_role("dialog", name="Coriander seed")
    expect(panel).to_be_visible()
    expect(panel).to_contain_text("Moore Wilson")
    expect(panel).to_contain_text("CS-0931")
    expect(panel).to_contain_text("12 days left")
    expect(panel.locator(".inv-audit-timeline__item")).to_have_count(1)
    expect(page).to_have_url(re.compile(r"[?&]item="))

    page.keyboard.press("Escape")
    expect(panel).to_be_hidden()
    expect(opener).to_be_focused()
    expect(page).not_to_have_url(re.compile(r"[?&]item="))
    assert_clean_page(page)


def test_saving_an_edit_from_the_panel_updates_the_row_without_a_refresh(stocked_page):
    """[REGRESSION] The after-save hook called a function it could not see, so the table kept
    showing the old quantity until the page was reloaded."""
    page = stocked_page
    page.goto("/core/inventory/view")
    row = page.get_by_role("row", name=re.compile("Coriander seed"))
    row.get_by_role("button", name="Coriander seed").click()
    page.get_by_role("dialog", name="Coriander seed").get_by_role("button", name="Edit this line").click()

    sheet = page.get_by_role("dialog", name="Edit item")
    sheet.get_by_label("Quantity").fill("6.5")
    sheet.get_by_role("button", name="Save changes").click()

    expect(row.locator(".inv-qty")).to_have_text("6.5")
    panel = page.get_by_role("dialog", name="Coriander seed")
    expect(panel.locator(".inv-drawer__qty")).to_contain_text("6.5")
    expect(panel.locator(".inv-audit-timeline__item")).to_have_count(2)
    assert_clean_page(page)


def test_the_table_becomes_a_list_on_a_phone_without_sideways_scrolling(stocked_page):
    page = stocked_page
    page.set_viewport_size({"width": 390, "height": 844})
    page.goto("/core/inventory/view")
    expect(_rows(page)).to_have_count(4)
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth + 1")

    _rows(page).first.get_by_role("button").click()
    panel = page.get_by_role("dialog", name="Coriander seed")
    expect(panel).to_be_visible()
    panel.evaluate("el => Promise.all(el.getAnimations().map(a => a.finished))")
    box = panel.bounding_box()
    assert box["x"] == 0 and round(box["width"]) == 390
    assert_clean_page(page)
