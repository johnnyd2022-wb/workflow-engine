"""Live-cogs polish (after 8.1f): small wins from .agents/plans/live-cogs-polish.md."""

from __future__ import annotations

from decimal import Decimal

import pytest

from tests.costing_helpers import lot, price, user_client
from tests.test_compliant_routes import flask_app  # noqa: F401 -- fixture re-export
from tests.test_costing_readiness import _gin_batch, _products, world  # noqa: F401 -- fixture re-export

D = Decimal


def test_a_ready_product_shows_what_one_unit_cost_on_the_list(world, db):  # noqa: F811
    org, client = world
    juniper, coriander = lot(db, org.id, "Juniper", 2, "kg"), lot(db, org.id, "Coriander", 2, "kg")
    price(db, org.id, juniper.id, 90, 2)
    execution, _step = _gin_batch(db, org, client, juniper, coriander)
    (gin,) = [p for p in _products(client) if p["name"] == "Gin"]
    assert gin["ready"] is False and gin["unit_cost"] is None, "an incomplete cost is never shown as the cost"
    price(db, org.id, coriander.id, 20, 2)
    (gin,) = [p for p in _products(client) if p["name"] == "Gin"]
    assert gin["ready"] is True and gin["unit"] == "bottles"
    card = client.get(f"/api/core/costing/executions/{execution.id}/cost").get_json()
    (bottles,) = [o for o in card["outputs"] if o["name"] == "Gin"]
    assert D(gin["unit_cost"]) == D(bottles["unit_cost"]) > 0  # the same figure the batch card shows


@pytest.mark.parametrize(
    ("raw", "clean"),
    [
        ("$1,234.50", "1234.50"),
        ("NZ$ 80", "80"),
        ("1 234.50", "1234.50"),
        ("  42 ", "42"),
        ("1,23", "1,23"),  # not a thousands pattern: left for the check to refuse
        ("1 23.45", "1 23.45"),  # nor is this: never silently read as 123.45
        ("1\u00a0234.50", "1234.50"),
        ("", None),
    ],
)
def test_csv_total_paid_reads_money_as_typed(raw, clean):
    from app.core.backend.inventory_upload_routes import _check_total_paid, _clean_money

    assert _clean_money(raw) == clean
    if clean in ("1,23", "1 23.45"):
        assert _check_total_paid(clean)[0] == "error"
    elif clean is not None:
        assert _check_total_paid(clean) == ("ok", None)


def test_excise_public_helpers_match_what_duty_uses():
    from app.features.compliant.modules.nz_alcohol import excise

    assert excise.product_base_name("Navy Gin - Library stock") == excise._base_name("Navy Gin - Library stock")
    assert excise.litres_of(D("1500"), "ml", None) == excise._litres(D("1500"), "ml", None) == D("1.5")


def test_costs_page_settings_sheet_is_for_managers_only(flask_app, db):  # noqa: F811
    from tests.costing_helpers import new_org, purge

    org = new_org(db)
    try:
        manager = user_client(db, flask_app, org)
        assert "data-costs-settings" in manager.get("/core/costing/costs").get_data(as_text=True)
        viewer = user_client(db, flask_app, org, permissions=["costs.view", "production.view", "inventory.view"])
        assert "data-costs-settings" not in viewer.get("/core/costing/costs").get_data(as_text=True)
        assert viewer.put("/api/core/costing/settings", json={"split_basis": "litres"}).status_code == 403
    finally:
        purge(db, org)


