"""Stage 2: inventory write flow driven through the real UI.

The app's spine ends in an inventory quantity write, which the domain guards with a
required write-reason (see CLAUDE.md). This drives the manual-add page like a user and
confirms the item actually lands, then the unhappy path. Reaching the write through the
browser exercises the CSRF header, the SPA's API client, and the render — none of which a
unit test touches.
"""

import re
import uuid

import pytest
from playwright.sync_api import Page, expect

from tests.e2e.conftest import assert_clean_page

pytestmark = pytest.mark.e2e


def test_manual_inventory_add_persists_and_shows(logged_in_page: Page):
    page = logged_in_page
    name = f"E2E Botanical {uuid.uuid4().hex[:8]}"

    page.goto("/core/inventory/add/manual")
    expect(page.locator("#add-inventory-name")).to_be_visible()

    # Assert cleanliness of the add page here, before submit. Not on the post-redirect
    # /core: submitting redirects while the add page's background /system-findings poll is
    # still in flight, and that navigation-cancelled fetch surfaces as a console error
    # that races the assertion. /core's own cleanliness is covered on a settled load by
    # test_pages_render — the right place for it. Here we assert the flow's real outcomes.
    assert_clean_page(page)

    page.locator("#add-inventory-name").fill(name)
    page.locator("#add-inventory-quantity").fill("12.5")
    page.locator("#add-inventory-unit").select_option("kg")
    page.locator("#add-inv-manual-submit-btn").click()

    # On success the page redirects to /core (add_manual.html) — the reliable success
    # signal; the toast is too fleeting to assert on without racing it.
    page.wait_for_url(re.compile(r"/core$"), timeout=15_000)

    # And it must actually be queryable afterwards — the write reached the database.
    listing = page.request.get("/api/core/inventory")
    assert listing.status == 200
    assert name in listing.text(), "added item is not in the inventory list"


def test_manual_inventory_add_rejects_zero_quantity(logged_in_page: Page):
    """Unhappy path: the domain rejects a non-positive quantity, and no row is written."""
    page = logged_in_page
    name = f"E2E ShouldNotExist {uuid.uuid4().hex[:8]}"

    page.goto("/core/inventory/add/manual")
    expect(page.locator("#add-inventory-name")).to_be_visible()

    page.locator("#add-inventory-name").fill(name)
    page.locator("#add-inventory-quantity").fill("0")
    page.locator("#add-inventory-unit").select_option("kg")
    page.locator("#add-inv-manual-submit-btn").click()

    # Give any (incorrect) write time to happen, then prove it did not.
    page.wait_for_timeout(1500)
    listing = page.request.get("/api/core/inventory")
    assert name not in listing.text(), "a zero-quantity item was written despite the guard"
