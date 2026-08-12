"""AC15/AC16/AC17: the mandatory cross-tenant probe for both dashboard routes.

AC15 gap (per the spec's "Notes for the audit"): the existing cross-tenant coverage for
`/api/core/dashboard/summary` -- `test_org_b_dashboard_summary_excludes_org_a_data` in
`tests/e2e/test_tenant_isolation.py` -- only asserts a single marker string is absent from
the raw response body. That is real signal, but it is also the weakest possible aggregate
check: a leak that reached the response through a differently-formatted field (a count, a
percentage, a rounded total) would not contain the literal marker string and would sail
straight through. `test_ac15_dashboard_summary_per_field_isolation` below is the per-field
twin `test_dashboard_operations_summary_org_isolated` already proves for the underlying
helper, but at the route level: it seeds org A across every dimension the summary
aggregates (inventory, execution, CRM task, audit-log event) and asserts each
corresponding field in org B's response is exactly zero/empty, not just marker-free.

AC16/AC17: `/api/core/metrics` had zero cross-tenant coverage at all before this file --
this is the mandatory probe `test_org_b_dashboard_summary_excludes_org_a_data` established
as the pattern for every aggregate endpoint in this slice.
"""

from __future__ import annotations

import datetime as dt
import uuid

import pytest

from tests.e2e.dashboard.conftest import create_crm_task, create_inventory_item, create_process, start_execution

pytestmark = pytest.mark.e2e

SUMMARY_URL = "/api/core/dashboard/summary"
METRICS_URL = "/api/core/metrics"


def test_ac15_dashboard_summary_per_field_isolation(two_tenants):
    page_a = two_tenants["a"]
    page_b = two_tenants["b"]
    marker = f"AC15 Isolation Marker {uuid.uuid4().hex[:8]}"

    # Baseline org B BEFORE org A acts: logging in itself emits a "user.login" EntityEvent
    # (auth_routes.py:597-605, actor_type defaults to "user"), so org B's own
    # operator_actions/audit_log are not zero even with no explicit action of its own --
    # comparing against this baseline (rather than assuming zero) is what makes the
    # assertions below a genuine leak check instead of an assumption about login's own
    # side effects.
    baseline_b = page_b.request.get(SUMMARY_URL).json()

    item_id = create_inventory_item(page_a, marker, untracked=True)
    process_id = create_process(page_a, marker)
    start_execution(page_a, process_id)
    create_crm_task(page_a, marker, due_date=(dt.date.today() - dt.timedelta(days=1)).isoformat())

    response_b = page_b.request.get(SUMMARY_URL)
    assert response_b.status == 200, response_b.text()
    body_b = response_b.json()

    # operations: org A's execution must not inflate org B's active count. org B truly has
    # no executions of its own, so this stays an exact zero rather than a baseline delta.
    assert body_b["operations"]["active_executions"] == 0, "org A's execution leaked into org B's operations"
    assert body_b["operations_today"]["active_executions"] == 0

    # operator_actions / audit_log: org A's inventory-create event must not appear, and
    # org B's own counts (from its login) must not have moved.
    assert body_b["operator_actions"]["week_to_date"] == baseline_b["operator_actions"]["week_to_date"], (
        "org A's operator action leaked into org B's count"
    )
    for period in ("day", "week"):
        bucket = body_b["audit_log"][period]
        baseline_bucket = baseline_b["audit_log"][period]
        assert bucket["total"] == baseline_bucket["total"], f"org A's event leaked into org B's audit_log.{period}"
        entity_ids_b = {i["entity_id"] for i in bucket["items"]}
        assert item_id not in entity_ids_b, f"org A's inventory item leaked into org B's audit_log.{period}"
        assert marker not in str(bucket["items"]), f"org A's marker leaked into org B's audit_log.{period}"

    # tasks: org A's CRM task must not be bucketed into org B's counts or top_tasks.
    tasks_b = body_b["tasks"]
    assert tasks_b["open_count"] == 0, f"org A's task leaked into org B's tasks: {tasks_b}"
    assert tasks_b["overdue_count"] == 0
    assert tasks_b["due_today_count"] == 0
    assert tasks_b["due_this_week_count"] == 0
    assert tasks_b["top_tasks"] == []

    # action_board: org A's untracked item and overdue task must not surface as org B
    # candidates -- with a fresh org B, the whole board must be empty.
    action_board_b = body_b["action_board"]
    assert action_board_b["items"] == [], f"org A's findings leaked into org B's action board: {action_board_b}"
    assert action_board_b["critical_actions_total"] == 0

    # compliance: org A's untracked item must not dock org B's score.
    compliance_b = body_b["compliance"]
    assert compliance_b["score"] == 100, f"org B's compliance score was docked by org A's data: {compliance_b}"
    assert compliance_b["top_drivers"] == []
    assert compliance_b["findings"]["untracked_items"]["count"] == 0

    # sales: org A has no revenue baseline here so this mainly guards against gross
    # cross-org aggregation bugs (e.g. summing across all orgs).
    sales_b = body_b["sales"]
    assert sales_b["current_month_revenue"] == 0 or sales_b["current_month_revenue"] == 0.0
    assert sales_b["outstanding_receivables"] == 0 or sales_b["outstanding_receivables"] == 0.0
    # NOTE: no real revenue is seeded for org A here (would require Xero-sandbox plumbing
    # this suite doesn't have -- see the spec's "Out of scope: CRMService... revenue
    # correctness"), so this only guards against gross cross-org summation bugs, not a
    # true revenue-leak probe. AC13's own null-baseline test is the closest existing
    # coverage for the revenue-baseline fields specifically.

    # insight_series: org B's six cumulative series must reflect only its own baseline
    # activity (from logging in), not any of org A's newly created process/execution/task.
    # A leak that summed org A's counts into org B's per-day totals would inflate the final
    # (most recent) cumulative point in one or more series without necessarily introducing
    # the marker string anywhere, since series points are just dates and numbers.
    series_b = body_b["insight_series"]
    baseline_series_b = baseline_b["insight_series"]
    for name in series_b:
        final_value = series_b[name]["points"][-1]["value"]
        baseline_final_value = baseline_series_b[name]["points"][-1]["value"]
        assert final_value == baseline_final_value, (
            f"org B's {name} series moved from {baseline_final_value} to {final_value} "
            f"after org A's activity -- org A's data leaked into org B's insight_series"
        )

    assert marker not in response_b.text(), "org A's marker leaked into org B's dashboard summary"

    # Sanity: org A itself sees its own data -- proves the probe would catch a real leak
    # rather than every field being an inert always-empty default.
    response_a = page_a.request.get(SUMMARY_URL)
    assert response_a.status == 200, response_a.text()
    body_a = response_a.json()
    assert body_a["operations"]["active_executions"] >= 1, "probe is inert: org A can't see its own execution"
    assert body_a["operator_actions"]["week_to_date"] >= 1, "probe is inert: org A can't see its own action"
    assert body_a["tasks"]["overdue_count"] >= 1, "probe is inert: org A can't see its own overdue task"
    assert body_a["compliance"]["score"] < 100, "probe is inert: org A's own untracked item didn't dock its score"
    assert marker in response_a.text(), "probe is inert: org A's own marker is missing from its own summary"
    assert body_a["insight_series"]["active_batches_week"]["points"][-1]["value"] >= 1, (
        "probe is inert: org A's own execution didn't move its own active_batches_week series"
    )


