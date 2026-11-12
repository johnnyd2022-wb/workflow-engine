"""Sales › Margins page (live-cogs 8.1f-2)."""

from __future__ import annotations

from app.core.db.models.user import UserRole
from app.core.db.repositories.feature_subscription_repo import FeatureSubscriptionRepository
from tests.costing_helpers import new_org, purge, user_client
from tests.test_compliant_routes import flask_app  # noqa: F401 -- fixture re-export

PAGE = "/core/costing/margins"


def _content(html: str) -> str:
    start = html.find('id="page-content"')
    return html[start:] if start >= 0 else html


def test_margins_page_renders_in_sales_for_cost_and_sales_viewers(flask_app, db):  # noqa: F811
    org = new_org(db)
    try:
        FeatureSubscriptionRepository(db).grant(org.id, "crm")
        db.commit()
        client = user_client(db, flask_app, org)
        html = client.get(PAGE).get_data(as_text=True)
        assert "data-margins-root" in html and "costing/margins.js" in _content(html)
        assert f'href="{PAGE}"' in client.get("/crm/analytics").get_data(as_text=True), "a Sales tab"
        only_costs = user_client(db, flask_app, org, permissions=["costs.view"])
        assert only_costs.get(PAGE).status_code == 403
        assert user_client(db, flask_app, org, role=UserRole.PRODUCTION).get(PAGE).status_code == 403
    finally:
        purge(db, org)


def test_margins_page_absent_without_costing(flask_app, db):  # noqa: F811
    org = new_org(db, grant=False)
    try:
        FeatureSubscriptionRepository(db).grant(org.id, "crm")
        db.commit()
        client = user_client(db, flask_app, org)
        assert client.get(PAGE).status_code == 404
        assert f'href="{PAGE}"' not in client.get("/crm/analytics").get_data(as_text=True)
    finally:
        purge(db, org)
