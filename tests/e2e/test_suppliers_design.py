"""The Suppliers page's redesign (docs/suppliers-redesign-plan.md): what you buy from each
supplier, the gaps in their details, their details one click away, and the two bugs the old page
had (unreadable in the dark theme, a search box sized by the shared input rules)."""

from uuid import UUID

import pytest
from playwright.sync_api import expect

from app.core.db.models.supplier import Supplier
from app.core.db.models.user import UserRole
from tests.e2e.conftest import login_through_ui
from tests.factories import InventoryItemFactory

pytestmark = pytest.mark.e2e

# Contrast of the text against what is drawn behind it, walking up to the first painted background.
_CONTRAST_JS = """(node) => {
  const rgb = (value) => (value.match(/[\\d.]+/g) || []).map(Number);
  const lum = ([r, g, b]) => {
    const f = (c) => { c /= 255; return c <= 0.03928 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4); };
    return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b);
  };
  let el = node, bg = null;
  while (el) {
    const parts = rgb(getComputedStyle(el).backgroundColor);
    if (parts.length === 3 || (parts.length === 4 && parts[3] > 0.5)) { bg = parts.slice(0, 3); break; }
    el = el.parentElement;
  }
  const fg = rgb(getComputedStyle(node).color).slice(0, 3);
  const [hi, lo] = [lum(fg), lum(bg || [255, 255, 255])].sort((a, b) => b - a);
  return (hi + 0.05) / (lo + 0.05);
}"""


@pytest.fixture
def suppliers_page(browser, app_url, fresh_user, db):
    """Two suppliers with stock (one missing an address), one with nothing bought, and a name on
    stock that is not a supplier record yet."""
    user = fresh_user(UserRole.ADMIN)
    org_id = UUID(user["org_id"])
    db.add_all(
        [
            Supplier(
                org_id=org_id,
                name="Davis Trading",
                contact_name="Priya Shah",
                phone="04 384 2210",
                email="orders@davistrading.co.nz",
                address="12 Kingsford Smith St, Wellington",
            ),
            Supplier(org_id=org_id, name="Wairarapa Foragers", phone="027 455 0193", email="hemi@foragers.nz"),
            Supplier(org_id=org_id, name="Southern Hops", phone="03 545 1288", email="kate@hops.nz", address="Riwaka"),
        ]
    )
    db.commit()
    InventoryItemFactory(org_id=org_id, name="Juniper berries", quantity="18.5", supplier="Davis Trading")
    InventoryItemFactory(org_id=org_id, name="Coriander seed", quantity="9", supplier="Davis Trading")
    InventoryItemFactory(org_id=org_id, name="Kawakawa leaf", quantity="0.85", supplier="Wairarapa Foragers")
    InventoryItemFactory(org_id=org_id, name="Cork stopper", quantity="3400", unit="units", supplier="Corticeira")
    db.commit()
    context = browser.new_context(base_url=app_url, ignore_https_errors=True, viewport={"width": 1440, "height": 900})
    page = context.new_page()
    login_through_ui(page, user["email"], user["password"])
    yield page
    context.close()


def _open(page, query=""):
    page.goto("/core/suppliers" + query)
    expect(page.locator("[data-suppliers-page]")).to_have_attribute("aria-busy", "false")


def test_each_supplier_says_what_you_buy_and_search_finds_them_by_it(suppliers_page):
    page = suppliers_page
    _open(page)
    davis = page.locator(".sup-table__row", has_text="Davis Trading")
    expect(davis).to_contain_text("Coriander seed, Juniper berries")
    expect(davis).to_contain_text("2 lots in stock")
    expect(page.locator(".sup-table__row", has_text="Southern Hops")).to_contain_text("Nothing bought yet")

    page.get_by_role("searchbox", name="Search suppliers").fill("juniper")
    expect(page.locator(".sup-table__row")).to_have_count(1)
    expect(page.locator(".sup-table__row")).to_contain_text("Davis Trading")
    page.get_by_role("searchbox", name="Search suppliers").fill("nothing like this")
    page.get_by_role("button", name="Clear search and filters").click()
    expect(page.locator(".sup-table__row")).to_have_count(3)


def test_gaps_in_a_suppliers_details_are_named_and_filterable(suppliers_page):
    page = suppliers_page
    _open(page)
    expect(page.locator(".sup-table__row", has_text="Wairarapa Foragers")).to_contain_text("No address")
    expect(page.locator(".sup-table__row", has_text="Davis Trading").locator(".sup-tag")).to_have_count(0)
    page.locator(".sup-chip[data-suppliers-filter='incomplete']").click()
    expect(page.locator("[data-suppliers-heading]")).to_have_text("Need details")
    expect(page.locator(".sup-table__row")).to_have_count(1)
    page.locator(".sup-chip[data-suppliers-filter='buying']").click()
    expect(page.locator(".sup-table__row")).to_have_count(2)