def test_ac16_ac17_metrics_cross_tenant_isolation(two_tenants):
    """Mirrors test_org_b_dashboard_summary_excludes_org_a_data (tests/e2e/test_tenant_isolation.py)
    for /api/core/metrics -- the mandatory cross-tenant probe this route never had.

    `operational_counters` (the process-wide, non-org-scoped counter dict security-audit.md
    finding F1 flagged as a real tenant-isolation leak) was removed by this same review --
    see test_metrics_api.py's well-formed-shape test for the regression guard on its
    absence. Nothing left in this response to exclude from the isolation check below.
    """
    page_a = two_tenants["a"]
    page_b = two_tenants["b"]
    marker = f"AC16 Isolation Marker {uuid.uuid4().hex[:8]}"

    process_id = create_process(page_a, marker)
    create_inventory_item(page_a, marker, inventory_type="raw_material")
    # An execution must exist on org A's side for active_executions/completed_executions
    # to be a real isolation check -- asserting org B reads 0 when org A also has 0 proves
    # nothing about leakage.
    start_execution(page_a, process_id)

    response_b = page_b.request.get(METRICS_URL)
    assert response_b.status == 200, response_b.text()
    body_b = response_b.json()

    assert body_b["total_processes"] == 0, f"org A's process leaked into org B's metrics: {body_b}"
    assert body_b["active_executions"] == 0, "org A's execution leaked into org B's active_executions"
    assert body_b["completed_executions"] == 0
    assert body_b["inventory_items"] == {
        "total": 0,
        "raw_materials": 0,
        "work_in_progress": 0,
        "final_products": 0,
    }, f"org A's inventory leaked into org B's metrics: {body_b['inventory_items']}"
    assert marker not in response_b.text(), "org A's marker leaked into org B's metrics response"

    # Sanity: org A can see its own data -- proves the probe is not just two empty orgs.
    response_a = page_a.request.get(METRICS_URL)
    assert response_a.status == 200, response_a.text()
    body_a = response_a.json()
    assert body_a["total_processes"] == 1, "probe is inert: org A can't see its own process"
    assert body_a["inventory_items"]["total"] == 1, "probe is inert: org A can't see its own inventory item"
    assert body_a["active_executions"] == 1, "probe is inert: org A can't see its own execution"
