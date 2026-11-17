"""AC11-AC21: the bearer path in the app and the read-only rule."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.core.db.models.org_role import OrgRole
from app.core.db.models.user import User, UserRole
from app.core.security.access_policy import DENY, PUBLIC, SIGNED_IN, requirement_for
from app.core.security.auth_service import AuthService
from app.features.mcp_oauth.models import McpOrgSettings, OAuthGrant, OAuthToken
from app.features.mcp_oauth.services import rate_limit
from tests.mcp_oauth.support import bearer, mint_grant, unique_addr

FIXED_UUID = "00000000-0000-4000-8000-000000000000"  # stable test ids: xdist workers must collect identically
WWW_INVALID = 'Bearer error="invalid_token"'


def _token_for(world, who="member"):
    grant, access, refresh = mint_grant(world.db, world.users[who], world.client_row)
    return grant, access, refresh


def _get(world, path, access, **kwargs):
    return world.anon().get(path, headers=bearer(access), **kwargs)


# --- AC11 ---------------------------------------------------------------------------------------


def test_ac11_a_read_token_on_get_inventory_returns_what_the_session_api_returns(world):
    _g, access, _r = _token_for(world, "member")
    via_token = _get(world, "/api/core/inventory", access)
    via_session = world.session("member").get("/api/core/inventory")
    assert via_token.status_code == 200, via_token.get_data(as_text=True)[:300]
    assert via_session.status_code == 200
    assert via_token.get_json() == via_session.get_json()
    assert "Org A Juniper" in via_token.get_data(as_text=True)
    # A bearer request neither sets a cookie nor starts a session.
    assert "Set-Cookie" not in via_token.headers


def test_ac11_the_token_user_and_org_drive_the_response(world):
    _g, access, _r = _token_for(world, "sales")
    resp = _get(world, "/auth/me", access)
    assert resp.status_code == 200
    assert resp.get_json()["user"]["email"] == world.users["sales"].email


@pytest.mark.parametrize("who", ["admin", "member", "production", "compliance", "sales", "auditor"])
def test_ac11_a_token_reaches_exactly_what_its_roles_session_reaches_on_reads(world, who):
    _g, access, _r = _token_for(world, who)
    session = world.session(who)
    # Routes in the MCP catalogue (x-bize.mcp): outside it a token is out of scope (design review S1).
    for path in ("/api/core/inventory", "/api/core/processes", "/api/core/executions", "/api/crm/invoices"):
        want = session.get(path).status_code
        got = _get(world, path, access).status_code
        assert got == want, (who, path, got, want)


# --- AC12 ---------------------------------------------------------------------------------------


def _non_get_routes():
    import app.app as app_module
    from app.api.middleware.tenant_context import PUBLIC_ENDPOINTS

    routes = []
    for rule in sorted(app_module.app.url_map.iter_rules(), key=lambda r: (r.rule, r.endpoint)):
        for method in sorted(rule.methods - {"GET", "HEAD", "OPTIONS"}):
            if requirement_for(rule.endpoint, method) == PUBLIC or rule.endpoint in PUBLIC_ENDPOINTS:
                # Public endpoints stay public, and the anonymous ones (sign-in, telemetry, the
                # OAuth endpoints) never read a bearer token at all: the rule narrows signed-in routes.
                continue
            values = {}
            for arg in rule.arguments:
                kind = type(rule._converters[arg]).__name__
                values[arg] = FIXED_UUID if kind == "UUIDConverter" else (1 if kind == "IntegerConverter" else "x")
            routes.append(
                (
                    rule.endpoint,
                    method,
                    app_module.app.url_map.bind("localhost").build(rule.endpoint, values, method=method),
                )
            )
    return routes


NON_GET_ROUTES = _non_get_routes()


def _full_app_client():
    """A cookie-less client on the top-level app, which also serves /, /dashboard and /initialize
    (create_app() alone does not), so the walk over the URL map reaches every route it lists."""
    import app.app as app_module

    client = app_module.app.test_client()
    client.environ_base["wsgi.url_scheme"] = "https"
    client.environ_base["HTTP_X_FORWARDED_PROTO"] = "https"
    client.environ_base["REMOTE_ADDR"] = unique_addr()
    return client


@pytest.fixture
def admin_token_without_rate_limit(world, monkeypatch):
    monkeypatch.setattr(rate_limit, "BEARER_REQUESTS_PER_MINUTE", 10_000_000)
    return _token_for(world, "admin")[1]


def test_ac12_the_parametrised_set_covers_every_signed_in_non_get_route():
    assert len(NON_GET_ROUTES) > 100
    assert ("core.create_inventory_item", "POST", "/api/core/inventory") in NON_GET_ROUTES


@pytest.mark.parametrize("endpoint,method,url", NON_GET_ROUTES, ids=[f"{m} {u}" for _e, m, u in NON_GET_ROUTES])
def test_ac12_a_read_token_on_any_write_route_is_403_insufficient_scope(
    world, admin_token_without_rate_limit, endpoint, method, url
):
    resp = _full_app_client().open(url, method=method, json={}, headers=bearer(admin_token_without_rate_limit))
    assert resp.status_code == 403, (endpoint, resp.status_code)
    assert resp.get_json()["error"] == "insufficient_scope"
    assert resp.headers["WWW-Authenticate"] == 'Bearer error="insufficient_scope", scope="bize.read"'


def test_ac12_the_denial_comes_before_the_route_runs(world):
    _g, access, _r = _token_for(world, "admin")
    before = world.db.query(type(world.item)).filter_by(org_id=world.org.id).count()
    resp = world.anon().post(
        "/api/core/inventory",
        json={"name": "Smuggled", "quantity": 5, "unit": "kg", "inventory_type": "raw_material"},
        headers=bearer(access),
    )
    assert resp.status_code == 403
    world.db.expire_all()
    assert world.db.query(type(world.item)).filter_by(org_id=world.org.id).count() == before


@pytest.mark.parametrize("method", ["PUT", "PATCH", "DELETE", "POST"])
def test_ac12_every_write_method_on_a_stock_item_is_refused(world, method):
    _g, access, _r = _token_for(world, "admin")
    resp = world.anon().open(f"/api/core/inventory/{world.item.id}", method=method, json={}, headers=bearer(access))
    assert resp.status_code in {403, 405}
    if resp.status_code == 403:
        assert resp.get_json()["error"] == "insufficient_scope"


def test_ac12_options_is_not_a_read(world):
    _g, access, _r = _token_for(world, "admin")
    resp = world.anon().open("/api/core/inventory", method="OPTIONS", headers=bearer(access))
    assert resp.status_code == 403


# --- AC13 ---------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "path",
    [
        "/org/users",  # users.manage
        "/api/core/mcp/settings",  # users.manage
        "/api/core/mcp/grants",  # signed-in only
        "/api/core/dashboard/summary",  # signed-in only
        "/core/dashboard",
    ],
)
def test_ac13_a_read_token_on_a_get_route_outside_the_read_permissions_is_403_even_for_an_admin(world, path):
    _g, access, _r = _token_for(world, "admin")
    resp = _get(world, path, access)
    assert resp.status_code == 403, path
    assert resp.get_json()["error"] == "insufficient_scope"


def _get_routes_without_arguments():
    import app.app as app_module

    return sorted(
        {
            (rule.endpoint, rule.rule)
            for rule in app_module.app.url_map.iter_rules()
            if "GET" in rule.methods and not rule.arguments
        }
    )


def test_ac13_every_get_route_without_a_read_permission_is_refused_for_an_admin_token(world, monkeypatch):
    """Walk the live URL map: where the policy names no view permission, or the route is not in the
    MCP catalogue (design review S1), and the route is not public or the token's own identity, an
    admin's read token gets 403 insufficient_scope."""
    from app.core.security.access_policy import MCP_TOKEN_ENDPOINTS, READ_PERMISSIONS, in_mcp_catalogue

    monkeypatch.setattr(rate_limit, "BEARER_REQUESTS_PER_MINUTE", 10_000_000)
    _g, access, _r = _token_for(world, "admin")
    client = _full_app_client()
    refused = 0
    wrong = []
    for endpoint, url in _get_routes_without_arguments():  # no arguments, so the URL is the rule
        requirement = requirement_for(endpoint, "GET")
        if requirement == PUBLIC or endpoint in MCP_TOKEN_ENDPOINTS:
            continue
        required = set(requirement if isinstance(requirement, tuple) else (requirement,))
        resp = client.get(url, headers=bearer(access))
        if not (required & READ_PERMISSIONS and in_mcp_catalogue(world.app, endpoint, url, "GET")):
            refused += 1
            if resp.status_code != 403 or (resp.get_json(silent=True) or {}).get("error") != "insufficient_scope":
                wrong.append((endpoint, url, resp.status_code))
        elif resp.status_code == 403 and (resp.get_json(silent=True) or {}).get("error") == "insufficient_scope":
            wrong.append((endpoint, url, "read permission refused as out of scope"))
    assert refused > 30
    assert wrong == []


