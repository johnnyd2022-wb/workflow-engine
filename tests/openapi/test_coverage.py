"""AC37 and AC39: the coverage ratchet.

A test in the style of the access-policy coverage test (``tests/test_access_policy.py``): adding a route
without saying what it is fails here, in review, instead of leaving a hole in the catalogue.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

from app.api.openapi import build_document
from app.api.openapi.coverage import mcp_problems, operations_missing_summary, operations_without_schemas
from app.api.openapi.overlay import OVERLAY_DIR
from app.core.security.access_policy import READ_PERMISSIONS, requirement_for
from tests.openapi.support import by_id, mcp_operations, operations, response_example, response_schema, schema_errors

ROOT = Path(__file__).resolve().parents[2]

# The ratchet. The number of operations still shown as a skeleton (a summary and a permission, but no
# described response) may go down and never up. Lower it in the MR that documents more routes.
MAX_OPERATIONS_WITHOUT_SCHEMAS = 10_000  # set to the real count once the overlay exists

# What the spec's first wave names: the routes people ask about, plus the layer-3 calculations.
FIRST_WAVE = frozenset(
    {
        "core_list_inventory",
        "stocktake_get_stock_position",
        "core_trace_inventory_backward",
        "core_trace_inventory_to_sale_graph",
        "core_trace_raw_material",
        "lot_holds_list_open_holds",
        "lot_holds_get_lot_holds",
        "core_list_processes",
        "core_get_process",
        "core_list_executions",
        "core_get_execution",
        "compliant_compliant_api_list_records",
        "compliant_compliant_api_get_excise_position",
        "compliant_compliant_api_get_excise_period",
        "compliant_compliant_api_list_excise_periods",
        "crm_crm_api_get_org_invoices",
        "crm_crm_api_monthly_sales",
        "costing_get_lot_cost",
        "costing_get_execution_cost",
        "costing_readiness_list",
        "costing_readiness_detail",
        "costing_margins_report",
        "costing_get_stock_value",
        "planning_get_stock_cover",
        "planning_get_planning_batches",
        "core_list_output_ready_date",
        "core_list_expired_materials",
        "stocktake_get_stocktake_reconciliation",
    }
)
CALCULATIONS = frozenset(
    {
        "planning_get_stock_cover",
        "planning_get_planning_batches",
        "core_list_output_ready_date",
        "core_list_expired_materials",
        "stocktake_get_stocktake_reconciliation",
        "costing_get_stock_value",
        "costing_margins_report",
        "costing_readiness_list",
        "costing_readiness_detail",
        "compliant_compliant_api_get_excise_position",
    }
)
CONCEPT = re.compile(r"^[a-z][a-z_]*\.[a-z][a-z_]*$")


# --- every route says what it is (AC39) -----------------------------------------------------------


def test_ac39_every_api_route_has_a_summary(full_doc):
    assert operations_missing_summary(full_doc) == []


def test_ac39_adding_a_route_without_a_summary_fails_the_coverage_check():
    from app.api.app_factory import create_app
    from app.core.security.permissions import requires_auth

    app = create_app()  # a fresh app: nothing has been served yet, so a route can still be added

    @app.get("/api/zz/with-no-summary")
    @requires_auth
    def zz_no_summary():
        return {}

    @app.get("/api/zz/with-a-docstring")
    @requires_auth
    def zz_with_docstring():
        """Say what it does."""
        return {}

    missing = operations_missing_summary(build_document(app))
    assert missing == ["zz_no_summary"]
    assert by_id(build_document(app))["zz_with_docstring"][2]["summary"] == "Say what it does."


# --- the first wave is complete (AC37) --------------------------------------------------------------


def test_ac37_the_first_wave_is_marked_for_the_assistant_and_is_about_thirty_operations(full_doc):
    marked = set(mcp_operations(full_doc))
    assert FIRST_WAVE <= marked, sorted(FIRST_WAVE - marked)
    assert 28 <= len(marked) <= 40, len(marked)


def test_ac37_the_layer_three_calculations_say_so(full_doc):
    ops = by_id(full_doc)
    for oid in sorted(CALCULATIONS):
        assert ops[oid][2]["x-bize"]["kind"] == "calculation", oid
    kinds = {op["x-bize"].get("kind") for _p, _m, op in mcp_operations(full_doc).values()}
    assert kinds <= {"record", "list", "calculation"}


def test_ac37_every_assistant_operation_is_a_get_that_a_token_can_reach_and_names_a_read_permission(flask_app, full_doc):
    endpoints = {rule.endpoint.replace(".", "_"): rule.endpoint for rule in flask_app.url_map.iter_rules()}
    for oid, (_path, method, op) in mcp_operations(full_doc).items():
        assert method == "GET", oid
        permission = op["x-bize"]["permission"]
        held = permission if isinstance(permission, list) else [permission]
        assert READ_PERMISSIONS & set(held), (oid, permission)
        requirement = requirement_for(endpoints[oid], "GET")
        assert requirement not in ("signed_in", "public", "deny"), oid
        assert op["security"] and {"bearerToken": []} in op["security"], oid


def test_ac37_every_assistant_operation_has_schemas_concepts_related_operations_and_an_example(full_doc):
    problems = mcp_problems(full_doc)
    assert problems == {}, "\n".join(f"{oid}: {'; '.join(p)}" for oid, p in sorted(problems.items()))


def test_ac37_concepts_are_domain_dot_topic_ids(full_doc):
    for oid, (_path, _method, op) in mcp_operations(full_doc).items():
        concepts = op["x-bize"]["concepts"]
        assert concepts, oid
        for concept in concepts:
            assert CONCEPT.match(concept), (oid, concept)


def test_ac37_the_concept_ids_used_are_recorded_for_the_knowledge_docs(full_doc):
    report = (ROOT / ".agents" / "reports" / "public-mcp" / "openapi-concepts.md").read_text(encoding="utf-8")
    used = {c for _p, _m, op in operations(full_doc) for c in op["x-bize"].get("concepts", [])}
    assert used, "no operation names a concept"
    missing = sorted(c for c in used if f"`{c}`" not in report)
    assert missing == [], f"add these to .agents/reports/public-mcp/openapi-concepts.md: {missing}"


def test_ac37_every_related_operation_exists(full_doc):
    ids = set(by_id(full_doc))
    for oid, (_path, _method, op) in by_id(full_doc).items():
        related = op["x-bize"].get("related_operations", [])
        assert set(related) <= ids, (oid, sorted(set(related) - ids))
        assert oid not in related, oid


def test_ac37_every_example_is_a_valid_instance_of_its_own_schema(full_doc):
    checked = 0
    for oid, (_path, _method, op) in by_id(full_doc).items():
        schema, example = response_schema(op), response_example(op)
        if schema is None or example is None:
            continue
        checked += 1
        assert schema_errors(full_doc, schema, example) == [], oid
    assert checked >= 28


# --- the overlay and the ratchet ---------------------------------------------------------------------


def test_the_overlay_only_describes_operations_that_exist(full_doc):
    ids = set(by_id(full_doc))
    stale = []
    for path in sorted(OVERLAY_DIR.glob("*.yaml")):
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        stale += [f"{path.name}: {oid}" for oid in data.get("operations", {}) if oid not in ids]
    assert stale == [], f"a route was renamed or removed; update the overlay: {stale}"


def test_the_count_of_operations_without_schemas_only_goes_down(full_doc):
    count = len(operations_without_schemas(full_doc))
    assert count <= MAX_OPERATIONS_WITHOUT_SCHEMAS, (
        f"{count} operations have no described response, up from the ratchet's {MAX_OPERATIONS_WITHOUT_SCHEMAS}. "
        "Describe the new route's response in app/api/openapi/overlay/<domain>.yaml."
    )


def test_a_documented_operation_names_its_success_response(full_doc):
    for oid, (_path, _method, op) in by_id(full_doc).items():
        status = op["x-bize"]["schema_status"]
        assert status in ("documented", "skeleton"), oid
        assert (status == "documented") == (response_schema(op) is not None), oid


@pytest.mark.parametrize("oid", sorted(FIRST_WAVE))
def test_ac37_each_first_wave_operation_documents_every_query_parameter_it_takes(full_doc, oid):
    op = by_id(full_doc)[oid][2]
    for parameter in op.get("parameters", []):
        assert parameter.get("description"), (oid, parameter["name"])
        assert parameter.get("schema"), (oid, parameter["name"])
        if parameter["in"] == "path":
            assert parameter["required"] is True
