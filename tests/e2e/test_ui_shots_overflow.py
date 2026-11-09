"""ui_shots' mobile guard: a page that scrolls sideways at phone width must fail its shot.

CLAUDE.md makes "no sideways scroll on mobile" a hard rule for UI work, and every page
design pass relies on this check to enforce it, so it has to catch real overflow and leave
deliberately scrollable regions alone. Runs against real Chromium on static HTML: no app,
no database.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))
import ui_shots  # noqa: E402

FITS = "<body style='margin:0'><p>Short text that wraps.</p></body>"
OVERFLOWS = "<body style='margin:0'><div id='too-wide' class='card wide' style='width:800px'>x</div></body>"
SCROLLS_INSIDE = (
    "<body style='margin:0'><div id='table-wrap' style='overflow-x:auto'>"
    "<table id='wide-table' style='width:900px'><tr><td>x</td></tr></table></div></body>"
)


@pytest.fixture(scope="module")
def browser(playwright):
    # Share pytest-playwright's driver; starting another sync driver while its
    # event loop is active raises before any overflow assertion can run.
    try:
        browser = playwright.chromium.launch()
    except Exception as error:  # an absent browser is a skip with a reason, not a failure
        pytest.skip(f"Playwright Chromium not installed: {error}")
    yield browser
    browser.close()


@pytest.fixture
def page(browser):
    page = browser.new_page(viewport=ui_shots.PHONE)
    yield page
    page.close()


def test_phone_shot_fails_and_names_the_element_that_sticks_out(page, tmp_path):
    page.set_content(OVERFLOWS)
    with pytest.raises(AssertionError) as raised:
        ui_shots.shot(page, tmp_path, "phone")
    assert "scrolls sideways at 390px" in str(raised.value)
    assert "div#too-wide.card.wide" in str(raised.value)
    assert (tmp_path / "phone.png").exists(), "the shot is saved before failing, so the overflow can be seen"


def test_phone_shot_passes_when_the_page_fits(page, tmp_path):
    page.set_content(FITS)
    assert ui_shots.shot(page, tmp_path, "phone").exists()


def test_a_deliberately_scrolling_inner_region_is_allowed(page, tmp_path):
    page.set_content(SCROLLS_INSIDE)
    assert ui_shots.shot(page, tmp_path, "phone").exists()


@pytest.mark.parametrize("viewport", [ui_shots.LAPTOP, ui_shots.DESKTOP])
def test_wider_layouts_are_not_held_to_the_mobile_rule(browser, tmp_path, viewport):
    page = browser.new_page(viewport=viewport)
    try:
        page.set_content("<body style='margin:0'><div style='width:2400px'>x</div></body>")
        assert ui_shots.shot(page, tmp_path, "wide").exists()
    finally:
        page.close()