def test_a_co_product_never_lends_its_cost_and_a_renamed_lot_keeps_its_own(world, db):  # noqa: F811
    """Review: cost per unit is matched by the product's output id, not its name."""
    from tests.costing_helpers import complete, output_defs, produced_lots, workflow

    org, client = world
    spirit = lot(db, org.id, "Spirit", 10, "L")
    price(db, org.id, spirit.id, 100, 10)
    execution, (step,) = workflow(db, org.id, [[{"name": "Gin", "unit": "bottles"}, {"name": "Vodka", "unit": "L"}]])
    complete(
        client,
        execution,
        step,
        [(spirit, 10, "L")],
        [{"name": "Gin", "quantity": 10, "unit": "bottles"}, {"name": "Vodka", "quantity": 30, "unit": "L"}],
    )
    gin_def, vodka_def = output_defs(step)
    card = client.get(f"/api/core/costing/executions/{execution.id}/cost").get_json()
    by_name = {o["name"]: D(o["unit_cost"]) for o in card["outputs"]}
    for lot_ in produced_lots(db, org.id, step.id):
        if lot_.name == "Vodka":
            lot_.name = "Vodka 1L"  # the lot's name no longer matches its output's name
    db.commit()
    listed = {p["key"]: p for p in _products(client)}
    assert D(listed[f"output:{gin_def['id']}"]["unit_cost"]) == by_name["Gin"]
    vodka = listed[f"output:{vodka_def['id']}"]
    assert D(vodka["unit_cost"]) == by_name["Vodka"]
    assert by_name["Gin"] != by_name["Vodka"], "the two outputs must cost differently for this test to mean anything"


def test_the_costs_list_queries_stay_flat_as_ready_products_with_batches_grow(world, db):  # noqa: F811
    """Review: each ready product's latest batch is its own; the list's query count must not grow
    per product (bulk priming of produced lots and their batches)."""
    from sqlalchemy import event

    from tests.costing_helpers import complete, workflow

    org, client = world
    spirit = lot(db, org.id, "Base spirit", 100, "L")
    price(db, org.id, spirit.id, 1000, 100)

    def products(start, n):
        for i in range(start, start + n):
            execution, (step,) = workflow(db, org.id, [[{"name": f"Product {i}", "unit": "bottles"}]])
            complete(
                client,
                execution,
                step,
                [(spirit, 1, "L")],
                [{"name": f"Product {i}", "quantity": 1, "unit": "bottles"}],
            )

    def count():
        statements = []
        engine = getattr(db.get_bind(), "engine", db.get_bind())
        listener = lambda *_a: statements.append(1)  # noqa: E731
        event.listen(engine, "before_cursor_execute", listener)
        try:
            listed = _products(client)
        finally:
            event.remove(engine, "before_cursor_execute", listener)
        assert all(p["unit_cost"] is not None for p in listed if p["name"].startswith("Product "))
        return len(statements)

    products(0, 2)
    few = count()
    products(2, 6)
    many = count()
    assert many <= few + 3, (few, many)


def test_a_cost_per_unit_built_on_an_estimated_price_says_so(world, db):  # noqa: F811
    """Review r4: every cost carries a status; the list's figure is no exception."""
    org, client = world
    juniper, coriander = lot(db, org.id, "Juniper", 2, "kg"), lot(db, org.id, "Coriander", 2, "kg")
    price(db, org.id, juniper.id, 90, 2)
    earlier = lot(db, org.id, "Coriander", 1, "kg")
    price(db, org.id, earlier.id, 10, 1)  # coriander itself unpriced: estimated from the last price paid
    _gin_batch(db, org, client, juniper, coriander)
    (gin,) = [p for p in _products(client) if p["name"] == "Gin"]
    assert gin["ready"] is True and gin["unit_cost"] is not None
    assert gin["unit_cost_status"] == "estimated"


