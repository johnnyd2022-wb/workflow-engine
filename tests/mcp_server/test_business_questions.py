# ruff: noqa: F811
"""Business questions against the shipped catalogue, knowledge and seeded Flask data.

Each case fixes the expected discovery candidates and the tool result an assistant would use.
This suite exercises the MCP boundary without an external model or a live customer account.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import pytest

from app.features.crm.models.xero_invoice import XeroInvoice
from tests.mcp_oauth.conftest import flask_app  # noqa: F401 - used by showcase_world
from tests.mcp_server.support import FlaskTransport, Mcp, make_config
from tests.openapi.seeds import SEEDS, showcase_world  # noqa: F401 - shared test data

KNOWLEDGE = Path(__file__).resolve().parents[2] / "docs" / "knowledge"


@dataclass(frozen=True)
class Question:
    text: str
    topic: str
    operation: str
    selection: str
    expected: object
    query: dict = field(default_factory=dict)
    seeded_params: dict[str, str] = field(default_factory=dict)


QUESTIONS = [
    Question(
        "How much raw material is on hand in kilograms?",
        "inventory.availability",
        "core_list_inventory",
        "totals.quantity_by_unit[0].quantity",
        "2",
        {"type": "raw_material"},
    ),
    Question(
        "How many finished stock lots do we have on hand?",
        "inventory.lots",
        "core_list_inventory",
        "total_count",
        1,
        {"type": "final_product"},
    ),
    Question(
        "Which stock lots are quarantined right now?",
        "inventory.holds",
        "lot_holds_list_open_holds",
        "holds[*].lot.name",
        ["Gin · 20.0000 bottles"],
    ),
    Question(
        "Why is this Gin lot quarantined?",
        "inventory.holds",
        "lot_holds_get_lot_holds",
        "open.reason",
        "Failed ABV check",
    ),
    Question(
        "Are any lots still resting before they're ready to use?",
        "inventory.ready_dates",
        "core_list_output_ready_date",
        "output_ready_date_items",
        [],
    ),
    Question(
        "Which raw materials have gone past their expiry date?",
        "inventory.expiry",
        "core_list_expired_materials",
        "expired_raw_materials",
        [],
    ),
    Question(
        "How many steps are in our production recipe?",
        "production.workflows",
        "core_list_processes",
        "processes[0].step_count",
        2,
    ),
    Question(
        "How many batches have we run in production?",
        "production.batches",
        "core_list_executions",
        "total_count",
        1,
    ),
    Question(
        "Did this production run finish?",
        "production.batches",
        "core_get_execution",
        "status",
        "completed",
    ),
    Question(
        "Which ingredients went into this finished Gin lot?",
        "traceability.back",
        "core_trace_inventory_backward",
        "raw_materials[*].name",
        ["Coriander", "Juniper"],
    ),
    Question(
        "Which finished product was made using this supplier lot of Juniper?",
        "traceability.forward",
        "core_trace_raw_material",
        "finals[*].name",
        ["Gin"],
    ),
    Question(
        "Trace this Gin lot through to sales. What lot did the trace start from?",
        "traceability.to_sale",
        "core_trace_inventory_to_sale_graph",
        "traced_item.name",
        "Gin",
    ),
    Question(
        "What was the actual price per kilogram of this Juniper lot?",
        "costing.cost_status",
        "costing_get_lot_cost",
        "unit_cost",
        "45.000000",
    ),
    Question(
        "How much did we pay for this Juniper lot in total?",
        "costing.cost_status",
        "costing_get_lot_cost",
        "entries[0].amount",
        "90.0000",
    ),
    Question(
        "What is the cost per kilogram of this unpriced Coriander lot?",
        "costing.cost_status",
        "costing_get_lot_cost",
        "{unit_cost:unit_cost, status:status}",
        {"unit_cost": None, "status": "unknown"},
        seeded_params={"item_id": "coriander"},
    ),
    Question(
        "How much known input cost went into this Gin batch?",
        "costing.cost_status",
        "costing_get_execution_cost",
        "known_input_cost",
        "45.0000",
    ),
    Question(
        "Which materials are still missing a price for this product?",
        "costing.readiness",
        "costing_readiness_detail",
        "materials[*].{name:name, costed:costed}",
        [{"name": "Coriander", "costed": False}, {"name": "Juniper", "costed": True}],
    ),
    Question(
        "Can we work out what a bottle of Gin costs yet?",
        "costing.readiness",
        "costing_readiness_list",
        "products[0].ready",
        False,
    ),
    Question(
        "Is the value of the stock on hand complete, or are we missing prices?",
        "costing.stock_value",
        "costing_get_stock_value",
        "complete",
        False,
    ),
    Question(
        "Which customer invoice still needs paying?",
        "sales.xero_invoices",
        "crm_crm_api_get_org_invoices",
        "invoices[*].invoice_number",
        ["SHOWCASE-1"],
        {"kind": "outstanding"},
    ),
    Question(
        "How much did we invoice in net sales excluding GST this month?",
        "sales.xero_invoices",
        "crm_crm_api_monthly_sales",
        "months[0].total",
        "100.00",
        {"months": 1},
    ),
    Question(
        "How many excise filing periods are on the returns list?",
        "compliance.excise_periods",
        "compliant_compliant_api_list_excise_periods",
        "total_count",
        12,
    ),
    Question(
        "How many Customs excise returns have we lodged this year?",
        "compliance.excise_position",
        "compliant_compliant_api_get_excise_position",
        "year.lodged_periods",
        0,
    ),
    Question(
        "Does this stocktake reconciliation track individual stock movements?",
        "inventory.stocktakes",
        "stocktake_get_stocktake_reconciliation",
        "tracks_flows",
        False,
    ),
]


@pytest.fixture(scope="module")
def business_tools(showcase_world):
    world = showcase_world
    world.db.add(
        XeroInvoice(
            org_id=world.org.id,
            xero_invoice_id=f"showcase-{world.org.id}",
            xero_tenant_id="showcase",
            invoice_number="SHOWCASE-1",
            invoice_type="ACCREC",
            status="AUTHORISED",
            sub_total=100,
            total_tax=15,
            total=115,
            amount_due=115,
            currency_code="NZD",
            date=date.today(),
        )
    )
    world.db.commit()
    token = world.token_headers["Authorization"].removeprefix("Bearer ")
    with Mcp(FlaskTransport(world.app), make_config(knowledge_dir=str(KNOWLEDGE))) as harness:
        yield harness, token


@pytest.mark.parametrize("question", QUESTIONS, ids=lambda q: q.text)
def test_business_questions_find_the_operation_and_get_the_expected_answer(question, showcase_world, business_tools):
    harness, token = business_tools
    discovery = harness.discover(token, question.text, limit=6)
    assert not discovery.is_error, discovery.text
    topics = [r["topic"] for r in discovery.data["concepts"]]
    operations = [r["operation_id"] for r in discovery.data["operations"]]
    # The expected operation must be available in a short search result alongside its concept.
    assert question.topic in topics, topics
    assert question.operation in operations, operations
    params = {**SEEDS[question.operation](showcase_world).params, **question.query}
    params.update({name: showcase_world.ids[key] for name, key in question.seeded_params.items()})
    documentation = harness.docs(token, operation_id=question.operation)
    assert not documentation.is_error, documentation.text
    returned = harness.execute(
        token,
        {"id": "answer", "operation_id": question.operation, "params": params, "select": question.selection},
    ).results[0]
    assert returned["ok"], returned
    answer = returned["data"]
    if isinstance(answer, list) and all(isinstance(item, str) for item in answer):
        answer = sorted(answer)
    assert answer == question.expected


def test_supplier_lot_alias_is_available_to_an_operation_only_search(business_tools):
    harness, token = business_tools
    discovery = harness.discover(
        token, "Which finished product was made using this supplier lot of Juniper?", kind="operations", limit=6
    )
    assert not discovery.is_error, discovery.text
    operations = [row["operation_id"] for row in discovery.data["operations"]]
    assert "core_trace_raw_material" in operations, operations
    assert discovery.data["concepts"] == []
