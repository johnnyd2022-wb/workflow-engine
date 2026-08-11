"""E2E coverage for the two wastage HTML pages (AC-D1/D2/D3, .agents/specs/wastage.md).

Unlike the rest of the wastage surface (tests/e2e/test_inventory_flow.py,
test_tenant_isolation.py's wastage cases), these two routes had no dedicated test file
before this review (feature-index GAP, confirmed by security-audit's F1 finding) —
`/core/inventory/dispose` was only ever hit by test_pages_render.py's generic
render-smoke-test, and `/core/inventory/dispose/confirm` had no coverage at all.
"""

import re
import uuid

import pytest
from playwright.sync_api import Page, expect

from tests.e2e.test_inventory_flow import _create_item
from tests.e2e.test_tenant_isolation import _create_inventory_item, two_tenants  # noqa: F401,F811 (fixture)

pytestmark = pytest.mark.e2e


def test_dispose_page_preselects_only_the_requested_item_ids(logged_in_page: Page):
    """AC-D1: the item_ids query param preselects items, not the whole inventory."""
    page = logged_in_page
    kept_id = _create_item(page, f"E2E Dispose Kept {uuid.uuid4().hex[:8]}")
    other_id = _create_item(page, f"E2E Dispose Other {uuid.uuid4().hex[:8]}")

    page.goto(f"/core/inventory/dispose?item_ids={kept_id}")
    expect(page.locator(f'[data-inventory-id="{kept_id}"]')).to_be_visible()
    expect(page.locator(f'[data-inventory-id="{other_id}"]')).to_have_count(0)


def test_dispose_confirm_computes_remaining_quantity(logged_in_page: Page):
    """AC-D2 happy path: the preview shows the item name, unit, and correct remainder."""
    page = logged_in_page
    name = f"E2E Confirm Remainder {uuid.uuid4().hex[:8]}"
    item_id = _create_item(page, name, quantity=10)

    page.goto(f"/core/inventory/dispose/confirm?inventory_item_id={item_id}&quantity_wasted=3")
    body = page.locator("#dispose-inventory-page")
    expect(body).to_contain_text(name)
    expect(body).to_contain_text("kg")
    # Anchored to the specific sentence the remainder renders into, not a bare "7":
    # `name`'s random hex suffix (uuid4().hex[:8]) can itself contain the digit 7, so a
    # bare to_contain_text("7") would stay green even if the remainder computation broke
    # (test-evaluator finding). \b7\b does not match "7" inside a longer alphanumeric
    # hex run, only as its own token.
    expect(body).to_contain_text(re.compile(r"remaining quantity will be\s*\n?\s*7\b"))


def test_dispose_confirm_rejects_non_finite_quantity(logged_in_page: Page):
    """AC-D2: ?quantity_wasted=nan must render a page-level error, not 500
    (regression coverage for the inventory review's F2 fix, backend.py:742-746)."""
    page = logged_in_page
    item_id = _create_item(page, f"E2E Confirm NaN {uuid.uuid4().hex[:8]}")

    response = page.goto(f"/core/inventory/dispose/confirm?inventory_item_id={item_id}&quantity_wasted=nan")
    assert response.status == 200, f"expected 200 with an error message, got {response.status}"
    expect(page.locator("#dispose-inventory-page")).to_contain_text("Invalid quantity.")


def test_dispose_confirm_rejects_negative_quantity(logged_in_page: Page):
    """AC-D2: a non-positive quantity is a page-level error, not a negative remainder."""
    page = logged_in_page
    item_id = _create_item(page, f"E2E Confirm Negative {uuid.uuid4().hex[:8]}")

    response = page.goto(f"/core/inventory/dispose/confirm?inventory_item_id={item_id}&quantity_wasted=-3")
    assert response.status == 200
    expect(page.locator("#dispose-inventory-page")).to_contain_text("Quantity must be greater than 0.")


def test_dispose_confirm_missing_item_id_shows_error(logged_in_page: Page):
    """AC-D2: no inventory_item_id at all is a page-level error, not a 500 or a blank page."""
    page = logged_in_page

    response = page.goto("/core/inventory/dispose/confirm?quantity_wasted=1")
    assert response.status == 200
    expect(page.locator("#dispose-inventory-page")).to_contain_text("Missing inventory item id.")


def test_dispose_confirm_nonexistent_item_shows_error(logged_in_page: Page):
    """AC-D2: a well-formed but nonexistent item id resolves to the same not-found error
    a cross-tenant id gets (test_org_b_cannot_preview_dispose_org_a_item below) — the
    baseline this review's cross-tenant test is compared against."""
    page = logged_in_page

    response = page.goto(f"/core/inventory/dispose/confirm?inventory_item_id={uuid.uuid4()}&quantity_wasted=1")
    assert response.status == 200
    expect(page.locator("#dispose-inventory-page")).to_contain_text("Inventory item was not found.")


def test_org_b_cannot_preview_dispose_org_a_item(two_tenants):  # noqa: F811 (pytest fixture param, not a redefinition)
    """AC-D3/AC33: org B previewing a disposal against org A's item id must see the same
    generic not-found state a genuinely nonexistent id gets — never org A's real item
    name, unit, or quantity. This is the security-audit F1 finding's actual regression
    test (.agents/reports/wastage/security-audit.md)."""
    marker_name = f"Secret Dispose Botanicals {uuid.uuid4().hex[:8]}"
    item_id = _create_inventory_item(two_tenants["a"], marker_name, quantity_override=42)

    page_b = two_tenants["b"]
    response = page_b.goto(f"/core/inventory/dispose/confirm?inventory_item_id={item_id}&quantity_wasted=1")
    assert response.status == 200, f"expected 200 with a not-found error, got {response.status}"

    # Scope the leak check to the page's own disclosed-content region, not the raw HTML
    # source: the full page (script bundles, correlation ids, CSS) can coincidentally
    # contain any short numeric substring, which would make a whole-page search noise,
    # not signal. The content div is what the template actually renders the item's
    # name/unit/quantity into (backend.py:784-793), so it's the real disclosure surface.
    disclosed = page_b.locator("#dispose-inventory-page").inner_text()
    assert marker_name not in disclosed, "org A's item name leaked onto org B's dispose-confirm page"
    # The page never echoes the raw on-hand quantity (42) back — only the COMPUTED
    # REMAINDER (42-1=41) if the item resolves, per the template's `remaining_dec =
    # current_qty_dec - quantity_wasted_dec` (backend.py:770-777). Checking for "42"
    # would stay green even under a real leak, since "42" itself is never the disclosed
    # value (test-evaluator finding) — "41" is the value that would actually appear.
    assert "41" not in disclosed, "org A's computed remaining quantity leaked onto org B's dispose-confirm page"
    expect(page_b.locator("#dispose-inventory-page")).to_contain_text("Inventory item was not found.")

    # Sanity: the owner previewing the same item sees the real data — proves the probe
    # would have caught a leak rather than the assertions being universally true. This
    # also proves "41" is the actual disclosed value the org-B assertion above guards:
    # the legitimate owner's own preview of this exact request DOES show it.
    page_a = two_tenants["a"]
    owner_response = page_a.goto(f"/core/inventory/dispose/confirm?inventory_item_id={item_id}&quantity_wasted=1")
    assert owner_response.status == 200
    owner_disclosed = page_a.locator("#dispose-inventory-page").inner_text()
    assert marker_name in owner_disclosed
    assert "41" in owner_disclosed, (
        "sanity check failed: the probe's own owner-view didn't disclose the remainder either"
    )
