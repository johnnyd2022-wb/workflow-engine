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


def test_core_tabs_follow_browser_back_and_forward_without_reloading_data(logged_in_page):
    """A tab is a navigable Core view, not a state change the browser loses.

    The initial load remains compact; moving Back/Forward between already-opened tabs
    only switches panels and must reuse their cached data.
    """
    page = logged_in_page
    calls = _core_api_calls(page)

    page.goto("/core")
    _wait(page)
    page.click('[data-core2-tab-target="inventory"]')
    page.wait_for_function(
        "() => { const e = document.querySelector('[data-core2-tab-panel=\"inventory\"]'); return e && !e.hidden; }"
    )
    assert "tab=inventory" in page.url

    page.click('[data-core2-tab-target="workflows"]')
    page.wait_for_function(
        "() => { const e = document.querySelector('[data-core2-tab-panel=\"workflows\"]'); return e && !e.hidden; }"
    )
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
    assert sum(1 for c in calls if c == "inventory" or c.startswith("inventory?")) == 1, calls
    assert sum(1 for c in calls if c == "executions" or c.startswith("executions?")) == 1, calls


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


def test_executions_live_reuses_hub_overview_no_heavy_lists(logged_in_page):
    page = logged_in_page
    calls = _core_api_calls(page)

    page.goto("/core/executions/live")
    _wait(page)

    assert calls.count("hub/overview") == 1, calls
    assert not any(c == "executions" or c.startswith("executions?") for c in calls), calls
    assert not any("include_steps=true" in c for c in calls), calls
    assert not any(c == "inventory" or c.startswith("inventory?") for c in calls), calls


def test_core_hub_stays_interactive_after_boosted_navigation_back(logged_in_page):
    """core2.html's scripts live in the template's scripts block, outside #page-content,
    so an hx-boost return to /core swaps in fresh markup they never re-touch. Without the
    htmx:afterSettle re-bootstrap the tab buttons have no handlers -- the page looks fine
    but every click is dead until a hard refresh -- and Overview never (re)loads. Bounce a
    few times and prove the tabs still respond and the overview call still fires."""
    page = logged_in_page
    page.goto("/core/dashboard")
    page.wait_for_selector("[data-dashboard-root]")
    _wait(page)
    calls = _core_api_calls(page)

    for i in range(3):
        page.locator('a.nav-link[href="/core"]').click()
        page.wait_for_selector('[data-core2-tab-target="inventory"]')
        _wait(page)
        assert calls.count("hub/overview") == i + 1, ("overview not re-fetched on return", calls)

        page.click('[data-core2-tab-target="inventory"]')
        page.wait_for_function(
            "() => { const e = document.querySelector('[data-core2-tab-panel=\"inventory\"]'); return e && !e.hidden; }"
        )
        page.click('[data-core2-tab-target="overview"]')
        page.wait_for_function(
            "() => { const e = document.querySelector('[data-core2-tab-panel=\"overview\"]'); return e && !e.hidden; }"
        )

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
