"""Route-level coverage for `GET /api/core/dashboard/summary`.

Per the spec's "Notes for the audit": this route had zero direct route-level tests before
this file -- `tests/test_dashboard_summary.py` only exercises four pure helper functions
in isolation, never the HTTP endpoint, and six more helpers
(`_dashboard_event_log_period`, `_dashboard_series_from_date_counts`,
`_dashboard_event_counts_by_day`, `_dashboard_execution_counts_by_day`,
`_dashboard_open_action_item_dates`, `_dashboard_operations_weekly_summary`) had no
integration-level coverage at all. Each test here seeds real data through the same APIs
the app's own UI uses, then asserts the aggregate response reflects it -- proving the
route -> repository -> aggregation chain, not just the aggregation math in isolation.

crm_enabled is true in local.ini (the E2E boot's config -- see test_crm_flow.py's header
note), so `tasks`/`sales` exercise the *enabled* shape here; AC5's *disabled* shape
(`crm_enabled=false`, or the CRM lookup raising) is not reachable through this suite
without monkeypatching config, which is unit-test territory -- flagged as a gap in the
report rather than faked with a route-level test that doesn't actually prove it.
"""

from __future__ import annotations

import datetime as dt

import pytest

from tests.e2e.dashboard.conftest import create_crm_task, create_inventory_item, start_execution
from tests.e2e.dashboard.conftest import create_process as _create_process

pytestmark = pytest.mark.e2e

SUMMARY_URL = "/api/core/dashboard/summary"

INSIGHT_SERIES_KEYS = {
    "operator_actions_week",
    "open_action_items",
    "active_batches_week",
    "batch_completion_week",
    "tasks_due_week",
    "revenue_goal_mtd",
}


def test_summary_requires_auth(page, app_url):
    response = page.request.get(SUMMARY_URL)
    assert response.status == 401, f"expected 401 for a logged-out request, got {response.status}"


def test_ac3_window_days_defaults_to_30_when_omitted(logged_in_page):
    response = logged_in_page.request.get(SUMMARY_URL)
    assert response.status == 200, response.text()
    assert response.json()["window_days"] == 30


@pytest.mark.parametrize("raw_value", ["abc", "12.5", "  "])
def test_ac3_window_days_rejects_non_integer(logged_in_page, raw_value):
    # params=, not string interpolation: an unencoded literal space in the URL gets
    # silently trimmed before it reaches the server, which made the whitespace-only case
    # indistinguishable from an absent parameter (window_days="" is a documented pass-through
    # to the default 30, per `(request.args.get("window_days") or "30")` -- not tested here
    # since it is the *presence-but-empty* case, not a non-integer one).
    response = logged_in_page.request.get(SUMMARY_URL, params={"window_days": raw_value})
    assert response.status == 400, f"expected 400 for window_days={raw_value!r}, got {response.status}"
    assert response.json() == {"error": "window_days must be an integer"}


def test_ac3_window_days_empty_string_falls_back_to_default(logged_in_page):
    """`window_days=""` is falsy, so `(request.args.get(...) or "30")` treats it as absent
    rather than as an empty non-integer -- documenting that pass-through explicitly rather
    than lumping it in with the rejection cases above."""
    response = logged_in_page.request.get(SUMMARY_URL, params={"window_days": ""})
    assert response.status == 200, response.text()
    assert response.json()["window_days"] == 30


@pytest.mark.parametrize("raw_value", ["6", "181", "0", "-5"])
def test_ac3_window_days_rejects_out_of_range(logged_in_page, raw_value):
    response = logged_in_page.request.get(SUMMARY_URL, params={"window_days": raw_value})
    assert response.status == 400, f"expected 400 for window_days={raw_value!r}, got {response.status}"
    assert response.json() == {"error": "window_days must be between 7 and 180"}


@pytest.mark.parametrize("boundary", ["7", "180"])
def test_ac3_window_days_accepts_boundary_values(logged_in_page, boundary):
    response = logged_in_page.request.get(SUMMARY_URL, params={"window_days": boundary})
    assert response.status == 200, response.text()
    assert response.json()["window_days"] == int(boundary)


