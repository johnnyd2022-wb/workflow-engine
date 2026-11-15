"""AC37: each ``x-bize.mcp`` operation, called on seeded data, returns a body that validates against its schema.

The calls go through a real bearer token, the way the MCP server makes them, so an operation that only
works for a session fails here too. The schema is closed for the test (see ``tests.openapi.support``): a
field the route returns that the document does not describe is a failure, so the docs cannot drift from
the code.
"""

from __future__ import annotations

import pytest

from tests.openapi.seeds import SEEDS, Call, Showcase, showcase_world  # noqa: F401  (the fixture)
from tests.openapi.support import by_id, mcp_operations, response_schema, schema_errors


def _present(body, dotted: str) -> bool:
    """True when ``dotted`` (``items``, ``summary.total``) is in the body and is not empty or null."""
    node = body
    for part in dotted.split("."):
        if not isinstance(node, dict) or part not in node:
            return False
        node = node[part]
    return node not in (None, [], {}, "")


def test_ac37_every_assistant_operation_has_a_seed(full_doc):
    assert set(mcp_operations(full_doc)) <= set(SEEDS), sorted(set(mcp_operations(full_doc)) - set(SEEDS))


@pytest.mark.parametrize("oid", sorted(SEEDS))
def test_ac37_the_real_response_validates_against_the_documented_schema(showcase_world, full_doc, oid):
    world: Showcase = showcase_world
    path_template, method, op = by_id(full_doc)[oid]
    assert method == "GET"
    call: Call = SEEDS[oid](world)
    url = path_template.format(**call.params)
    resp = world.token_client.get(url, query_string=call.query, headers=world.token_headers)
    assert resp.status_code == 200, f"{url}: {resp.get_data(as_text=True)[:400]}"
    body = resp.get_json()
    schema = response_schema(op)
    assert schema is not None, oid
    errors = schema_errors(full_doc, schema, body)
    assert errors == [], f"{oid}: {errors[:8]}"
    for dotted in call.nonempty:
        assert _present(body, dotted), f"{oid}: the seed did not produce {dotted}, so it proves nothing about it"


def test_ac37_a_session_gets_the_same_body_as_a_token(showcase_world, full_doc):
    world: Showcase = showcase_world
    url = by_id(full_doc)["core_list_inventory"][0]
    via_token = world.token_client.get(url, headers=world.token_headers)
    via_session = world.session_client.get(url)
    assert via_token.status_code == via_session.status_code == 200
    assert via_token.get_json() == via_session.get_json()
