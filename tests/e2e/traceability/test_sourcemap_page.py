"""AC21: the sourcemap page loads. AC3: a forward trace from the browse grid renders.

View-switch and the wastage toggle are asserted not to refetch the trace: `smBindControls`
(sourcemap.js) re-renders from the cached `lastTraceResult` on view switch, and the wastage
toggle calls a separate `/inventory/wastage` endpoint entirely -- both are behavioural
claims worth pinning so a future change that reintroduces a refetch is caught here rather
than as a slow page in production.
"""

import pytest
from playwright.sync_api import Page, expect

from tests.e2e.conftest import assert_clean_page, csrf_headers

pytestmark = pytest.mark.e2e


def test_ac21_sourcemap_page_loads(logged_in_page: Page):
    page = logged_in_page
    page.goto("/core/sourcemap")
    page.wait_for_load_state("networkidle")

    expect(page.get_by_role("heading", name="Source Map")).to_be_visible()
    expect(page.locator("#sm-search-input")).to_be_visible()
    # Controls (view toggle, wastage, legend) are hidden in browse mode, before any trace.
    expect(page.locator("#sm-controls")).to_be_hidden()
    assert_clean_page(page)


def test_ac3_forward_trace_from_browse_grid_renders_timeline(traced_chain):
    page, _dag, _user = traced_chain
    page.goto("/core/sourcemap")
    page.wait_for_load_state("networkidle")

    card = page.locator(".sm-browse-card", has_text="R1").first
    expect(card).to_be_visible()
    card.click()

    expect(page.locator("#sm-controls")).to_be_visible()
    expect(page.locator(".sm-impact-header__item-name")).to_have_text("R1")
    expect(page.locator(".sm-timeline-entry").first).to_be_visible()
    expect(page.locator(".sm-timeline-process").first).to_contain_text("Linear Test Process")
    assert_clean_page(page)


def test_view_switch_renders_map_and_table_without_refetching_trace(traced_chain):
    page, _dag, _user = traced_chain
    trace_requests: list[str] = []
    page.on(
        "request",
        lambda req: trace_requests.append(req.url) if "/api/core/inventory/trace" in req.url else None,
    )

    page.goto("/core/sourcemap")
    page.wait_for_load_state("networkidle")
    page.locator(".sm-browse-card", has_text="R1").first.click()
    expect(page.locator(".sm-timeline-entry").first).to_be_visible()
    assert len(trace_requests) == 1, f"expected exactly one trace fetch, got {trace_requests}"

    page.get_by_role("tab", name="Map").click()
    expect(page.locator(".sm-tree-root")).to_be_visible()
    assert len(trace_requests) == 1, "switching to map view must not refetch the trace"

    page.get_by_role("tab", name="Table").click()
    expect(page.locator("#sm-table-wrap")).to_be_visible()
    expect(page.locator("#sm-table-body tr").first).to_be_visible()
    assert len(trace_requests) == 1, "switching to table view must not refetch the trace"

    page.get_by_role("tab", name="Timeline").click()
    expect(page.locator(".sm-timeline-entry").first).to_be_visible()
    assert len(trace_requests) == 1, "switching back to timeline must not refetch the trace"


def test_wastage_toggle_does_not_refetch_trace(traced_chain):
    page, _dag, _user = traced_chain
    trace_requests: list[str] = []
    wastage_requests: list[str] = []

    def _record(req):
        if "/api/core/inventory/trace" in req.url:
            trace_requests.append(req.url)
        elif "/api/core/inventory/wastage" in req.url:
            wastage_requests.append(req.url)

    page.on("request", _record)

    page.goto("/core/sourcemap")
    page.wait_for_load_state("networkidle")
    page.locator(".sm-browse-card", has_text="R1").first.click()
    expect(page.locator(".sm-timeline-entry").first).to_be_visible()
    assert len(trace_requests) == 1

    page.locator("#sm-wastage-toggle").click()
    expect(page.locator("#sm-wastage-inline")).to_be_visible()
    assert len(wastage_requests) == 1, "wastage toggle must fetch the wastage log exactly once"
    assert len(trace_requests) == 1, "wastage toggle must not refetch the trace"

    # And toggling it back off does not re-fetch either endpoint.
    page.locator("#sm-wastage-toggle").click()
    expect(page.locator("#sm-wastage-inline")).to_be_hidden()
    assert len(wastage_requests) == 1
    assert len(trace_requests) == 1


def test_ac10_sourcemap_trace_dispatch_without_as_of_returns_current_state_graph(traced_chain):
    """AC10: POST /api/core/sourcemap/trace's current-state (no as_of) branch must return a
    real graph, 200, not the 500 it used to raise -- the route imported a module
    (app.features.workflow_engine.dagtraversal) that does not exist anywhere in the repo, so
    every call into this branch raised ModuleNotFoundError, caught by a bare except and
    turned into a generic 500 (backend.py's sourcemap_trace, confirmed dead/broken when this
    suite was first written -- see .agents/reports/traceability/security-audit.md F2 and
    .agents/reports/traceability/e2e-playwright.md). Not reachable from the SPA today
    (smRunTemporalTrace always sends as_of, per AC23) but it is a live, authenticated route,
    so it must not silently 500 for its documented alternate mode.
    """
    page, dag, _user = traced_chain

    resp = page.request.post(
        "/api/core/sourcemap/trace",
        headers=csrf_headers(page),
        data={"root_type": "inventory_item", "root_id": str(dag["w1_id"])},
    )
    assert resp.status == 200, resp.text()
    body = resp.json()
    assert body["is_current"] is True
    assert body["as_of"] is None
    node_ids = {n["id"] for n in body["nodes"]}
    assert str(dag["w1_id"]) in node_ids, "the requested root item must be in the returned graph"
    assert str(dag["r1_id"]) in node_ids, "W1's upstream source (R1) must also be in the graph"
