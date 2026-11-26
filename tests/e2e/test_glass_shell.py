"""GLASS PROTOTYPE: the shell every signed-in page shares (branch proto/glass-theme only).

The top bar replaces the sidebar, Home is gone, and Action items is one tray in the top bar on every
page. Pages swap under it by htmx boost, so the bar must keep working after any number of in-app
navigations, at laptop and phone width.
"""

import re

import pytest

from app.ui.page_registry import PAGES

pytestmark = pytest.mark.e2e

PHONE = {"width": 390, "height": 844}
SMALL = {"width": 320, "height": 700}
LAPTOP = {"width": 1440, "height": 900}

# One page per workspace and kind (overview, list, form, settings): enough to catch a page that
# breaks the shell without walking every route (test_boosted_navigation walks them all).
SAMPLE = [
    "/core",
    "/core/inventory/view",
    "/core/processes",
    "/core/planner",
    "/core/tasks/configuration",
    "/core/settings",
    "/core/notifications",
    "/compliant/nz-alcohol",
    "/crm",
    "/crm/customers",
]


def _settle(page):
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(250)


def _wide(page):
    return page.evaluate("() => document.documentElement.scrollWidth - window.innerWidth")


def test_home_is_gone_and_redirects_to_production(logged_in_page):
    page = logged_in_page
    page.goto("/core/dashboard")
    _settle(page)
    assert re.search(r"/core/?$", page.url), page.url
    assert page.locator(".g-ws a", has_text="Home").count() == 0
    assert page.locator("#sidebar").count() == 0


def test_production_tabs_are_in_the_new_order(logged_in_page):
    page = logged_in_page
    page.goto("/core")
    _settle(page)
    tabs = page.locator("#page-content .section-tabs [data-section-tab]:not([hidden])").all_inner_texts()
    assert [t.strip() for t in tabs][:5] == ["Overview", "Inventory", "Workflows", "Planner", "Tasks"]


@pytest.mark.parametrize("path", SAMPLE)
def test_every_page_has_the_glass_top_bar_and_no_sideways_scroll(logged_in_page, path):
    page = logged_in_page
    if not any(p.path == path for p in PAGES):
        pytest.skip(f"{path} not registered")
    page.set_viewport_size(LAPTOP)
    response = page.goto(path)
    _settle(page)
    if response is None or response.status >= 400 or not page.url.split("?")[0].endswith(path):
        pytest.skip(f"{path} is not open to the e2e org (status {response and response.status}, at {page.url})")
    assert page.locator("[data-glass-topbar]").is_visible()
    assert page.locator("#g-act-btn").is_visible()
    assert page.locator("#topbar-notifications-link").is_visible()
    page.set_viewport_size(SMALL)
    page.goto(path)
    _settle(page)
    assert page.locator("[data-glass-tabbar]").is_visible()
    assert _wide(page) <= 1, f"{path} scrolls sideways at 320px"


def test_action_items_tray_opens_shows_the_board_and_closes(logged_in_page):
    page = logged_in_page
    page.set_viewport_size(LAPTOP)
    page.goto("/core/inventory/view")
    _settle(page)
    btn = page.locator("#g-act-btn")
    tray = page.locator("#g-act-tray")
    page.wait_for_function("() => !/Loading/.test(document.getElementById('g-act-cap').textContent)")
    btn.click()
    assert tray.is_visible()
    assert btn.get_attribute("aria-expanded") == "true"
    assert page.locator("#g-act-list li").count() >= 1
    page.keyboard.press("Escape")
    assert not tray.is_visible()
    assert btn.get_attribute("aria-expanded") == "false"

    # On a phone it is a bottom sheet, outside the top bar so it can sit at the bottom of the screen.
    page.set_viewport_size(PHONE)
    page.goto("/core/inventory/view")
    _settle(page)
    btn.click()
    page.wait_for_timeout(400)  # the sheet rises for 220ms
    box = tray.bounding_box()
    assert box and abs(box["y"] + box["height"] - PHONE["height"]) <= 2, box
    page.locator("#g-scrim").click(position={"x": 10, "y": 10})
    assert not tray.is_visible()


def test_top_bar_survives_boosted_navigation(logged_in_page):
    """Ten in-app clicks later the bar still tracks the workspace and the tray still opens."""
    page = logged_in_page
    page.set_viewport_size(LAPTOP)
    page.goto("/core")
    _settle(page)
    # The /core pages, then every workspace the top bar offers this user (not every e2e org has
    # Compliance or Sales).
    paths = [p for p in SAMPLE[1:] if p.startswith("/core")]
    paths += [h for h in page.locator(".g-ws a").evaluate_all("els => els.map(a => a.getAttribute('href'))") if h != "/core"]
    for path in paths:
        page.evaluate(
            """(href) => { const a = document.createElement('a'); a.href = href; a.id = '__glass_probe';
                document.querySelector('#page-content').appendChild(a); htmx.process(a); a.click(); }""",
            path,
        )
        try:
            page.wait_for_url(f"**{path}", timeout=15_000)
        except Exception as exc:  # name the page that did not arrive
            raise AssertionError(f"boosted click to {path} ended on {page.url}") from exc
        _settle(page)
        section = page.locator("#page-content [data-nav-section]").first.get_attribute("data-nav-section")
        current = page.locator(".g-ws a[aria-current='page']")
        if section in ("production", "compliance", "sales"):
            assert current.count() == 1 and current.get_attribute("data-nav-section") == section, path
        else:
            assert current.count() == 0, path
    page.locator("#g-act-btn").click()
    assert page.locator("#g-act-tray").is_visible()