def test_ac6_task_bucketing_reflected_in_summary_route(fresh_page):
    """AC6, at the HTTP layer rather than the pure-function layer
    `test_dashboard_task_bucketing_due_today_and_overdue` already covers.

    `top_tasks` is capped at 5, so this needs a genuinely fresh org (`fresh_page`) rather
    than the session-shared `logged_in_page` org -- otherwise unrelated tasks left by
    earlier tests in the same org could push these two out of the top 5 and the
    membership assertions below would flake."""
    today = dt.date.today()
    overdue_id = create_crm_task(fresh_page, "Overdue task", due_date=(today - dt.timedelta(days=2)).isoformat())
    today_id = create_crm_task(fresh_page, "Due today task", due_date=today.isoformat())

    response = fresh_page.request.get(SUMMARY_URL)
    assert response.status == 200, response.text()
    tasks = response.json()["tasks"]

    assert tasks["enabled"] is True
    assert tasks["overdue_count"] >= 1
    assert tasks["due_today_count"] >= 1
    top_task_ids = {t["id"] for t in tasks["top_tasks"]}
    assert overdue_id in top_task_ids, "the overdue task created by this test is missing from top_tasks"
    assert today_id in top_task_ids, "the due-today task created by this test is missing from top_tasks"


def test_ac7_ac8_compliance_summary_is_well_formed(logged_in_page):
    response = logged_in_page.request.get(SUMMARY_URL)
    assert response.status == 200, response.text()
    compliance = response.json()["compliance"]

    assert compliance["score_version"] == "v1"
    assert isinstance(compliance["score"], int)
    assert 0 <= compliance["score"] <= 100
    assert isinstance(compliance["top_drivers"], list)
    assert len(compliance["top_drivers"]) <= 3
    for driver in compliance["top_drivers"]:
        assert {"key", "label", "penalty"} <= driver.keys()
        assert driver["penalty"] > 0, "top_drivers must only list nonzero-penalty buckets"
    assert isinstance(compliance["state"], str) and compliance["state"]

    # findings.active_use_risk_count nests under compliance.findings, per
    # _dashboard_build_compliance_summary.
    findings = compliance["findings"]
    active_use_risk_count = findings.get("active_use_risk_count")
    assert isinstance(active_use_risk_count, int), f"active_use_risk_count missing or not an int: {findings}"
    assert active_use_risk_count >= 0


def test_ac7_ac8_compliance_score_reflects_real_untracked_item_finding(fresh_page):
    """The well-formed check above only proves shape -- a hard-coded score=100/state=
    'unknown'/top_drivers=[] response would pass it too. This proves the score is actually
    *computed* from `CoreChecksRunner` output: a fresh org (score must start at the
    formula's ceiling, 100, with no drivers) that then gets one untracked inventory item
    (the same fixture AC9's test uses to dock the action board) must see its score drop by
    exactly the untracked-items penalty (`min(25, 3 * count)` = 3 for one item, per
    `_dashboard_build_compliance_summary`) and `untracked_items` appear as a top driver."""
    baseline = fresh_page.request.get(SUMMARY_URL).json()["compliance"]
    assert baseline["score"] == 100, f"fresh org must start at a perfect score: {baseline}"
    assert baseline["top_drivers"] == []
    assert baseline["findings"]["untracked_items"]["count"] == 0

    create_inventory_item(fresh_page, "AC7/AC8 real finding widget", untracked=True)

    response = fresh_page.request.get(SUMMARY_URL)
    assert response.status == 200, response.text()
    compliance = response.json()["compliance"]

    assert compliance["score"] == 97, f"expected exactly a 3-point untracked-items penalty: {compliance}"
    assert compliance["findings"]["untracked_items"]["count"] == 1
    driver_keys = {d["key"] for d in compliance["top_drivers"]}
    assert "untracked_items" in driver_keys, f"untracked_items must surface as a top driver: {compliance}"


