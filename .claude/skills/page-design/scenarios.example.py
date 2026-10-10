"""Example scenario file for scripts/ui_shots.py. Copy it next to your screenshots and edit.

Each public function takes (page, out) and is one view worth looking at. Keep one function
per state you would otherwise have to click to: the page as it loads, a filter applied, the
empty state, a panel open, the phone width, the dark theme.

    env -u ENVIRONMENT uv run python scripts/ui_shots.py shoot OUT \
        --scenarios .claude/skills/page-design/scenarios.example.py
"""

from ui_shots import PHONE, TABLET, settle, shot, theme

PAGE = "/core/inventory/view"
READY = "#inv-view-tbody tr"  # something that only exists once the page has its data


def _open(page, viewport=None):
    if viewport:
        page.set_viewport_size(viewport)
    page.goto(PAGE)
    page.locator(READY).first.wait_for()
    settle(page)


def desktop(page, out):
    _open(page)
    shot(page, out, "desktop")  # what a person sees without scrolling: judge this one first
    shot(page, out, "desktop-full", full=True)


def filtered_then_empty(page, out):
    _open(page)
    page.get_by_role("searchbox", name="Search inventory").fill("juniper")
    settle(page, 200)
    shot(page, out, "filtered")
    page.get_by_role("searchbox", name="Search inventory").fill("no such thing")
    settle(page, 200)
    shot(page, out, "empty")


def detail_open(page, out):
    _open(page)
    page.locator(READY).first.get_by_role("button").first.click()
    settle(page)
    shot(page, out, "detail")
    page.keyboard.press("Escape")


def tablet(page, out):
    _open(page, TABLET)
    shot(page, out, "tablet")


def phone(page, out):
    _open(page, PHONE)
    shot(page, out, "phone")
    shot(page, out, "phone-full", full=True)


def dark(page, out):
    _open(page)
    theme(page, "dark")
    shot(page, out, "dark")
    theme(page, "light")


def survives_a_boosted_round_trip(page, out):
    """Leave by an in-app link and come back: a page that only works on a full load fails here."""
    _open(page)
    page.get_by_role("link", name="Live inventory", exact=True).click()
    page.wait_for_url("**/core/inventory/live")
    settle(page)
    page.get_by_role("link", name="Back to inventory", exact=True).click()
    page.locator(READY).first.wait_for(timeout=8000)
    shot(page, out, "after-round-trip")
