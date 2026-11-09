"""UX-SWEEP, Production: the single-task pages carry a real page heading, content buttons follow
Style 1 in the dark theme (teal, not the shell's mustard), and a short page stays dark to the
bottom on a phone."""

from __future__ import annotations

import pytest
from playwright.sync_api import Page

from tests.e2e.conftest import assert_clean_page

pytestmark = pytest.mark.e2e

TEAL = "rgb(45, 212, 191)"


def _dark(page: Page, path: str, width: int = 1440):
    page.set_viewport_size({"width": width, "height": 844 if width < 600 else 900})
    page.goto(path)
    page.wait_for_load_state("networkidle")
    page.evaluate("() => document.documentElement.setAttribute('data-spa-theme', 'dark')")
    page.wait_for_timeout(200)


@pytest.mark.parametrize(
    ("path", "heading"),
    [
        ("/core/inventory/add/manual", "Add inventory manually"),
        ("/core/inventory/add/barcode", "Add inventory by barcode"),
        ("/core/inventory/add/csv", "Add inventory from a file"),
        ("/core/flows/create/start", "Create a workflow"),
    ],
)
def test_each_page_has_its_title_as_the_h1(logged_in_page: Page, path, heading):
    logged_in_page.goto(path)
    logged_in_page.wait_for_load_state("networkidle")
    assert logged_in_page.locator("#page-content h1").first.inner_text().strip() == heading
    assert_clean_page(logged_in_page)


def test_a_primary_button_is_teal_in_the_dark_theme(logged_in_page: Page):
    _dark(logged_in_page, "/core/inventory/add/manual")
    button = logged_in_page.locator(".add-inv-manual-submit-bar__btn")
    background = button.evaluate("el => getComputedStyle(el).backgroundColor")
    image = button.evaluate("el => getComputedStyle(el).backgroundImage")
    assert background == TEAL and image == "none", (background, image)


def test_a_short_page_stays_dark_to_the_bottom_on_a_phone(logged_in_page: Page):
    _dark(logged_in_page, "/core/inventory/add", width=390)
    body = logged_in_page.evaluate("() => getComputedStyle(document.body).backgroundColor")
    assert body == "rgb(3, 3, 3)", body
