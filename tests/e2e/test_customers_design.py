"""The chosen customer directory preserves behavior, contact access and responsive layout."""

import re
from urllib.parse import parse_qs, urlsplit

import pytest
from playwright.sync_api import expect

from app.features.crm.models.xero_contact import XeroContact
from tests.e2e import test_crm_contact_sync_ui as fixtures
from tests.test_crm_contact_sync import _xero_contact

db = fixtures.db
org = fixtures.org
user = fixtures.user
client = fixtures.client
sales_page = fixtures.sales_page
xero = fixtures.xero
pytestmark = pytest.mark.e2e


@pytest.fixture
def contacts(db, org):
    complete = _xero_contact(db, org.id, name="Beacon Bottle Shop", contact_status="ACTIVE")
    missing = XeroContact(org_id=org.id, name="Aro Valley Wine Bar", source="bize", contact_status="ARCHIVED")
    db.add(missing)
    db.commit()
    return complete, missing


def _open(page, query=""):
    page.goto("https://crm.test/crm/customers" + query)
    expect(page.locator(".customers-results")).to_contain_text("2 customers")


def test_filters_order_and_clear_use_the_server_query(sales_page, contacts, xero):
    page = sales_page
    _open(page)
    links = page.locator("tbody .customers-name")
    expect(links).to_have_text(["Aro Valley Wine Bar", "Beacon Bottle Shop"])
    page.get_by_role("button", name="Sort", exact=True).click()
    page.get_by_label("Order by", exact=True).select_option("name:desc")
    expect(links).to_have_text(["Beacon Bottle Shop", "Aro Valley Wine Bar"])
    page.get_by_role("searchbox", name="Search customers").fill("Beacon")
    expect(links).to_have_text(["Beacon Bottle Shop"])
    page.get_by_role("button", name="Clear filters", exact=True).click()
    page.get_by_label("Customer status", exact=True).select_option("ARCHIVED")
    expect(links).to_have_text(["Aro Valley Wine Bar"])
    page.get_by_role("button", name="Clear filters", exact=True).click()
    page.get_by_role("button", name="Missing contact details", exact=True).click()
    expect(links).to_have_text(["Aro Valley Wine Bar"])
    page.get_by_role("searchbox", name="Search customers").fill("nobody")
    expect(page.get_by_role("heading", name="No customers match these filters")).to_be_visible()
    page.get_by_role("button", name="Show all customers", exact=True).click()
    expect(links).to_have_text(["Beacon Bottle Shop", "Aro Valley Wine Bar"])
    expect(page.get_by_label("Customer status", exact=True)).to_have_value("")
    expect(page.get_by_role("button", name="Missing contact details", exact=True)).to_have_attribute(
        "aria-pressed", "false"
    )


def test_customer_links_and_preview_work_with_keyboard(sales_page, contacts, xero):
    page = sales_page
    complete, _ = contacts
    _open(page)
    button = page.get_by_role("button", name="Preview Beacon Bottle Shop", exact=True)
    button.focus()
    button.press("Enter")
    dialog = page.get_by_role("dialog", name="Beacon Bottle Shop", exact=True)
    expect(dialog).to_be_visible()
    expect(dialog.get_by_role("link", name="orders@harbour.example")).to_have_attribute(
        "href", "mailto:orders@harbour.example"
    )
    expect(dialog.get_by_role("link", name="04 555 0100")).to_have_attribute("href", "tel:04 555 0100")
    close = dialog.get_by_role("button", name="Close customer preview")
    expect(close).to_be_focused()
    close.press("Shift+Tab")
    expect(dialog.get_by_role("link", name="Open customer")).to_be_focused()
    page.keyboard.press("Escape")
    expect(dialog).to_be_hidden()
    expect(button).to_be_focused()
    link = page.get_by_role("link", name="Beacon Bottle Shop", exact=True)
    expect(link).to_have_attribute("href", f"/crm/customers/{complete.id}")
    link.focus()
    link.press("Enter")
    expect(page).to_have_url(re.compile(rf"/crm/customers/{complete.id}$"))
    expect(page.locator("[data-contact-details]")).to_be_visible()


def test_failure_is_not_an_empty_directory_and_retry_restores_rows(sales_page, contacts, xero):
    page = sales_page

    def unavailable(route):
        route.fulfill(status=503, json={"error": "Directory temporarily unavailable"})

    page.route("**/api/crm/customers?*", unavailable)
    page.goto("https://crm.test/crm/customers")
    expect(page.get_by_role("alert")).to_contain_text("Directory temporarily unavailable")
    expect(page.get_by_role("heading", name="Your customer directory starts here")).to_be_hidden()
    page.unroute("**/api/crm/customers?*", unavailable)
    page.get_by_role("button", name="Try again", exact=True).click()
    expect(page.locator("tbody .customers-name")).to_have_text(["Aro Valley Wine Bar", "Beacon Bottle Shop"])
    expect(page.get_by_role("alert")).to_be_hidden()


