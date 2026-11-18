"""``GET /api/core/mcp/me`` carries what bize_mcp needs to filter and audit: features and ids.

(8.2b made the endpoint; 8.2c adds ``features``, ``client_id`` and ``grant_id`` to it. All additive.)
"""

from __future__ import annotations

from app.core.db.repositories.feature_subscription_repo import FeatureSubscriptionRepository
from tests.mcp_oauth.support import bearer, mint_grant


def test_me_reports_the_organisations_features_and_the_grant_for_a_token(world):
    FeatureSubscriptionRepository(world.db).grant(world.org.id, "costing")
    world.db.commit()
    grant, access, _ = mint_grant(world.db, world.users["admin"], world.client_row)
    body = world.anon().get("/api/core/mcp/me", headers=bearer(access)).get_json()
    assert "costing" in body["features"] and "crm" in body["features"]
    assert "compliant" not in body["features"], "no compliance subscription"
    assert body["grant_id"] == str(grant.id)
    assert body["client_id"] == world.client_row.client_id
    assert body["auth"] == "mcp"


def test_me_for_a_session_has_no_grant(world):
    body = world.session("admin").get("/api/core/mcp/me").get_json()
    assert body["auth"] != "mcp"
    assert body["grant_id"] is None and body["client_id"] is None
    assert isinstance(body["features"], list)