def test_ac13_the_read_permission_set_is_exactly_the_five_view_permissions():
    from app.core.security.access_policy import READ_PERMISSIONS

    assert READ_PERMISSIONS == {"production.view", "inventory.view", "sales.view", "compliance.view", "costs.view"}


def test_ac13_data_export_download_is_403_for_a_token(world):
    _g, access, _r = _token_for(world, "admin")
    import app.app as app_module

    urls = [
        rule.rule
        for rule in app_module.app.url_map.iter_rules()
        if rule.endpoint.startswith("data_export.") and "GET" in rule.methods and not rule.arguments
    ]
    assert urls
    for url in urls:
        resp = _get(world, url, access)
        assert resp.status_code == 403, url
        assert resp.get_json()["error"] == "insufficient_scope"


# --- AC14 ---------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "who,path",
    [
        # Catalogue routes (x-bize.mcp), so the refusal is the role's, not the scope's.
        ("sales", "/api/core/costing/margins"),  # costs.view: sales has none
        ("sales", "/api/core/processes"),  # production.view
        ("sales", "/api/core/executions"),
        ("production", "/api/crm/invoices"),  # sales.view
        ("auditor", "/api/core/costing/margins"),
    ],
)
def test_ac14_a_token_on_a_read_route_its_role_lacks_is_403(world, who, path):
    _g, access, _r = _token_for(world, who)
    resp = _get(world, path, access)
    assert resp.status_code == 403, (who, path)
    body = resp.get_json()
    assert body.get("code") == "permission_denied"


