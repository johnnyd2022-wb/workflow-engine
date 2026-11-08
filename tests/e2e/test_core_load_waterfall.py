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
    # /api/core/system-findings runs the whole check suite server-side; the several
    # page-load callers must collapse to one request, never fire it twice serially.
    assert calls.count("system-findings") <= 1, calls


# /core lost its in-page tab buttons in 51fd6dc6 (Inventory and Workflows are their own
# pages in the Production sub-nav). Its panels remain, opened by `?tab=` links (e.g. the
# stock-integrity check's "/core?tab=inventory") and by Back/Forward through
# setCore2MainTab, so the lazy-load contract below is driven the same way.


def _show(page, tab):
    """Open a /core panel in place, as a ?tab= link does once the page is up."""
    # After a boosted swap the hub's scripts run a moment after its markup appears.
    page.wait_for_function("() => typeof setCore2MainTab === 'function'")
    page.evaluate("tab => setCore2MainTab(tab, { historyMode: 'push' })", tab)
    page.wait_for_function(
        'tab => { const e = document.querySelector(`[data-core2-tab-panel="${tab}"]`); return e && !e.hidden; }',
        arg=tab,
    )


def _inventory_calls(calls):
    return sum(1 for c in calls if c == "inventory" or c.startswith("inventory?"))


def _execution_calls(calls):
    return sum(1 for c in calls if c == "executions" or c.startswith("executions?"))


def test_inventory_tab_loads_on_open_and_not_again(logged_in_page):
    page = logged_in_page
    calls = _core_api_calls(page)

    page.goto("/core")
    _wait(page)
    assert _inventory_calls(calls) == 0

    _show(page, "inventory")
    _wait(page)
    assert _inventory_calls(calls) == 1, calls

    # leave and come back -- the panel is already loaded, no second fetch
    _show(page, "overview")
    _show(page, "inventory")
    _wait(page)
    assert _inventory_calls(calls) == 1, calls


def test_workflows_tab_defers_execution_history_until_opened(logged_in_page):
    page = logged_in_page
    calls = _core_api_calls(page)

    page.goto("/core")
    _wait(page)
    assert _execution_calls(calls) == 0, calls

    _show(page, "workflows")
    _wait(page)
    assert _execution_calls(calls) == 1, calls


def test_core_tabs_follow_browser_back_and_forward_without_reloading_data(logged_in_page):
    """A panel is a navigable Core view, not a state change the browser loses.

    Moving Back/Forward between already-opened panels only switches them and reuses
    their cached data.
    """
    page = logged_in_page
    calls = _core_api_calls(page)

    page.goto("/core?tab=inventory")
    _wait(page)
    _show(page, "workflows")
    assert "tab=workflows" in page.url

    page.go_back()
    page.wait_for_function(
        "() => { const e = document.querySelector('[data-core2-tab-panel=\"inventory\"]'); return e && !e.hidden; }"
    )
    assert "tab=inventory" in page.url

    page.go_forward()
    page.wait_for_function(
        "() => { const e = document.querySelector('[data-core2-tab-panel=\"workflows\"]'); return e && !e.hidden; }"
    )
    assert "tab=workflows" in page.url
    assert _inventory_calls(calls) == 1, calls
    assert _execution_calls(calls) == 1, calls


@pytest.mark.parametrize(("tab", "loaded_calls"), [("inventory", _inventory_calls), ("workflows", _execution_calls)])
def test_core_detail_tabs_reload_after_boosted_return(logged_in_page, tab, loaded_calls):
    """A swapped-in Core panel must not inherit the old panel's lazy-load cache."""
    page = logged_in_page
    calls = _core_api_calls(page)

    page.goto("/core/dashboard")
    page.wait_for_selector("[data-dashboard-root]")
    _wait(page)

    page.locator('a.nav-link[href="/core"]').click()
    page.wait_for_selector(f'[data-core2-tab-panel="{tab}"]', state="attached")
    _wait(page)
    _show(page, tab)
    _wait(page)
    first_load_count = loaded_calls(calls)
    assert first_load_count == 1, calls

    page.locator('a.nav-link[href="/core/dashboard"]').click()
    page.wait_for_selector("[data-dashboard-root]")
    _wait(page)
    page.locator('a.nav-link[href="/core"]').click()
    page.wait_for_selector(f'[data-core2-tab-panel="{tab}"]', state="attached")
    _wait(page)
    _show(page, tab)
    _wait(page)

    assert loaded_calls(calls) == first_load_count + 1, calls


def test_core_overview_is_deterministic_and_traceability_is_on_inventory_tab(logged_in_page):
    """A plain /core is an operational landing page, not the last browser's panel state."""
    page = logged_in_page
    page.goto("/core?tab=inventory")
    _wait(page)
    assert page.locator('[data-core2-tab-panel="inventory"]').is_visible()
    assert page.locator("#core2-inv-summary-traceable").is_visible()
    page.evaluate("localStorage.setItem('core2.mainTab', 'workflows')")

    page.goto("/core")
    _wait(page)
    assert page.url.endswith("/core")
    assert page.locator('[data-core2-tab-panel="overview"]').is_visible()
    assert page.locator('[data-core2-tab-panel="inventory"]').is_hidden()
    assert page.locator('[data-core2-tab-panel="workflows"]').is_hidden()