def test_ac9_action_board_reflects_untracked_item_and_overdue_task(logged_in_page):
    marker = "Dashboard AC9 Untracked Widget"
    create_inventory_item(logged_in_page, marker, untracked=True)
    create_crm_task(
        logged_in_page,
        "AC9 overdue task",
        due_date=(dt.date.today() - dt.timedelta(days=3)).isoformat(),
    )

    response = logged_in_page.request.get(SUMMARY_URL)
    assert response.status == 200, response.text()
    action_board = response.json()["action_board"]

    items_by_key = {item["key"]: item for item in action_board["items"]}
    assert "untracked_items" in items_by_key, f"untracked item not reflected in action board: {action_board}"
    assert items_by_key["untracked_items"]["count"] >= 1
    assert "overdue_tasks" in items_by_key, f"overdue task not reflected in action board: {action_board}"
    assert items_by_key["overdue_tasks"]["count"] >= 1

    non_informational_total = sum(
        item["count"] for item in action_board["items"] if item["severity"] != "informational"
    )
    assert action_board["critical_actions_total"] >= non_informational_total


def test_ac10_operations_counts_reflect_new_active_execution(fresh_page):
    process_id = _create_process(fresh_page, "AC10 dashboard process")
    start_execution(fresh_page, process_id)

    response = fresh_page.request.get(SUMMARY_URL)
    assert response.status == 200, response.text()
    body = response.json()

    # A real execution lands IN_PROGRESS immediately (see test_metrics_api.py's module
    # docstring), which is active under both PENDING+IN_PROGRESS definitions here. A
    # fresh org (fresh_page) makes this an exact count, not just >=1.
    assert body["operations"]["active_executions"] == 1
    assert body["operations_today"]["active_executions"] == 1
    assert body["operations"]["window"] == "week_to_date"
    assert body["operations"]["completed_vs_last_week_pct"] is None or isinstance(
        body["operations"]["completed_vs_last_week_pct"], (int, float)
    )


def test_ac11_operator_actions_week_to_date_counts_user_action(logged_in_page):
    before = logged_in_page.request.get(SUMMARY_URL).json()["operator_actions"]["week_to_date"]

    create_inventory_item(logged_in_page, "AC11 operator action widget")

    after = logged_in_page.request.get(SUMMARY_URL).json()["operator_actions"]["week_to_date"]
    assert after >= before + 1, "operator_actions.week_to_date did not increase after a real user-initiated action"


def test_ac12_audit_log_day_and_week_buckets_present(fresh_page):
    """A fresh org (fresh_page) so the seeded event is unambiguously within the last-10
    cap on each bucket, rather than relying on the session-shared org's recent-event
    ordering to keep it there."""
    marker = "AC12 Audit Log Widget"
    item_id = create_inventory_item(fresh_page, marker)

    response = fresh_page.request.get(SUMMARY_URL)
    assert response.status == 200, response.text()
    audit_log = response.json()["audit_log"]

    assert audit_log["limit"] == 10
    for period in ("day", "week"):
        bucket = audit_log[period]
        assert "total" in bucket and "items" in bucket
        assert len(bucket["items"]) <= 10
        entity_ids = {i["entity_id"] for i in bucket["items"]}
        assert item_id in entity_ids, f"seeded event missing from audit_log.{period}: {bucket}"
        matching = next(i for i in bucket["items"] if i["entity_id"] == item_id)
        assert matching["event_type"]
        assert matching["summary"]
        assert matching["actor"]


def test_ac13_sales_enabled_with_null_baseline_for_fresh_org(fresh_page):
    """A genuinely fresh org (fresh_page, not the session-shared logged_in_page) has no
    `revenue_baseline_target_mtd` configured, so all three baseline fields must be null
    while the raw revenue figures stay numeric -- AC13's "else all three are null"
    branch."""
    response = fresh_page.request.get(SUMMARY_URL)
    assert response.status == 200, response.text()
    sales = response.json()["sales"]

    assert sales["enabled"] is True, "crm_enabled=true locally; sales must use the enabled shape"
    assert sales["baseline_target_mtd"] is None
    assert sales["baseline_variance_mtd"] is None
    assert sales["baseline_attainment_pct"] is None
    assert isinstance(sales["current_month_revenue"], (int, float))
    assert isinstance(sales["outstanding_receivables"], (int, float))


def test_ac14_insight_series_present_for_all_six_series(logged_in_page):
    response = logged_in_page.request.get(SUMMARY_URL)
    assert response.status == 200, response.text()
    series = response.json()["insight_series"]

    assert set(series.keys()) == INSIGHT_SERIES_KEYS
    for name, s in series.items():
        assert s["points"], f"{name} series has no points even in the documented empty-state fallback: {s}"
        for point in s["points"]:
            assert "date" in point and "value" in point