def test_ac14_a_custom_roles_permissions_bound_the_token(world, db):
    role = OrgRole(org_id=world.org.id, name="Stock only", base_role="member", permissions=["inventory.view"])
    db.add(role)
    db.commit()
    user = world.add_user(UserRole.MEMBER)
    db.get(User, user.id).custom_role_id = role.id
    db.commit()
    world.enable(roles=["admin"], extra_keys=[f"custom:{role.id}"])
    _g, access, _r = mint_grant(db, user, world.client_row)
    assert _get(world, "/api/core/inventory", access).status_code == 200
    assert _get(world, "/api/core/processes", access).status_code == 403
    assert _get(world, "/api/crm/customers", access).status_code == 403


# --- AC15 ---------------------------------------------------------------------------------------


def test_ac15_org_as_token_asking_for_org_bs_lot_is_404_and_org_b_data_is_in_no_list(world):
    _g, access, _r = _token_for(world, "admin")
    own = _get(world, f"/api/core/inventory/trace-backward/{world.item.id}", access)
    assert own.status_code == 200
    foreign = _get(world, f"/api/core/inventory/trace-backward/{world.other_item.id}", access)
    assert foreign.status_code == 404
    listing = _get(world, "/api/core/inventory", access).get_data(as_text=True)
    assert "Org B Secret Botanical" not in listing
    assert str(world.other_item.id) not in listing
    graph = _get(world, f"/api/core/inventory/trace-graph/{world.other_item.id}", access)
    assert graph.status_code == 404


def test_ac15_a_grant_never_opens_another_orgs_data_even_when_the_other_org_enables_mcp(world, db):
    other = McpOrgSettings(org_id=world.other_org.id, enabled=True)
    db.add(other)
    db.commit()
    _g, access, _r = _token_for(world, "admin")
    resp = _get(world, "/api/core/inventory", access)
    assert "Org B Secret Botanical" not in resp.get_data(as_text=True)