def test_a_row_opens_the_details_with_ways_to_reach_them_and_an_edit_comes_back_to_them(suppliers_page):
    page = suppliers_page
    _open(page)
    page.locator(".sup-table__row", has_text="Davis Trading").click()
    drawer = page.locator("[data-supplier-drawer]")
    expect(drawer).to_be_visible()
    expect(drawer.get_by_role("link", name="Call")).to_have_attribute("href", "tel:043842210")
    expect(drawer.get_by_role("link", name="Email")).to_have_attribute("href", "mailto:orders@davistrading.co.nz")
    expect(drawer.locator(".sup-lots__item")).to_have_count(2)
    page.keyboard.press("Escape")
    expect(drawer).to_be_hidden()

    page.locator(".sup-table__row", has_text="Wairarapa Foragers").locator("[data-supplier-open]").click()
    drawer.locator("[data-supplier-edit]").click()
    sheet = page.locator("[data-supplier-sheet]")
    sheet.get_by_label("Address").fill("Greytown")
    sheet.get_by_role("button", name="Save changes").click()
    expect(drawer).to_be_visible()
    expect(drawer.locator(".sup-detail__saved")).to_have_text("Saved")
    expect(drawer).to_contain_text("Greytown")
    expect(page.locator(".sup-table__row", has_text="Wairarapa Foragers").locator(".sup-tag")).to_have_count(0)


def test_a_name_on_stock_but_not_listed_can_be_added_from_the_figures(suppliers_page):
    page = suppliers_page
    _open(page)
    tile = page.get_by_role("button", name="Import 1 supplier named on your stock")
    expect(tile).to_contain_text("Corticeira")
    tile.click()
    expect(page.locator("[data-suppliers-message]")).to_contain_text("Added 1 from inventory: Corticeira.")
    expect(page.locator(".sup-table__row", has_text="Corticeira")).to_contain_text("No contact details")


def test_a_failed_load_says_so_and_offers_to_try_again(suppliers_page):
    page = suppliers_page
    page.route("**/api/core/suppliers", lambda route: route.fulfill(status=500, json={"error": "Server error"}))
    _open(page)
    expect(page.get_by_role("button", name="Try again")).to_be_visible()
    page.unroute("**/api/core/suppliers")
    page.get_by_role("button", name="Try again").click()
    expect(page.locator(".sup-table__row")).to_have_count(3)


def test_the_register_stays_readable_in_the_dark_theme(suppliers_page):
    """Regression: the old page hard-coded #172033 text, which sat on the dark card at 1.2:1."""
    page = suppliers_page
    _open(page)
    page.evaluate("document.documentElement.setAttribute('data-spa-theme', 'dark')")
    cell = page.locator(".sup-table tbody td").first
    expect(cell).to_be_visible()
    assert cell.evaluate(_CONTRAST_JS) >= 4.5


def test_the_search_box_is_sized_like_the_controls_beside_it(suppliers_page):
    """Regression: base-spa.css sized the search input to 60px tall inside its own bordered box."""
    page = suppliers_page
    _open(page)
    box = page.locator(".sup-search").bounding_box()
    assert box["height"] <= 44, box


# The selected register stays usable at every width, including old preview links.
@pytest.mark.parametrize("width", [390, 1024, 1440, 1920])
def test_register_and_detail_drawer_work_at_every_width(suppliers_page, width):
    page = suppliers_page
    page.set_viewport_size({"width": width, "height": 1000})
    page.evaluate("sessionStorage.setItem('suppliers-design-style', '3')")
    _open(page, "?style=2")
    expect(page.get_by_role("group", name="Suppliers design concepts")).to_have_count(0)
    expect(page.get_by_role("heading", name="At a glance")).to_be_visible()
    expect(page.locator(".sup-table__row", has_text="Davis Trading")).to_be_visible()
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth + 1"), "scrolls sideways"
    page.locator("[data-supplier-open]", has_text="Southern Hops").click()
    expect(page.locator("[data-supplier-drawer]")).to_contain_text("Southern Hops")
    expect(page.get_by_role("link", name="Email", exact=True)).to_have_attribute("href", "mailto:kate@hops.nz")
    page.get_by_role("button", name="Close supplier details").click()
    expect(page.locator("[data-supplier-drawer]")).to_be_hidden()
