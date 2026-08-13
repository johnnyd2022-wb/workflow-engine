"""AC16/AC17: `GET /api/core/metrics`.

Per the spec's "Notes for the audit", this route had ZERO test coverage anywhere before
this file -- not in `tests/test_dashboard_summary.py`, not in `tests/test_multi_tenant_api.py`,
not in `tests/test_multi_tenant_isolation.py`, not in any e2e suite -- despite being a
live, auth-gated, tenant-scoped production API. The cross-tenant isolation half of AC17
lives in `tests/e2e/dashboard/test_tenant_isolation.py` (the mandatory probe, mirroring
`test_org_b_dashboard_summary_excludes_org_a_data`); this file covers AC16's route-level
correctness.

AC16 documents this route's `active_executions` as counting ExecutionStatus.IN_PROGRESS
only, versus `/api/core/dashboard/summary`'s PENDING+IN_PROGRESS. That distinction could
not be reproduced with a live PENDING execution: `ExecutionRepository.create_execution`
(app/core/db/repositories/execution_repo.py:79-119) briefly constructs the row with
`status=ExecutionStatus.PENDING` but reassigns it to `ExecutionStatus.IN_PROGRESS` before
the transaction commits, on every execution, every time -- so `POST /api/core/executions`
never actually leaves an execution observably PENDING through the real API. Flagged in the
report rather than tested with a mock/direct-DB row that would prove the query filter
works but not that the divergence is reachable in practice.
"""

from __future__ import annotations

import pytest

from tests.e2e.dashboard.conftest import create_inventory_item, create_process, start_execution

pytestmark = pytest.mark.e2e

METRICS_URL = "/api/core/metrics"


def test_metrics_requires_auth(page, app_url):
    response = page.request.get(METRICS_URL)
    assert response.status == 401, f"expected 401 for a logged-out request, got {response.status}"


def test_ac16_metrics_returns_well_formed_shape_for_fresh_org(fresh_page):
    response = fresh_page.request.get(METRICS_URL)
    assert response.status == 200, response.text()
    body = response.json()

    assert body["total_processes"] == 0
    assert body["active_executions"] == 0
    assert body["completed_executions"] == 0
    assert body["inventory_items"] == {
        "total": 0,
        "raw_materials": 0,
        "work_in_progress": 0,
        "final_products": 0,
    }
    # `operational_counters` was removed by this review (security-audit.md finding F1): it
    # was a process-wide, non-org-scoped counter dict leaking across every tenant sharing
    # the worker, with no consumer in the frontend. Asserting its absence here, not just
    # omitting the old assertions, so a regression that re-adds it gets caught.
    assert "operational_counters" not in body


def test_ac16_metrics_total_processes_reflects_created_process(fresh_page):
    create_process(fresh_page, "AC16 metrics process")

    response = fresh_page.request.get(METRICS_URL)
    assert response.status == 200, response.text()
    assert response.json()["total_processes"] == 1


def test_ac16_metrics_inventory_breakdown_by_type(fresh_page):
    create_inventory_item(fresh_page, "AC16 raw material", inventory_type="raw_material")
    create_inventory_item(fresh_page, "AC16 wip item", inventory_type="work_in_progress")
    create_inventory_item(fresh_page, "AC16 final product", inventory_type="final_product")

    response = fresh_page.request.get(METRICS_URL)
    assert response.status == 200, response.text()
    items = response.json()["inventory_items"]

    assert items["total"] == 3
    assert items["raw_materials"] == 1
    assert items["work_in_progress"] == 1
    assert items["final_products"] == 1


def test_ac16_metrics_active_executions_counts_real_in_progress_execution(fresh_page):
    """A real execution lands IN_PROGRESS immediately (see the module docstring), so this
    proves the IN_PROGRESS-only filter actually counts a genuine row -- both endpoints
    agree it is active, since IN_PROGRESS is active under either definition."""
    process_id = create_process(fresh_page, "AC16 metrics active-executions process")
    start_execution(fresh_page, process_id)

    metrics = fresh_page.request.get(METRICS_URL)
    assert metrics.status == 200, metrics.text()
    assert metrics.json()["active_executions"] == 1

    summary = fresh_page.request.get("/api/core/dashboard/summary")
    assert summary.status == 200, summary.text()
    assert summary.json()["operations"]["active_executions"] == 1