# --- AC16 ---------------------------------------------------------------------------------------


def test_ac16_turning_the_org_off_blocks_the_next_request_and_turning_it_on_restores_it(world):
    _g, access, _r = _token_for(world, "member")
    assert _get(world, "/api/core/inventory", access).status_code == 200
    world.enable(enabled=False)
    off = _get(world, "/api/core/inventory", access)
    assert off.status_code == 403
    assert off.get_json() == {"error": "mcp_not_allowed"}
    world.enable(enabled=True)
    assert _get(world, "/api/core/inventory", access).status_code == 200  # same token


def test_ac16_the_off_state_does_not_revoke_the_grant(world, db):
    grant, access, _r = _token_for(world, "member")
    world.enable(enabled=False)
    _get(world, "/api/core/inventory", access)
    db.expire_all()
    assert db.get(OAuthGrant, grant.id).revoked_at is None


def test_ac16_unticking_the_users_role_blocks_and_ticking_it_restores(world):
    _g, access, _r = _token_for(world, "sales")
    assert _get(world, "/api/core/inventory", access).status_code == 200
    world.enable(roles=["admin", "member", "production", "compliance", "auditor"])
    blocked = _get(world, "/api/core/inventory", access)
    assert blocked.status_code == 403
    assert blocked.get_json() == {"error": "mcp_not_allowed"}
    world.enable()
    assert _get(world, "/api/core/inventory", access).status_code == 200


def test_ac16_changing_the_users_role_applies_at_once(world, db):
    _g, access, _r = _token_for(world, "sales")
    world.enable(roles=["admin", "sales"])
    assert _get(world, "/api/core/inventory", access).status_code == 200
    db.get(User, world.users["sales"].id).role = UserRole.AUDITOR
    db.commit()
    assert _get(world, "/api/core/inventory", access).status_code == 403


def test_ac16_an_org_with_no_settings_row_is_off(world, db):
    db.query(McpOrgSettings).filter_by(org_id=world.org.id).delete()
    db.commit()
    _g, access, _r = _token_for(world, "admin")
    assert _get(world, "/api/core/inventory", access).status_code == 403


# --- AC17 ---------------------------------------------------------------------------------------


def test_ac17_a_password_change_revokes_the_users_grants(world, db):
    user = world.users["member"]
    grant, access, _r = _token_for(world, "member")
    assert _get(world, "/api/core/inventory", access).status_code == 200
    db.get(User, user.id).password_hash = AuthService.hash_password("Another-Passw0rd!9")
    db.commit()
    resp = _get(world, "/api/core/inventory", access)
    assert resp.status_code == 401
    assert resp.headers["WWW-Authenticate"].startswith(WWW_INVALID)
    db.expire_all()
    assert db.get(OAuthGrant, grant.id).revoked_at is not None
    assert db.get(OAuthGrant, grant.id).revoked_reason == "password_changed"


def test_ac17_the_change_password_endpoint_ends_the_grant_too(world, db):
    from tests.mcp_oauth.conftest import PASSWORD

    _g, access, _r = _token_for(world, "member")
    session = world.session("member")
    resp = session.post(
        "/auth/change-password",
        json={
            "current_password": PASSWORD,
            "new_password": "Brand-New-Passw0rd!7",
            "new_password_confirm": "Brand-New-Passw0rd!7",
        },
    )
    assert resp.status_code == 200, resp.get_json()
    assert _get(world, "/api/core/inventory", access).status_code == 401


def test_ac17_a_deactivated_user_gets_401(world, db):
    _g, access, _r = _token_for(world, "member")
    db.get(User, world.users["member"].id).is_active = False
    db.commit()
    resp = _get(world, "/api/core/inventory", access)
    assert resp.status_code == 401
    assert resp.headers["WWW-Authenticate"].startswith(WWW_INVALID)


