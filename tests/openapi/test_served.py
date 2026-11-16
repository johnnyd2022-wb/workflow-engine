"""AC36 and AC38: ``GET /api/openapi.json``, and what each caller is shown."""

from __future__ import annotations

import json

import pytest
from openapi_spec_validator import validate

from app.core.security.access_policy import (
    MCP_TOKEN_ENDPOINTS,
    SIGNED_IN,
    allows,
    requirement_for,
    token_access,
)
from tests.mcp_oauth.conftest import ROLES
from tests.mcp_oauth.support import bearer, mint_grant
from tests.openapi.support import by_id, operations

URL = "/api/openapi.json"


def _endpoints(app) -> dict[str, str]:
    return {
        rule.endpoint.replace(".", "_"): rule.endpoint
        for rule in app.url_map.iter_rules()
        if rule.rule.startswith("/api/")
    }


def _served(client, query="", **kwargs):
    resp = client.get(URL + query, **kwargs)
    assert resp.status_code == 200, resp.get_data(as_text=True)[:300]
    return resp.get_json()


def _token_client(world, who):
    _grant, access, _refresh = mint_grant(world.db, world.users[who], world.client_row)
    return world.anon(), bearer(access)


def _refs(node) -> set[str]:
    found = set()
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "$ref" and isinstance(value, str):
                found.add(value)
            else:
                found |= _refs(value)
    elif isinstance(node, list):
        for value in node:
            found |= _refs(value)
    return found


# --- the endpoint ---------------------------------------------------------------------------------


def test_ac36_a_signed_in_user_gets_a_document_that_validates_as_openapi_3_1(world):
    doc = _served(world.session("admin"))
    assert doc["openapi"].startswith("3.1")
    validate(doc)
    assert "openapi_get_openapi" in by_id(doc)  # the document describes its own route


def test_ac36_a_signed_out_caller_is_refused(world):
    resp = world.anon().get(URL)
    assert resp.status_code == 401


def test_ac36_the_response_is_json_and_private_to_the_caller(world):
    resp = world.session("member").get(URL)
    assert resp.mimetype == "application/json"
    cache = resp.headers["Cache-Control"]
    assert "private" in cache and "public" not in cache
    vary = resp.headers.get("Vary", "")
    assert "Cookie" in vary and "Authorization" in vary


def test_ac36_the_route_has_an_explicit_policy_rule_a_token_may_read():
    assert requirement_for("openapi.get_openapi", "GET") == SIGNED_IN
    assert "openapi.get_openapi" in MCP_TOKEN_ENDPOINTS


def test_ac36_an_unknown_audience_is_a_400(world):
    resp = world.session("admin").get(URL + "?audience=everyone")
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "unknown_audience"


def test_ac36_an_admin_is_shown_the_whole_committed_document(world, full_doc):
    assert _served(world.session("admin")) == json.loads(json.dumps(full_doc))


# --- AC38 ---------------------------------------------------------------------------------------


@pytest.mark.parametrize("who", ROLES)
def test_ac38_a_session_caller_is_shown_exactly_the_operations_their_role_reaches(world, full_doc, who):
    doc = _served(world.session(who))
    validate(doc)
    endpoints = _endpoints(world.app)
    shown = {op["operationId"] for _p, _m, op in operations(doc)}
    reachable = {
        op["operationId"]
        for _p, method, op in operations(full_doc)
        if allows(world.users[who], endpoints[op["operationId"]], method)
    }
    assert shown == reachable


def test_ac38_a_sales_user_is_shown_no_costs_view_operation(world):
    doc = _served(world.session("sales"))
    for _path, _method, op in operations(doc):
        permission = op["x-bize"]["permission"]
        held = permission if isinstance(permission, list) else [permission]
        assert "costs.view" not in held or len(held) > 1, op["operationId"]
    assert {"costing_get_stock_value", "costing_margins_report", "costing_readiness_list"}.isdisjoint(by_id(doc))
    assert "crm_crm_api_monthly_sales" in by_id(doc)  # what Sales does hold is there


def test_ac38_an_admin_is_shown_the_cost_operations(world):
    assert {"costing_get_stock_value", "costing_margins_report", "costing_readiness_list"} <= set(
        by_id(_served(world.session("admin")))
    )