def test_pagination_keeps_filters_and_shows_the_requested_page(sales_page, contacts, xero):
    page = sales_page
    requests = []

    def pages(route):
        query = parse_qs(urlsplit(route.request.url).query)
        requests.append(query)
        number = int(query["page"][0])
        route.fulfill(
            json={
                "customers": [
                    {
                        "id": str(number),
                        "name": f"Customer page {number}",
                        "email_address": "a@example.test",
                        "phone_number": "021 555 0100",
                    }
                ],
                "total": 51,
                "total_pages": 2,
                "page": number,
            }
        )

    page.route("**/api/crm/customers?*", pages)
    page.goto("https://crm.test/crm/customers?missing_contact=1")
    expect(page.locator("tbody .customers-name")).to_have_text(["Customer page 1"])
    page.get_by_role("button", name="Next →", exact=True).click()
    expect(page.locator("tbody .customers-name")).to_have_text(["Customer page 2"])
    assert requests[-1]["page"] == ["2"]
    assert requests[-1]["missing_contact"] == ["1"]
    expect(page.get_by_role("button", name="Next →", exact=True)).to_be_disabled()
    expect(page.locator(".customers-pagination")).to_contain_text("51–51 of 51")
    page.get_by_role("button", name="← Prev", exact=True).click()
    expect(page.locator("tbody .customers-name")).to_have_text(["Customer page 1"])
    expect(page.get_by_role("button", name="← Prev", exact=True)).to_be_disabled()


@pytest.mark.parametrize("width", [390, 1024, 1440, 1920])
def test_directory_and_drawer_work_at_every_width_despite_old_preview_choices(sales_page, contacts, xero, width):
    page = sales_page
    page.set_viewport_size({"width": width, "height": 900})
    page.goto("https://crm.test/crm/customers")
    page.evaluate("sessionStorage.setItem('customers-design-style', '3')")
    _open(page, "?style=2")
    expect(page.get_by_role("group", name="Customer design options")).to_have_count(0)
    expect(page.locator("tbody .customers-name")).to_have_text(["Aro Valley Wine Bar", "Beacon Bottle Shop"])
    expect(page.locator(".customers-contact").first).to_be_visible()
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1")
    assert page.locator("#page-content").evaluate("main => main.scrollWidth <= main.clientWidth + 1")
    records = page.locator("tbody tr:visible")
    boxes = [record.bounding_box() for record in records.all()]
    for i, left in enumerate(boxes):
        for right in boxes[i + 1 :]:
            assert (
                left["x"] + left["width"] <= right["x"] + 1
                or right["x"] + right["width"] <= left["x"] + 1
                or left["y"] + left["height"] <= right["y"] + 1
                or right["y"] + right["height"] <= left["y"] + 1
            )
    page.get_by_role("button", name="Preview Beacon Bottle Shop", exact=True).click()
    preview = page.get_by_role("dialog", name="Beacon Bottle Shop", exact=True)
    expect(preview.get_by_role("link", name="orders@harbour.example")).to_be_visible()
    expect(preview.get_by_role("link", name="Open customer")).to_be_visible()
    page.get_by_role("button", name="Close customer preview").click()
    expect(preview).to_be_hidden()
    expect(page.locator(".customers-contact").first).to_be_visible()
    page.evaluate("document.documentElement.setAttribute('data-spa-theme', 'dark')")
    page.wait_for_timeout(300)
    if width >= 700:
        colors = page.locator(".customers-table th").first.evaluate(
            "el => ({fg:getComputedStyle(el).color,bg:getComputedStyle(el).backgroundColor})"
        )

        def luminance(value):
            channels = [int(channel) / 255 for channel in re.findall(r"\d+", value)[:3]]
            channels = [
                channel / 12.92 if channel <= 0.04045 else ((channel + 0.055) / 1.055) ** 2.4 for channel in channels
            ]
            return sum(channel * weight for channel, weight in zip(channels, [0.2126, 0.7152, 0.0722]))

        light, dark = sorted([luminance(colors["fg"]), luminance(colors["bg"])], reverse=True)
        assert (light + 0.05) / (dark + 0.05) >= 4.5, colors


def test_directory_search_survives_a_boosted_round_trip(sales_page, contacts, xero):
    page = sales_page
    _open(page)
    tabs = page.get_by_role("navigation", name="Sales sections", exact=True)
    tabs.get_by_role("tab", name="Analytics", exact=True).click()
    expect(page).to_have_url(re.compile(r"/crm/analytics$"))
    tabs.get_by_role("tab", name="Customers", exact=True).click()
    page.wait_for_load_state("networkidle")
    expect(page.locator("tbody .customers-name")).to_have_text(["Aro Valley Wine Bar", "Beacon Bottle Shop"])
    page.get_by_role("searchbox", name="Search customers").fill("Beacon")
    expect(page.get_by_role("link", name="Beacon Bottle Shop", exact=True)).to_be_visible()
    expect(page.locator(".customers-results")).to_contain_text("1 customer match")
