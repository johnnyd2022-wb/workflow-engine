"""The left sidebar collapses to a rail on laptop and desktop, on every page.

The sidebar is the shell's (`app/ui/templates/shared/sidebar-v2.html`), so this runs against two
pages. The rail must keep each tab's name, give the page its width back, move any bar pinned along
the sidebar's edge with it, and be remembered: a boosted visit swaps only `#page-content`, and a
full load must not flash open before collapsing.
"""

import pytest
from playwright.sync_api import expect

from tests.e2e.conftest import assert_clean_page, attach_probe

pytestmark = pytest.mark.e2e

OPEN, RAIL = 260, 80


def _width(page) -> float:
    return page.evaluate("document.getElementById('sidebar').getBoundingClientRect().width")


def _wait_for_width(page, width: int) -> None:
    page.wait_for_function(
        # Exactly: the glide's last frames are within a hair of the end, and the page beside it
        # is still moving until it lands.
        "w => document.getElementById('sidebar').getBoundingClientRect().width === w"
        " && document.querySelector('.main-content').getBoundingClientRect().left === w"
        " && !document.getElementById('sidebar').classList.contains('sidebar--switching')",
        arg=width,
    )


@pytest.fixture
def desktop_page(logged_in_page):
    page = logged_in_page
    attach_probe(page)
    page.set_viewport_size({"width": 1440, "height": 900})
    page.goto("/core/dashboard")
    page.evaluate("localStorage.removeItem('sidebarCollapsed')")
    page.reload()
    expect(page.locator("#sidebar")).to_be_visible()
    yield page
    page.evaluate("localStorage.removeItem('sidebarCollapsed')")


def test_the_sidebar_collapses_to_a_labelled_rail_and_gives_the_page_its_width(desktop_page):
    page = desktop_page
    sidebar = page.locator("#sidebar")
    toggle = page.get_by_role("button", name="Collapse menu")
    expect(toggle).to_have_attribute("aria-expanded", "true")
    assert _width(page) == OPEN
    content_before = page.locator(".main-content").bounding_box()
    icon_before = sidebar.get_by_role("link", name="Production", exact=True).locator("svg.nav-link-icon").bounding_box()

    toggle.click()
    _wait_for_width(page, RAIL)

    expect(page.get_by_role("button", name="Expand menu")).to_have_attribute("aria-expanded", "false")
    content = page.locator(".main-content").bounding_box()
    assert content["x"] == RAIL and content["width"] == content_before["width"] + (OPEN - RAIL)
    # A rail of bare icons makes people guess: every tab keeps its name, inside the rail.
    for name in ["Home", "Production", "Settings"]:
        link = sidebar.get_by_role("link", name=name, exact=True)
        expect(link).to_be_visible()
        label = link.locator(".nav-link-text")
        expect(label).to_be_visible()
        box = page.evaluate(
            "el => { const r = document.createRange(); r.selectNodeContents(el); const b = r.getBoundingClientRect(); return [b.left, b.right]; }",
            label.element_handle(),
        )
        assert box[0] >= 0 and box[1] <= RAIL, f"{name} is clipped by the rail: {box}"
    # Each icon stays in its column, so nothing is seen to jump sideways.
    icon = sidebar.get_by_role("link", name="Production", exact=True).locator("svg.nav-link-icon").bounding_box()
    assert abs(icon["x"] - icon_before["x"]) < 0.5
    expect(sidebar.get_by_role("button", name="Logout")).to_be_visible()
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth + 1")
    assert_clean_page(page)


def test_the_choice_survives_an_in_app_visit_and_a_reload_without_flashing_open(desktop_page):
    page = desktop_page
    page.get_by_role("button", name="Collapse menu").click()
    _wait_for_width(page, RAIL)

    page.locator("#sidebar").get_by_role("link", name="Production", exact=True).click()
    page.wait_for_url("**/core")
    assert _width(page) == RAIL
    expect(page.locator("#sidebar").get_by_role("link", name="Production", exact=True)).to_have_attribute(
        "aria-current", "page"
    )

    # On a full load the rail is in place before the page's scripts have run at all.
    page.add_init_script(
        "document.addEventListener('DOMContentLoaded', () => {"
        " window.__railAtParse = document.getElementById('sidebar').getBoundingClientRect().width; })"
    )
    page.reload()
    assert page.evaluate("window.__railAtParse") == RAIL
    expect(page.get_by_role("button", name="Expand menu")).to_have_attribute("aria-expanded", "false")

    page.get_by_role("button", name="Expand menu").focus()
    page.keyboard.press("Enter")
    _wait_for_width(page, OPEN)
    expect(page.locator("#sidebar .nav-label")).to_be_visible()
    page.reload()
    assert _width(page) == OPEN


def test_a_bar_pinned_beside_the_sidebar_moves_with_it(desktop_page):
    page = desktop_page
    page.goto("/core/inventory/add/manual")
    bar = page.locator(".add-inv-manual-submit-bar")
    expect(bar).to_be_visible()
    assert bar.bounding_box()["x"] == OPEN

    page.get_by_role("button", name="Collapse menu").click()
    _wait_for_width(page, RAIL)
    page.wait_for_function("document.querySelector('.add-inv-manual-submit-bar').getBoundingClientRect().left === 80")


def test_a_narrow_laptop_starts_as_the_rail_until_the_user_chooses(desktop_page):
    page = desktop_page
    page.set_viewport_size({"width": 1024, "height": 800})
    page.reload()
    assert _width(page) == RAIL
    page.get_by_role("button", name="Expand menu").click()
    _wait_for_width(page, OPEN)
    page.reload()
    assert _width(page) == OPEN


def test_the_phone_keeps_its_bottom_bar_whatever_was_chosen_on_a_desktop(desktop_page):
    page = desktop_page
    page.get_by_role("button", name="Collapse menu").click()
    _wait_for_width(page, RAIL)
    page.set_viewport_size({"width": 390, "height": 844})
    page.reload()
    bar = page.locator("#sidebar").bounding_box()
    assert round(bar["width"]) == 390 and bar["y"] > 700
    expect(page.locator("[data-sidebar-toggle]")).to_be_hidden()
    assert page.locator(".main-content").bounding_box()["x"] == 0
    for name in ["Home", "Production", "Settings"]:
        expect(page.locator("#sidebar").get_by_role("link", name=name, exact=True)).to_be_visible()
