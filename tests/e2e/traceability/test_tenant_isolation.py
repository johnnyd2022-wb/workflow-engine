"""The mandatory cross-tenant probe for the sourcemap/trace surface (AC2/AC6/AC9).

Companion to `tests/e2e/test_tenant_isolation.py` -- same shape (two real authenticated
browser sessions, org B reaching for org A's ids), scoped to the traceability slice's own
routes. Every probe goes through `page.request` on an already-logged-in page, i.e. the
real browser session's cookies -- not a bypass.
"""

from datetime import UTC, datetime, timedelta

import pytest

from tests.e2e.conftest import csrf_headers

pytestmark = pytest.mark.e2e


def test_ac2_forward_trace_cross_tenant_existence_not_distinguishable(two_tenants_with_chains):
    """AC2: a UUID belonging to another org's item must 404 exactly like a nonexistent one --
    org B must not be able to tell "not mine" apart from "doesn't exist"."""
    page_b = two_tenants_with_chains["b"]["page"]
    org_a_r1_id = two_tenants_with_chains["a"]["dag"]["r1_id"]

    resp = page_b.request.get(f"/api/core/inventory/trace/{org_a_r1_id}")
    assert resp.status == 404, f"org B traced org A's raw material: {resp.status} {resp.text()}"
    assert resp.json()["error"] == "Raw material not found"
    assert "R1" not in resp.text(), "org A's item name leaked into the 404 body"


def test_ac6_backward_trace_cross_tenant_returns_404(two_tenants_with_chains):
    """AC6: same UUID-validation and cross-tenant-404 guarantee as AC2, for the backward
    trace endpoint (any item, not just raw materials)."""
    page_b = two_tenants_with_chains["b"]["page"]
    org_a_w1_id = two_tenants_with_chains["a"]["dag"]["w1_id"]

    resp = page_b.request.get(f"/api/core/inventory/trace-backward/{org_a_w1_id}")
    assert resp.status == 404, f"org B traced org A's WIP item: {resp.status} {resp.text()}"
    assert resp.json()["error"] == "Inventory item not found"
    assert "W1" not in resp.text(), "org A's item name leaked into the 404 body"


def test_ac6_backward_trace_cross_tenant_final_product_returns_404(two_tenants_with_chains):
    page_b = two_tenants_with_chains["b"]["page"]
    org_a_f1_id = two_tenants_with_chains["a"]["dag"]["f1_id"]

    resp = page_b.request.get(f"/api/core/inventory/trace-backward/{org_a_f1_id}")
    assert resp.status == 404
    assert resp.json()["error"] == "Inventory item not found"


def test_ac9_temporal_trace_root_state_not_visible_cross_tenant(two_tenants_with_chains):
    """AC9: TemporalDAGTracer._snapshot_at now filters EntityEvent by org_id, so
    POST /api/core/sourcemap/trace's temporal branch no longer returns another org's root
    item state when given that org's item id as root_id (was: leaked name/quantity/supplier
    via body["root"]["state"]; fixed in app/core/backend/temporal_dag_tracer.py:121-134)."""
    page_b = two_tenants_with_chains["b"]["page"]
    org_a_r1_id = two_tenants_with_chains["a"]["dag"]["r1_id"]

    as_of = (datetime.now(UTC) + timedelta(minutes=5)).isoformat()
    resp = page_b.request.post(
        "/api/core/sourcemap/trace",
        headers=csrf_headers(page_b),
        data={"root_type": "inventory_item", "root_id": str(org_a_r1_id), "as_of": as_of, "depth": 3},
    )
    assert resp.status == 200, resp.text()
    body = resp.json()
    assert body["root"].get("state") is None, (
        f"org B received org A's item state via the temporal trace root: {body['root'].get('state')}"
    )