def test_ac17_an_auditor_whose_access_has_ended_gets_401(world, db):
    _g, access, _r = _token_for(world, "auditor")
    assert _get(world, "/api/core/inventory", access).status_code == 200
    db.get(User, world.users["auditor"].id).access_expires_at = datetime.now(UTC) - timedelta(minutes=1)
    db.commit()
    assert _get(world, "/api/core/inventory", access).status_code == 401


def test_ac17_a_suspended_organisation_gets_401(world, db):
    from app.core.db.models.organisation import OrganisationStatus

    _g, access, _r = _token_for(world, "member")
    org = world.org
    org.status = OrganisationStatus.SUSPENDED
    db.commit()
    assert _get(world, "/api/core/inventory", access).status_code == 401


# --- AC18 ---------------------------------------------------------------------------------------


def test_ac18_a_token_issued_for_another_resource_is_401(world):
    _g, access, _r = mint_grant(
        world.db, world.users["member"], world.client_row, resource="https://elsewhere.example.test/mcp"
    )
    resp = _get(world, "/api/core/inventory", access)
    assert resp.status_code == 401
    assert resp.get_json() == {"error": "invalid_token"}
    assert resp.headers["WWW-Authenticate"].startswith(WWW_INVALID)


def test_ac18_an_expired_token_is_401(world):
    _g, access, _r = mint_grant(world.db, world.users["member"], world.client_row, access_ttl=timedelta(seconds=-1))
    resp = _get(world, "/api/core/inventory", access)
    assert resp.status_code == 401
    assert resp.headers["WWW-Authenticate"].startswith(WWW_INVALID)


def test_ac18_a_revoked_token_and_a_token_of_a_revoked_grant_are_401(world, db):
    grant, access, _r = _token_for(world, "member")
    row = db.query(OAuthToken).filter_by(grant_id=grant.id, kind="access").one()
    row.revoked_at = datetime.now(UTC)
    db.commit()
    assert _get(world, "/api/core/inventory", access).status_code == 401

    grant2, access2, _r2 = _token_for(world, "sales")
    db.get(OAuthGrant, grant2.id).revoked_at = datetime.now(UTC)
    db.commit()
    assert _get(world, "/api/core/inventory", access2).status_code == 401


@pytest.mark.parametrize("value", ["bza_" + "x" * 43, "bza_", "bza_%s" % ("A" * 5000)])
def test_ac18_an_unknown_token_is_401(world, value):
    resp = _get(world, "/api/core/inventory", value)
    assert resp.status_code == 401
    assert resp.headers["WWW-Authenticate"].startswith(WWW_INVALID)


def test_ac18_a_refresh_token_is_not_an_access_token(world):
    _g, _a, refresh = _token_for(world, "member")
    assert _get(world, "/api/core/inventory", refresh).status_code == 401


def test_ac18_an_authorization_code_is_not_an_access_token(world):
    assert _get(world, "/api/core/inventory", "bzc_" + "x" * 43).status_code == 401


def test_ac18_a_bearer_value_that_is_not_ours_is_just_unauthenticated(world):
    resp = _get(world, "/api/core/inventory", "someone-elses-token")
    assert resp.status_code in {401, 302}
    assert "invalid_token" not in resp.get_data(as_text=True)


def test_ac18_no_header_means_the_normal_unauthenticated_answer(world):
    resp = world.anon().get("/api/core/inventory")
    assert resp.status_code == 401


def test_ac18_a_token_never_works_in_the_query_string_or_a_cookie(world):
    _g, access, _r = _token_for(world, "member")
    assert world.anon().get(f"/api/core/inventory?access_token={access}").status_code == 401
    c = world.anon()
    c.set_cookie("access_token", access)
    assert c.get("/api/core/inventory").status_code == 401


# --- AC19 ---------------------------------------------------------------------------------------