@pytest.mark.parametrize("who", ROLES)
def test_ac38_a_token_with_audience_mcp_is_shown_only_mcp_get_operations_it_may_call(world, full_doc, who):
    client, headers = _token_client(world, who)
    doc = _served(client, "?audience=mcp", headers=headers)
    validate(doc)
    endpoints = _endpoints(world.app)
    shown = by_id(doc)
    assert shown, "an MCP caller is shown at least the operations its role may read"
    for oid, (_path, method, op) in shown.items():
        assert method == "GET", oid
        assert op["x-bize"]["mcp"] is True, oid
        assert token_access(world.users[who], endpoints[oid], "GET") == "ok", oid
    expected = {
        oid
        for oid, (_p, method, op) in by_id(full_doc).items()
        if op["x-bize"]["mcp"] is True
        and method == "GET"
        and token_access(world.users[who], endpoints[oid], "GET") == "ok"
    }
    assert set(shown) == expected


def test_ac38_what_an_mcp_caller_is_shown_differs_by_role(world):
    sales = set(by_id(_served(*_audience_args(world, "sales"))))
    admin = set(by_id(_served(*_audience_args(world, "admin"))))
    assert sales < admin
    assert "core_list_inventory" in sales and "costing_get_stock_value" not in sales
    assert "costing_get_stock_value" in admin


def _audience_args(world, who):
    client, headers = _token_client(world, who)
    return client, "?audience=mcp", {"headers": headers}


@pytest.mark.parametrize("who", ["admin", "sales"])
def test_ac38_a_token_without_an_audience_is_shown_every_read_operation_it_may_call_and_no_write(world, full_doc, who):
    client, headers = _token_client(world, who)
    doc = _served(client, headers=headers)
    endpoints = _endpoints(world.app)
    for oid, (_path, method, _op) in by_id(doc).items():
        assert method == "GET", oid
        assert token_access(world.users[who], endpoints[oid], "GET") == "ok", oid
    all_reads = {
        oid
        for oid, (_p, method, _op) in by_id(full_doc).items()
        if method == "GET" and token_access(world.users[who], endpoints[oid], "GET") == "ok"
    }
    assert set(by_id(doc)) == all_reads
    assert "openapi_get_openapi" in by_id(doc)
    assert "core_create_process" not in by_id(doc)


def test_ac38_a_session_asking_for_the_mcp_audience_is_shown_what_a_token_of_that_user_would_be(world):
    via_session = _served(world.session("sales"), "?audience=mcp")
    client, headers = _token_client(world, "sales")
    via_token = _served(client, "?audience=mcp", headers=headers)
    assert via_session == via_token


def test_ac38_a_token_of_a_switched_off_organisation_is_refused_not_shown_anything(world):
    client, headers = _token_client(world, "member")
    world.enable(enabled=False)
    resp = client.get(URL + "?audience=mcp", headers=headers)
    assert resp.status_code == 403
    assert resp.get_json()["error"] == "mcp_not_allowed"


# --- what a narrowed document leaves out -----------------------------------------------------------


@pytest.mark.parametrize("who", ["sales", "production", "auditor"])
def test_ac38_a_narrowed_document_keeps_only_the_schemas_and_tags_its_operations_use(world, full_doc, who):
    doc = _served(world.session(who))
    used = _refs({"paths": doc["paths"], "components": {"responses": doc["components"].get("responses", {})}})
    # transitive closure over component schemas
    schemas = doc["components"].get("schemas", {})
    wanted = {r.removeprefix("#/components/schemas/") for r in used if r.startswith("#/components/schemas/")}
    changed = True
    while changed:
        changed = False
        for name in list(wanted):
            for ref in _refs(schemas.get(name, {})):
                inner = ref.removeprefix("#/components/schemas/")
                if ref.startswith("#/components/schemas/") and inner not in wanted:
                    wanted.add(inner)
                    changed = True
    assert set(schemas) == wanted
    used_tags = {t for _p, _m, op in operations(doc) for t in op.get("tags", [])}
    assert {t["name"] for t in doc.get("tags", [])} == used_tags
    # something the full document defines is gone: this role is not shown everything
    assert set(schemas) < set(full_doc["components"]["schemas"])


def test_ac38_a_narrowed_document_does_not_mention_what_the_caller_cannot_reach(world, full_doc):
    """No hidden operation's id or path survives anywhere in what the caller receives, not even in a
    visible operation's ``related_operations``."""
    served = _served(world.session("sales"))
    text = json.dumps(served)
    hidden = [(oid, path) for oid, (path, _method, op) in by_id(full_doc).items() if oid not in by_id(served)]
    assert hidden
    for oid, path in hidden:
        assert f'"{oid}"' not in text, oid
        assert path not in served["paths"], path
    # ... and the related operations a caller is given are ones they can themselves reach
    visible = set(by_id(served))
    for oid, (_path, _method, op) in by_id(served).items():
        assert set(op["x-bize"].get("related_operations", [])) <= visible, oid
