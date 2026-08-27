"""The /core first-paint request waterfall is now a contract, not an accident.

Before docs/core-load-performance-design.md, opening /core fired four data calls in
parallel (metrics + processes + fully-enriched inventory + full execution history) and the
active-batches graph then issued a fifth, larger processes?include_steps=true. The
inventory and execution payloads grow without bound as an org accumulates history.

These tests fail if any of that creeps back: initial navigation must make exactly one
data call (`/api/core/hub/overview`), and the Inventory / Workflows tab data must not load
until its tab is actually opened -- and must not reload on a second visit.
"""

import pytest

pytestmark = [pytest.mark.e2e]


def _core_api_calls(page):
    """Attach a recorder for /api/core/* GETs; returns the growing list of paths+queries."""
    calls: list[str] = []

    def _on_request(request):
        if request.method != "GET":
            return
        url = request.url
        if "/api/core/" in url:
            # keep path + query so we can tell processes from processes?include_steps=true
            calls.append(url.split("/api/core/", 1)[1])

    page.on("request", _on_request)
    return calls


def _wait(page):
    page.wait_for_load_state("networkidle")


def test_initial_core_load_makes_one_overview_call_and_no_heavy_lists(logged_in_page):
    page = logged_in_page
    calls = _core_api_calls(page)

    page.goto("/core")
    _wait(page)

    assert calls.count("hub/overview") == 1, calls
    assert not any(c == "inventory" or c.startswith("inventory?") for c in calls), calls
    assert not any(c == "executions" or c.startswith("executions?") for c in calls), calls
    assert not any("include_steps=true" in c for c in calls), calls


def test_inventory_tab_loads_on_open_and_not_again(logged_in_page):
    page = logged_in_page
    calls = _core_api_calls(page)

    page.goto("/core")
    _wait(page)
    base_inv = sum(1 for c in calls if c == "inventory" or c.startswith("inventory?"))
    assert base_inv == 0

    page.click('[data-core2-tab-target="inventory"]')
    _wait(page)
    after_open = sum(1 for c in calls if c == "inventory" or c.startswith("inventory?"))
    assert after_open == 1, calls

    # leave and come back -- the tab is already loaded, no second fetch
    page.click('[data-core2-tab-target="overview"]')
    _wait(page)
    page.click('[data-core2-tab-target="inventory"]')
    _wait(page)
    assert sum(1 for c in calls if c == "inventory" or c.startswith("inventory?")) == 1, calls


def test_workflows_tab_defers_execution_history_until_opened(logged_in_page):
    page = logged_in_page
    calls = _core_api_calls(page)

    page.goto("/core")
    _wait(page)
    assert not any(c == "executions" or c.startswith("executions?") for c in calls), calls

    page.click('[data-core2-tab-target="workflows"]')
    _wait(page)
    assert sum(1 for c in calls if c == "executions" or c.startswith("executions?")) == 1, calls