def test_ac19_a_session_and_a_bearer_header_is_a_session_request(world, flask_app, monkeypatch):
    monkeypatch.setitem(flask_app.config, "WTF_CSRF_ENABLED", True)
    _g, access, _r = _token_for(world, "admin")
    session = world.session("member")
    # The cookie wins: this is the member, not the admin the token belongs to.
    me = session.get("/auth/me", headers=bearer(access)).get_json()["user"]
    assert me["email"] == world.users["member"].email
    # And a write without a CSRF token is rejected exactly as it is without the header.
    plain = session.post(
        "/api/core/inventory", json={"name": "x", "quantity": 1, "unit": "kg", "inventory_type": "raw_material"}
    )
    smuggled = session.post(
        "/api/core/inventory",
        json={"name": "x", "quantity": 1, "unit": "kg", "inventory_type": "raw_material"},
        headers=bearer(access),
    )
    assert plain.status_code == smuggled.status_code == 400
    assert smuggled.get_json().get("code") == "csrf"
    assert smuggled.get_json().get("error") != "insufficient_scope"


def test_ac19_a_bearer_request_has_no_session_so_csrf_never_applies_to_it(world, flask_app, monkeypatch):
    monkeypatch.setitem(flask_app.config, "WTF_CSRF_ENABLED", True)
    _g, access, _r = _token_for(world, "admin")
    resp = world.anon().post("/api/core/inventory", json={}, headers=bearer(access))
    assert resp.status_code == 403
    assert resp.get_json()["error"] == "insufficient_scope"


# --- AC20 ---------------------------------------------------------------------------------------


def test_ac20_the_121st_request_in_a_minute_on_one_grant_is_429(world):
    _g, access, _r = _token_for(world, "member")
    client = world.anon()
    codes = [client.get("/api/core/mcp/me", headers=bearer(access)).status_code for _ in range(120)]
    assert codes == [200] * 120
    over = client.get("/api/core/mcp/me", headers=bearer(access))
    assert over.status_code == 429
    assert int(over.headers["Retry-After"]) >= 1
    assert over.get_json()["error"] == "rate_limited"
    # Another grant is unaffected.
    _g2, access2, _r2 = _token_for(world, "sales")
    assert client.get("/api/core/mcp/me", headers=bearer(access2)).status_code == 200


def test_ac20_an_invalid_token_does_not_consume_a_real_grants_allowance(world):
    _g, access, _r = _token_for(world, "member")
    client = world.anon()
    for _ in range(130):
        client.get("/api/core/mcp/me", headers=bearer("bza_" + "z" * 43))
    assert client.get("/api/core/mcp/me", headers=bearer(access)).status_code == 200


# --- AC21 ---------------------------------------------------------------------------------------


EXPECTED_RULES = [
    ("oauth.metadata", "GET", PUBLIC),
    ("oauth.register", "POST", PUBLIC),
    ("oauth.token", "POST", PUBLIC),
    ("oauth.revoke", "POST", PUBLIC),
    ("oauth.authorize", "GET", SIGNED_IN),
    ("oauth.authorize_decision", "POST", SIGNED_IN),
    ("mcp.get_me", "GET", SIGNED_IN),
    ("mcp.get_settings", "GET", "users.manage"),
    ("mcp.update_settings", "PUT", "users.manage"),
    ("mcp.list_grants", "GET", SIGNED_IN),
    ("mcp.revoke_grant", "POST", SIGNED_IN),
]


@pytest.mark.parametrize("endpoint,method,expected", EXPECTED_RULES)
def test_ac21_each_new_endpoint_has_an_explicit_rule(endpoint, method, expected):
    assert requirement_for(endpoint, method) == expected


def test_ac21_every_oauth_and_mcp_url_is_classified():
    import app.app as app_module

    seen = set()
    for rule in app_module.app.url_map.iter_rules():
        if rule.rule.startswith(("/oauth/", "/.well-known/", "/api/core/mcp/")):
            for method in rule.methods - {"HEAD", "OPTIONS"}:
                assert requirement_for(rule.endpoint, method) != DENY, (rule.rule, method)
                seen.add(rule.endpoint)
    assert {e for e, _m, _r in EXPECTED_RULES} <= seen


def test_ac21_unauthenticated_access_to_the_signed_in_endpoints_is_not_a_data_leak(world):
    anon = world.anon()
    assert anon.get("/api/core/mcp/settings").status_code in {401, 302}
    assert anon.get("/api/core/mcp/grants").status_code in {401, 302}
    assert anon.get("/api/core/mcp/me").status_code in {401, 302}
    assert anon.put("/api/core/mcp/settings", json={}).status_code in {401, 302, 400}