def test_auth_me_is_fetched_once_per_page(logged_in_page):
    """The profile mascot (base_spa), the sidebar account widget and flows2 each used to
    fetch /auth/me; they now share CoreAPI.getMe."""
    page = logged_in_page
    me: list[str] = []
    page.on("request", lambda r: me.append(r.url) if r.method == "GET" and "/auth/me" in r.url else None)

    for path in ("/core", "/core/processes", "/core/flows"):
        me.clear()
        page.goto(path)
        _wait(page)
        assert len(me) <= 1, f"{path}: /auth/me fetched {len(me)}x"


def test_executions_live_loads_bounded_production_lists(logged_in_page):
    page = logged_in_page
    calls = _core_api_calls(page)

    page.goto("/core/executions/live")
    _wait(page)

    assert calls.count("hub/overview") == 1, calls
    assert "executions?status=in_progress&limit=100" in calls, calls
    assert "executions?status=pending&limit=100" in calls, calls
    assert not any(c == "executions" or (c.startswith("executions?") and "limit=" not in c) for c in calls), calls
    assert not any("include_steps=true" in c for c in calls), calls
    assert not any(c == "inventory" or c.startswith("inventory?") for c in calls), calls


def test_core_hub_stays_interactive_after_boosted_navigation_back(logged_in_page):
    """core2.html's scripts travel inside #page-content on a boosted response (base_spa.html) and
    htmx re-runs them on every visit. If they did not, the panels would never switch -- the page
    looks fine but nothing responds until a hard refresh -- and Overview would never (re)load.
    Bounce a few times and prove the panels still respond and the overview call fires."""
    page = logged_in_page
    page.goto("/core/dashboard")
    page.wait_for_selector("[data-dashboard-root]")
    _wait(page)
    calls = _core_api_calls(page)

    for i in range(3):
        page.locator('a.nav-link[href="/core"]').click()
        page.wait_for_selector('[data-core2-tab-panel="inventory"]', state="attached")
        # The hub's scripts run when the swap settles, a moment after its markup appears.
        for _ in range(100):
            if calls.count("hub/overview") >= i + 1:
                break
            page.wait_for_timeout(100)
        _wait(page)
        assert calls.count("hub/overview") == i + 1, ("overview not re-fetched on return", calls)

        _show(page, "inventory")
        _show(page, "overview")

        page.locator('a.nav-link[href="/core/dashboard"]').click()
        page.wait_for_selector("[data-dashboard-root]")
        _wait(page)


def test_flows2_defers_batches_and_inventory_until_their_tab_is_opened(logged_in_page):
    """flows2 first paint renders Structure only; Batches (execution list) and Inventory
    load the first time their tab is shown, and re-opening a tab is 0 fetches."""
    page = logged_in_page
    page.goto("/core")
    _wait(page)
    hdrs = {"X-CSRFToken": _csrf(page), "Content-Type": "application/json", "Referer": page.url}
    proc = page.request.post(
        "/api/core/processes", headers=hdrs, data='{"name": "Flows2 Lazy", "category": "manufacturing"}'
    )
    assert proc.status == 201, proc.text()
    pid = proc.json()["id"]
    page.request.post(f"/api/core/processes/{pid}/steps", headers=hdrs, data='{"step_number": 1, "name": "Mix"}')

    calls = _core_api_calls(page)
    page.goto(f"/core/flows?id={pid}")
    page.wait_for_selector('[data-flows2-target="batches"]')
    _wait(page)

    # first paint: a count for the badge, no execution list, no inventory list
    assert any(c.startswith("executions?") and "count=1" in c for c in calls), calls
    assert not any(c.startswith("executions?") and "count" not in c for c in calls), calls
    assert not any(c == "inventory" or c.startswith("inventory?") for c in calls), calls

    page.click('[data-flows2-target="batches"]')
    _wait(page)
    assert any(c.startswith("executions?") and "status=completed" in c for c in calls), calls

    page.click('[data-flows2-target="inventory"]')
    _wait(page)
    assert any(c.startswith("inventory?") and "process_id" in c for c in calls), calls

    # re-opening Batches: no new list fetch
    n_exec = sum(1 for c in calls if c.startswith("executions?") and "status=completed" in c)
    page.click('[data-flows2-target="overview"]') if page.locator('[data-flows2-target="overview"]').count() else None
    page.click('[data-flows2-target="batches"]')
    _wait(page)
    assert sum(1 for c in calls if c.startswith("executions?") and "status=completed" in c) == n_exec, calls


def _csrf(page):
    return page.evaluate("() => document.querySelector('meta[name=csrf-token]').content")
