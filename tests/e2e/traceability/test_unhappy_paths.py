"""Unhappy paths: invalid item ids, an empty search, and an item with no trace history.

AC1/AC6 (invalid id -> 400, never a 500) are checked by hitting the trace endpoints
directly, the way a forged/typo'd URL or search would -- the sourcemap UI itself never
constructs one of these ids from free text (search only ever filters the browse grid; a
trace is always started by clicking a card, which supplies a real id), so the endpoint is
the honest place to prove the guard.
"""

import uuid
from uuid import UUID

import pytest
from playwright.sync_api import Page, expect

from tests.e2e.conftest import csrf_headers

pytestmark = pytest.mark.e2e


def test_ac1_forward_trace_non_uuid_returns_400_not_500(logged_in_page: Page):
    page = logged_in_page
    resp = page.request.get("/api/core/inventory/trace/not-a-uuid")
    assert resp.status == 400, f"expected 400, got {resp.status}: {resp.text()}"
    assert "error" in resp.json()


def test_ac6_backward_trace_non_uuid_returns_400_not_500(logged_in_page: Page):
    page = logged_in_page
    resp = page.request.get("/api/core/inventory/trace-backward/not-a-uuid")
    assert resp.status == 400, f"expected 400, got {resp.status}: {resp.text()}"
    assert "error" in resp.json()


def test_ac11_sourcemap_trace_post_non_uuid_root_id_returns_400_not_500(logged_in_page: Page):
    """POST /api/core/sourcemap/trace is the route the temporal-replay UI actually calls
    (smRunTemporalTrace always sets as_of -- AC23), so a malformed root_id reaching it is a
    real UI-adjacent unhappy path, not just a forged request. The UUID parse (backend.py
    ~5709-5712) runs before the as_of/no-as_of branch split, so this guard applies to both
    the temporal and current-state branches identically."""
    page = logged_in_page
    resp = page.request.post(
        "/api/core/sourcemap/trace",
        headers=csrf_headers(page),
        data={"root_type": "inventory_item", "root_id": "not-a-uuid", "as_of": "2026-01-01T00:00:00Z", "depth": 3},
    )
    assert resp.status == 400, f"expected 400, got {resp.status}: {resp.text()}"
    assert "error" in resp.json()


def test_ac2_forward_trace_nonexistent_uuid_in_own_org_returns_404(logged_in_page: Page):
    page = logged_in_page
    resp = page.request.get(f"/api/core/inventory/trace/{uuid.uuid4()}")
    assert resp.status == 404, f"expected 404, got {resp.status}: {resp.text()}"
    assert resp.json()["error"] == "Raw material not found"


def test_ac6_backward_trace_nonexistent_uuid_in_own_org_returns_404(logged_in_page: Page):
    page = logged_in_page
    resp = page.request.get(f"/api/core/inventory/trace-backward/{uuid.uuid4()}")
    assert resp.status == 404, f"expected 404, got {resp.status}: {resp.text()}"
    assert resp.json()["error"] == "Inventory item not found"


def test_empty_search_shows_all_browse_cards_again(traced_chain):
    page, _dag, _user = traced_chain
    page.goto("/core/sourcemap")
    page.wait_for_load_state("networkidle")
    expect(page.locator(".sm-browse-card")).to_have_count(3)

    search = page.locator("#sm-search-input")
    search.fill("R1")
    expect(page.locator(".sm-browse-card")).to_have_count(1)

    search.fill("")
    expect(page.locator(".sm-browse-card")).to_have_count(3)

    # The explicit clear button (×) is the other route back to an empty query; it must
    # produce the same result as clearing the input by hand.
    search.fill("R1")
    expect(page.locator(".sm-browse-card")).to_have_count(1)
    page.locator("#sm-search-clear").click()
    expect(page.locator("#sm-search-input")).to_have_value("")
    expect(page.locator(".sm-browse-card")).to_have_count(3)


def test_item_with_no_trace_history_renders_as_lone_card(traced_chain):
    """A raw material never consumed by any execution has no connections -- the trace
    result is just the item itself, rendered as a lone card, not a broken timeline or an
    error state."""
    page, _dag, user = traced_chain
    from app.core.db import db_session
    from tests.factories import InventoryItemFactory

    InventoryItemFactory(org_id=UUID(user["org_id"]), name="Lonely Raw", quantity="4", unit="kg")
    db_session().commit()

    page.goto("/core/sourcemap")
    page.wait_for_load_state("networkidle")

    card = page.locator(".sm-browse-card", has_text="Lonely Raw").first
    expect(card).to_be_visible()
    card.click()

    expect(page.locator(".sm-lone-item")).to_be_visible()
    expect(page.locator(".sm-impact-header__item-name")).to_have_text("Lonely Raw")
    # No execution history -> no timeline entries, no false process/step data.
    expect(page.locator(".sm-timeline-entry")).to_have_count(0)


def test_item_with_no_trace_history_api_response_shape(traced_chain):
    """Same case at the API level: connections is empty, all_items has exactly the item
    itself, and the raw material's own record is still returned (AC3)."""
    page, _dag, user = traced_chain
    from app.core.db import db_session
    from tests.factories import InventoryItemFactory

    item = InventoryItemFactory(org_id=UUID(user["org_id"]), name="Lonely Raw 2", quantity="4", unit="kg")
    db_session().commit()

    resp = page.request.get(f"/api/core/inventory/trace/{item.id}")
    assert resp.status == 200, resp.text()
    body = resp.json()
    assert body["connections"] == []
    assert body["raw_material"]["id"] == str(item.id)
    assert [i["id"] for i in body["all_items"]] == [str(item.id)]
