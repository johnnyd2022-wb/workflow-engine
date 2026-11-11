"""Live-cogs 8.1d: the Purchases page is served, gated and in the Production nav.

Browser behaviour was driven through scripts/ui_shots.py scenarios (record, link, tabs, bulk,
phone, dark); these pin the server side.
"""

import pytest

from app.core.db.models.user import UserRole
from tests.costing_helpers import new_org, purge, user_client
from tests.test_compliant_routes import flask_app  # noqa: F401 -- fixture re-export

PAGE = "/core/costing/purchases"


@pytest.fixture
def org(db):
    o = new_org(db)
    yield o
    purge(db, o)


def test_page_renders_for_costs_view_with_its_script_inside_the_content(flask_app, org, db):  # noqa: F811
    client = user_client(db, flask_app, org)
    response = client.get(PAGE)
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "data-purchases-root" in html and 'data-can-manage="true"' in html
    content = html[html.index('id="page-content"') :]
    assert "costing/purchases.js" in content, "the script lives inside #page-content for boosted navigation"


def test_page_is_404_without_the_feature_and_403_without_permission(flask_app, org, db):  # noqa: F811
    from app.core.db.repositories.feature_subscription_repo import FeatureSubscriptionRepository

    production = user_client(db, flask_app, org, role=UserRole.PRODUCTION)
    assert production.get(PAGE).status_code == 403
    FeatureSubscriptionRepository(db).revoke(org.id, "costing")
    db.commit()
    assert user_client(db, flask_app, org).get(PAGE).status_code == 404


def test_view_only_user_sees_no_manage_actions(flask_app, org, db):  # noqa: F811
    viewer = user_client(db, flask_app, org, permissions=["costs.view", "inventory.view"])
    html = viewer.get(PAGE).get_data(as_text=True)
    assert 'data-can-manage="false"' in html and 'data-can-adjust="false"' in html


def test_nav_link_only_for_costing_orgs(flask_app, org, db):  # noqa: F811
    client = user_client(db, flask_app, org)
    assert 'href="/core/costing/purchases"' in client.get("/core/inventory/view").get_data(as_text=True)
    other = new_org(db, grant=False)
    try:
        plain = user_client(db, flask_app, other)
        assert 'href="/core/costing/purchases"' not in plain.get("/core/inventory/view").get_data(as_text=True)
    finally:
        purge(db, other)
