"""The mandatory cross-tenant probe for the activity-log routes (AC3, AC7, AC11).

Same shape as tests/e2e/traceability/test_tenant_isolation.py and
tests/e2e/test_tenant_isolation.py: two real authenticated browser sessions, org B
reaching for org A's ids, through `page.request` on an already-logged-in page -- the real
session's cookies, not a bypass.

AC7 is the headline: `entity_summary_detail` leaked another org's pre-computed summary
(including user PII / org metadata, not just inventory data) before this review's fix --
see .agents/reports/activity-log/security-audit.md F1. The unit-level regression coverage
(tests/test_activity_log.py::TestAC7CrossTenantSummaryLeak) already proves this against
`app_client`; this is the browser-session twin, proving the same fix holds behind the real
cookie/session/CSRF stack an attacker would actually have to go through.
"""

import pytest

from tests.e2e.activity_log.conftest import create_inventory_item

pytestmark = pytest.mark.e2e


def test_ac7_entity_summary_not_visible_cross_tenant(logged_in_two_orgs):
    page_a = logged_in_two_orgs["a"]["page"]
    page_b = logged_in_two_orgs["b"]["page"]
    item_id = create_inventory_item(page_a, name="Org A Secret Widget", quantity="9", unit="kg")

    resp = page_b.request.get(f"/api/core/entities/inventory_item/{item_id}/summary")
    assert resp.status == 200, resp.text()
    body = resp.json()
    assert body["summary"] == {}, f"org B received org A's inventory summary: {body['summary']}"
    assert body["recent_events"] == []
    assert "Org A Secret Widget" not in resp.text()


def test_ac3_entity_story_not_visible_cross_tenant(logged_in_two_orgs):
    page_a = logged_in_two_orgs["a"]["page"]
    page_b = logged_in_two_orgs["b"]["page"]
    item_id = create_inventory_item(page_a, name="Org A Story Widget", quantity="2", unit="kg")

    resp = page_b.request.get(f"/api/core/entities/inventory_item/{item_id}/story")
    assert resp.status == 200, resp.text()
    body = resp.json()
    assert body["events"] == [], "org B must not see org A's event timeline"
    assert body["total"] == 0
    assert "Org A Story Widget" not in resp.text()


def test_ac11_activity_feed_excludes_other_orgs_events(logged_in_two_orgs):
    page_a = logged_in_two_orgs["a"]["page"]
    page_b = logged_in_two_orgs["b"]["page"]
    item_id = create_inventory_item(page_a, name="Org A Activity Widget", quantity="3", unit="kg")

    resp = page_b.request.get("/api/core/entities/activity?limit=500")
    assert resp.status == 200, resp.text()
    seen_ids = {e["entity_id"] for e in resp.json()["events"]}
    assert item_id not in seen_ids, "org B's activity feed must never include org A's events"
