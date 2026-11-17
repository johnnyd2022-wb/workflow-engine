"""Design review S1: a bearer token reaches only the operations the MCP catalogue allows.

The app's token rule used to let a ``bize.read`` token call any GET route whose requirement names a
view permission, while the catalogue (``x-bize.mcp`` in the OpenAPI overlay) allows far fewer. The
spec (``.agents/specs/public-mcp.md``, Enforcement) says the app enforces the same allowlist again.

Every case is derived from the generated document, never hand-listed, so a new route is covered the
moment it exists: one with no ``x-bize.mcp: true`` overlay entry is out of scope for a token.
"""

from __future__ import annotations

import pytest

from app.core.security.access_policy import MCP_TOKEN_ENDPOINTS, READ_PERMISSIONS
from app.features.mcp_oauth.services import rate_limit
from tests.factories import FeatureSubscriptionFactory
from tests.mcp_oauth.support import bearer, mint_grant

FIXED_UUID = "00000000-0000-4000-8000-000000000000"  # stable ids: xdist workers must collect identically
INSUFFICIENT = 'Bearer error="insufficient_scope", scope="bize.read"'


def _value(parameter: dict):
    schema = parameter.get("schema", {})
    if schema.get("format") == "uuid":
        return FIXED_UUID
    if schema.get("type") == "integer":
        return "1"
    return "x"


def _url(path: str, parameters: list[dict]) -> str:
    for parameter in parameters:
        if parameter["in"] == "path":
            path = path.replace("{" + parameter["name"] + "}", _value(parameter))
    return path


def _read_operations():
    """(operationId, url, mcp) for every GET that names a view permission and is not public or the
    token's own identity: what the old rule let a token reach."""
    import app.app as app_module
    from app.api.openapi.document import build

    built = build(app_module.app)
    rows = []
    for path, item in sorted(built.document["paths"].items()):
        op = item.get("get")
        if op is None:
            continue
        endpoint, _method = built.endpoints[op["operationId"]]
        if endpoint in MCP_TOKEN_ENDPOINTS:
            continue
        permission = op["x-bize"]["permission"]
        held = set(permission if isinstance(permission, list) else [permission])
        if not held & READ_PERMISSIONS:
            continue
        rows.append((op["operationId"], _url(path, op["parameters"]), op["x-bize"]["mcp"] is True))
    return rows


READ_OPERATIONS = _read_operations()
OUTSIDE_CATALOGUE = [(oid, url) for oid, url, mcp in READ_OPERATIONS if not mcp]
IN_CATALOGUE = [(oid, url) for oid, url, mcp in READ_OPERATIONS if mcp]


@pytest.fixture
def admin_token(world, monkeypatch):
    monkeypatch.setattr(rate_limit, "BEARER_REQUESTS_PER_MINUTE", 10_000_000)
    for feature in ("costing", "compliant"):
        FeatureSubscriptionFactory(org_id=world.org.id, feature_key=feature)
    world.db.commit()
    return mint_grant(world.db, world.users["admin"], world.client_row)[1]


def test_the_derived_sets_match_the_size_of_the_finding():
    # The review counted 160 token-reachable GETs against 28 in the catalogue (2026-11-17).
    assert len(IN_CATALOGUE) >= 20
    assert len(OUTSIDE_CATALOGUE) > 100
    assert "core_list_inventory" in {oid for oid, _url in IN_CATALOGUE}


@pytest.mark.parametrize("oid,url", OUTSIDE_CATALOGUE, ids=[oid for oid, _url in OUTSIDE_CATALOGUE])
def test_s1_a_token_on_a_read_route_outside_the_mcp_catalogue_is_403_insufficient_scope(world, admin_token, oid, url):
    resp = world.anon().get(url, headers=bearer(admin_token))
    assert resp.status_code == 403, (oid, url, resp.status_code)
    assert (resp.get_json(silent=True) or {}).get("error") == "insufficient_scope", (oid, url)
    assert resp.headers["WWW-Authenticate"] == INSUFFICIENT


@pytest.mark.parametrize("oid,url", IN_CATALOGUE, ids=[oid for oid, _url in IN_CATALOGUE])
def test_s1_a_token_on_a_catalogue_operation_answers_as_the_session_does(world, admin_token, oid, url):
    via_token = world.anon().get(url, headers=bearer(admin_token))
    assert (via_token.get_json(silent=True) or {}).get("error") != "insufficient_scope", (oid, url)
    via_session = world.session("admin").get(url)
    assert via_token.status_code == via_session.status_code, (oid, url, via_token.status_code)
    assert via_token.status_code in {200, 400, 404}, (oid, url, via_token.status_code)


def test_s1_head_follows_the_same_rule_as_get(world, admin_token):
    assert world.anon().head("/api/core/inventory", headers=bearer(admin_token)).status_code == 200
    _oid, outside = OUTSIDE_CATALOGUE[0]
    assert world.anon().head(outside, headers=bearer(admin_token)).status_code == 403


@pytest.mark.parametrize("url", ["/api/core/costing/margins", "/api/compliant/records"])
def test_s1_a_catalogue_operation_of_a_product_the_org_lacks_is_not_served_to_a_token(world, monkeypatch, url):
    """The feature rule holds in the app too: the product's own blueprint gate answers 404."""
    if not any(u == url for _oid, u in IN_CATALOGUE):
        pytest.skip(f"{url} is not mounted in this configuration")
    monkeypatch.setattr(rate_limit, "BEARER_REQUESTS_PER_MINUTE", 10_000_000)
    access = mint_grant(world.db, world.users["admin"], world.client_row)[1]
    assert world.anon().get(url, headers=bearer(access)).status_code == 404


def test_s1_the_app_allowlist_is_the_overlays_mcp_flags(world):
    """One source of truth: the app's allowlist is exactly the document's ``x-bize.mcp`` operations."""
    from app.api.openapi.document import build

    built = build(world.app)
    flagged = {
        built.endpoints[op["operationId"]]
        for item in built.document["paths"].values()
        for op in item.values()
        if op["x-bize"]["mcp"] is True
    }
    assert set(world.app.extensions["mcp_operations"]) == flagged


def test_s1_the_mcp_audience_document_is_still_served_to_a_token(world, admin_token):
    resp = world.anon().get("/api/openapi.json?audience=mcp", headers=bearer(admin_token))
    assert resp.status_code == 200
    shown = {op["operationId"] for item in resp.get_json()["paths"].values() for op in item.values()}
    assert {oid for oid, _url in IN_CATALOGUE} <= shown
    assert shown.isdisjoint({oid for oid, _url in OUTSIDE_CATALOGUE})


def test_s1_a_token_without_an_audience_is_shown_only_what_it_may_call(world, admin_token):
    resp = world.anon().get("/api/openapi.json", headers=bearer(admin_token))
    assert resp.status_code == 200
    shown = {op["operationId"] for item in resp.get_json()["paths"].values() for op in item.values()}
    assert shown.isdisjoint({oid for oid, _url in OUTSIDE_CATALOGUE})
