"""Live-cogs 8.1e-2: cost on the pages people use, the Costs page, and the Home attention item.

Spec .agents/specs/live-cogs.md, "8.1e-2 build contract" (AC93-AC97).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.core.db.models.user import UserRole
from tests.costing_helpers import new_org, purge, user_client
from tests.test_compliant_routes import flask_app  # noqa: F401 -- fixture re-export
from tests.test_costing_allocations import _sync_purchase, world  # noqa: F401 -- fixture re-export

ROOT = Path(__file__).resolve().parents[1]
COST_PAGES = [
    "/core/inventory/view",
    "/core/inventory/add/manual",
    "/core/inventory/add/barcode",
    "/core/inventory/add/csv",
    "/core/executions/live",
]


def _content(html: str) -> str:
    start = html.find('id="page-content"')
    return html[start:] if start >= 0 else html


@pytest.mark.parametrize("path", COST_PAGES)
def test_cost_module_is_loaded_inside_page_content(flask_app, db, path):  # noqa: F811
    org = new_org(db)
    try:
        html = user_client(db, flask_app, org).get(path).get_data(as_text=True)
        assert "costing/cost-ui.js" in _content(html), "inside #page-content, so boosted visits load it"
    finally:
        purge(db, org)


def test_costs_page_for_viewers_only_and_in_the_nav(flask_app, db):  # noqa: F811
    org = new_org(db)
    try:
        viewer = user_client(db, flask_app, org, permissions=["costs.view", "production.view", "inventory.view"])
        page = viewer.get("/core/costing/costs")
        assert page.status_code == 200
        html = page.get_data(as_text=True)
        assert "data-costs-root" in html and "costing/costs.js" in _content(html)
        assert 'data-can-manage="false"' in html
        assert 'href="/core/costing/costs"' in viewer.get("/core/inventory/view").get_data(as_text=True)
        production = user_client(db, flask_app, org, role=UserRole.PRODUCTION)
        assert production.get("/core/costing/costs").status_code == 403
        assert 'href="/core/costing/costs"' not in production.get("/core/inventory/view").get_data(as_text=True)
    finally:
        purge(db, org)


def test_costs_page_hidden_without_the_feature(flask_app, db):  # noqa: F811
    org = new_org(db, grant=False)
    try:
        client = user_client(db, flask_app, org)
        assert client.get("/core/costing/costs").status_code == 404
        assert 'href="/core/costing/costs"' not in client.get("/core/inventory/view").get_data(as_text=True)
    finally:
        purge(db, org)


# --- AC95: Home attention item -----------------------------------------------------------------------------


def _attention(client):
    response = client.get("/api/core/attention")
    assert response.status_code == 200
    return {i["key"]: i for i in response.get_json()["items"]}


def _home_items(client):
    body = client.get("/api/core/dashboard/summary").get_json()
    return {i["key"]: i for i in body["action_board"]["items"]}


def test_ac95_purchases_to_record_on_home_and_notifications(flask_app, world, db):  # noqa: F811
    org = world["org"]
    _sync_purchase(world, db, "90")
    manager = user_client(db, flask_app, org)
    item = _attention(manager)["costing_purchases_to_record"]
    assert item["count"] == 1 and item["href"] == "/core/costing/purchases"
    assert item["detail"].startswith("Newest ")
    assert _home_items(manager)["costing_purchases_to_record"]["count"] == 1

    production = user_client(db, flask_app, org, role=UserRole.PRODUCTION)
    assert "costing_purchases_to_record" not in _attention(production)
    viewer = user_client(db, flask_app, org, permissions=["costs.view", "production.view"])
    assert "costing_purchases_to_record" not in _attention(viewer), "costs.manage only"


def test_ac95_hidden_at_zero(flask_app, world, db):  # noqa: F811
    manager = user_client(db, flask_app, world["org"])
    assert "costing_purchases_to_record" not in _attention(manager)


def test_ac95_absent_without_xero(flask_app, db):  # noqa: F811
    org = new_org(db)
    try:
        assert "costing_purchases_to_record" not in _attention(user_client(db, flask_app, org))
    finally:
        purge(db, org)


def test_ac95_a_failing_provider_never_breaks_the_page(flask_app, db, monkeypatch):  # noqa: F811
    from app.core import attention

    def broken(*_a):
        raise RuntimeError("boom")

    monkeypatch.setitem(attention._PROVIDERS, "test.broken", broken)
    org = new_org(db)
    try:
        client = user_client(db, flask_app, org)
        assert client.get("/api/core/attention").status_code == 200
        assert client.get("/api/core/dashboard/summary").status_code == 200
    finally:
        purge(db, org)


def test_ac95_core_holds_no_costing_check_id():
    for path in (
        "app/core/attention.py",
        "app/features/dashboard/routes/dashboard_routes.py",
        "app/core/frontend/js/feature-attention.js",
    ):
        assert "costing" not in (ROOT / path).read_text().lower(), path


# --- purchase rules page -----------------------------------------------------------------------------------


def test_rules_page_for_viewers_and_managers(flask_app, db):  # noqa: F811
    org = new_org(db)
    try:
        manager = user_client(db, flask_app, org)
        html = manager.get("/core/costing/rules").get_data(as_text=True)
        assert "data-rules-root" in html and "costing/rules.js" in _content(html)
        assert "data-rules-add>" in html
        viewer = user_client(db, flask_app, org, permissions=["costs.view", "production.view"])
        viewer_html = viewer.get("/core/costing/rules").get_data(as_text=True)
        assert 'data-can-manage="false"' in viewer_html and "data-rules-add>" not in viewer_html
        production = user_client(db, flask_app, org, role=UserRole.PRODUCTION)
        assert production.get("/core/costing/rules").status_code == 403
    finally:
        purge(db, org)


def test_rules_linked_from_settings_only_with_costing(flask_app, db):  # noqa: F811
    from app.core.db.repositories.feature_subscription_repo import FeatureSubscriptionRepository

    org = new_org(db)
    try:
        FeatureSubscriptionRepository(db).grant(org.id, "crm")
        db.commit()
        client = user_client(db, flask_app, org)
        assert 'href="/core/costing/rules"' in client.get("/crm/configuration").get_data(as_text=True)
        FeatureSubscriptionRepository(db).revoke(org.id, "costing")
        db.commit()
        assert 'href="/core/costing/rules"' not in client.get("/crm/configuration").get_data(as_text=True)
    finally:
        purge(db, org)