def test_costing_the_list_out_of_budget_leaves_figures_out_not_readiness(world, db, monkeypatch):  # noqa: F811
    """Review r4: the cost-per-unit pass runs on its own engine; if loading it is over budget the
    list still answers (200) with the same readiness, just without figures."""
    from app.features.costing import readiness
    from app.features.costing.engine import CostEngine, TooLargeError

    org, client = world
    juniper, coriander = lot(db, org.id, "Juniper", 2, "kg"), lot(db, org.id, "Coriander", 2, "kg")
    price(db, org.id, juniper.id, 90, 2)
    price(db, org.id, coriander.id, 20, 2)
    _gin_batch(db, org, client, juniper, coriander)
    before = {p["key"]: p["ready"] for p in _products(client)}

    class OverBudgetForFigures(CostEngine):
        made = 0

        def __init__(self, *a, **kw):
            super().__init__(*a, **kw)
            OverBudgetForFigures.made += 1
            self.second = OverBudgetForFigures.made >= 2

        def prime(self, ids):
            if self.second:
                raise TooLargeError()
            return super().prime(ids)

    monkeypatch.setattr(readiness, "CostEngine", OverBudgetForFigures)
    response = client.get("/api/core/costing/readiness")
    assert response.status_code == 200
    products = response.get_json()["products"]
    assert {p["key"]: p["ready"] for p in products} == before
    assert all(p["unit_cost"] is None for p in products)


def test_a_spent_node_budget_never_drops_later_products_figures(world, db, monkeypatch):  # noqa: F811
    """Review r5: once one product uses up the figures engine's node budget, the next products are
    costed on their own budget: the list shows what each product's own page shows."""
    from app.features.costing import engine as engine_module
    from tests.costing_helpers import complete, workflow

    org, client = world
    spirit = lot(db, org.id, "Base spirit", 100, "L")
    price(db, org.id, spirit.id, 1000, 100)
    for i in range(4):
        execution, (step,) = workflow(db, org.id, [[{"name": f"Node Product {i}", "unit": "bottles"}]])
        complete(
            client,
            execution,
            step,
            [(spirit, 1, "L")],
            [{"name": f"Node Product {i}", "quantity": 1, "unit": "bottles"}],
        )
    monkeypatch.setattr(engine_module, "MAX_NODES", 4)
    listed = {p["key"]: p for p in _products(client) if p["name"].startswith("Node Product")}
    assert len(listed) == 4
    for key, row in listed.items():
        own = client.get(f"/api/core/costing/readiness/{key}").get_json()
        assert row["unit_cost"] is not None and row["unit_cost"] == own.get("unit_cost"), (key, row, own)


@pytest.mark.parametrize("max_nodes", [3, 4, 5, 6, 7])
def test_a_product_used_by_another_still_shows_its_own_figure(world, db, monkeypatch, max_nodes):  # noqa: F811
    """Review r6: Gin's latest batch is consumed by an RTD's batch. Whatever order products are
    costed in, and wherever the shared budget runs out, every product shows its own page's figure."""
    from app.features.costing import engine as engine_module
    from tests.costing_helpers import complete, produced_lots, workflow

    org, client = world
    spirit = lot(db, org.id, "Base spirit", 100, "L")
    price(db, org.id, spirit.id, 1000, 100)
    execution, (step,) = workflow(db, org.id, [[{"name": "Probe Gin", "unit": "bottles"}]])
    complete(client, execution, step, [(spirit, 1, "L")], [{"name": "Probe Gin", "quantity": 4, "unit": "bottles"}])
    (gin,) = produced_lots(db, org.id, step.id)
    execution, (step,) = workflow(db, org.id, [[{"name": "Probe RTD", "unit": "cans"}]])
    complete(client, execution, step, [(gin, 1, "bottles")], [{"name": "Probe RTD", "quantity": 4, "unit": "cans"}])
    execution, (step,) = workflow(db, org.id, [[{"name": "Other Product", "unit": "bottles"}]])
    complete(client, execution, step, [(spirit, 1, "L")], [{"name": "Other Product", "quantity": 1, "unit": "bottles"}])

    monkeypatch.setattr(engine_module, "MAX_NODES", max_nodes)
    for row in _products(client):
        if not row["name"].startswith(("Probe", "Other")) or not row["ready"]:
            continue
        own = client.get(f"/api/core/costing/readiness/{row['key']}").get_json()
        assert row["unit_cost"] == own.get("unit_cost"), (max_nodes, row, own)
