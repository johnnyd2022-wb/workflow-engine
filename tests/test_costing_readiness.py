"""Live-cogs 8.1e-1: cost readiness per product, and Add Inventory "total paid".

Spec .agents/specs/live-cogs.md, "8.1e-1 build contract". Written before the implementation.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.core.db.models.user import UserRole
from app.features.costing.models import LotCostEntry
from tests.costing_helpers import (
    complete,
    lot,
    lot_cost,
    new_org,
    output_defs,
    price,
    produced_lots,
    purge,
    user_client,
    workflow,
)
from tests.test_compliant_routes import flask_app  # noqa: F401 -- fixture re-export

API = "/api/core/costing"
D = Decimal


@pytest.fixture
def world(db, flask_app):  # noqa: F811
    org = new_org(db)
    client = user_client(db, flask_app, org)
    yield org, client
    purge(db, org)


def _products(client):
    response = client.get(f"{API}/readiness")
    assert response.status_code == 200, response.get_json()
    return response.get_json()["products"]


def _detail(client, key):
    return client.get(f"{API}/readiness/{key}")


def _gin_batch(db, org, client, juniper, coriander):
    execution, (s1, s2) = workflow(
        db, org.id, [[{"name": "Macerate", "unit": "L"}], [{"name": "Gin", "unit": "bottles"}]]
    )
    complete(
        client,
        execution,
        s1,
        [(juniper, 1, "kg"), (coriander, 1, "kg")],
        [{"name": "Macerate", "quantity": 10, "unit": "L"}],
    )
    (macerate,) = produced_lots(db, org.id, s1.id)
    complete(client, execution, s2, [(macerate, 10, "L")], [{"name": "Gin", "quantity": 20, "unit": "bottles"}])
    return execution, s2


def test_ac39_latest_batch_lists_raw_materials_through_wip(world, db):
    org, client = world
    juniper = lot(db, org.id, "Juniper", 2, "kg")
    price(db, org.id, juniper.id, 90, 2)
    coriander = lot(db, org.id, "Coriander", 2, "kg")
    execution, s2 = _gin_batch(db, org, client, juniper, coriander)
    gin_id = output_defs(s2)[0]["id"]
    key = f"output:{gin_id}"

    body = _detail(client, key).get_json()
    assert body["basis"] == "latest_batch" and body["execution_id"] == str(execution.id)
    assert {m["name"]: m["costed"] for m in body["materials"]} == {"Coriander": False, "Juniper": True}
    assert body["ready"] is False
    listed = next(p for p in _products(client) if p["key"] == key)
    assert (listed["name"], listed["materials_total"], listed["materials_costed"], listed["ready"]) == (
        "Gin",
        2,
        1,
        False,
    )

    price(db, org.id, coriander.id, 20, 2)
    assert _detail(client, key).get_json()["ready"] is True


def test_ac39_product_with_no_batch_uses_declared_inputs(world, db):
    org, client = world
    from uuid import uuid4

    from app.core.db.repositories.process_repo import ProcessRepository

    repo = ProcessRepository(db)
    process = repo.create_process(org_id=org.id, name=f"Rum {uuid4().hex[:6]}", description="", is_draft=False)
    output_id = str(uuid4())
    repo.add_step(
        process_id=process.id,
        org_id=org.id,
        step_number=1,
        position=1000,
        name="Distil",
        inputs=[{"name": "Molasses", "unit": "kg"}, {"name": "Yeast", "unit": "g"}],
        outputs=[{"id": output_id, "name": "Dark Rum", "unit": "bottles", "quantity": "1"}],
        execution_prompts=[],
    )
    db.commit()
    molasses = lot(db, org.id, "molasses", 10, "kg")
    price(db, org.id, molasses.id, 30, 10)
    body = _detail(client, f"output:{output_id}").get_json()
    assert body["basis"] == "declared_inputs" and body["execution_id"] is None
    assert {m["name"]: m["costed"] for m in body["materials"]} == {"Molasses": True, "Yeast": False}
    assert all(m["inventory_item_id"] is None for m in body["materials"])
    assert body["ready"] is False


def test_ac87_same_name_definitions_are_two_products_and_legacy_lots_bucket_by_name(world, db):
    org, client = world
    spirit = lot(db, org.id, "Spirit", 20, "L")
    price(db, org.id, spirit.id, 100, 20)
    ex_a, (a,) = workflow(db, org.id, [[{"name": "Gin", "unit": "bottles"}]])
    ex_b, (b,) = workflow(db, org.id, [[{"name": "Gin", "unit": "bottles"}]])
    complete(client, ex_a, a, [(spirit, 5, "L")], [{"name": "Gin", "quantity": 5, "unit": "bottles"}])
    complete(client, ex_b, b, [(spirit, 5, "L")], [{"name": "Gin", "quantity": 5, "unit": "bottles"}])
    lot(db, org.id, "  GIN ", 3, "bottles", inventory_type="final_product")  # bought in, no output id
    keys = {p["key"] for p in _products(client) if p["name"].strip().lower() == "gin"}
    assert keys == {f"output:{output_defs(a)[0]['id']}", f"output:{output_defs(b)[0]['id']}", "name:gin"}


def test_ac88_inputs_from_an_earlier_batch_are_walked_once(world, db):
    org, client = world
    botanicals = lot(db, org.id, "Botanicals", 2, "kg")
    price(db, org.id, botanicals.id, 40, 2)
    mystery = lot(db, org.id, "Mystery", 1, "kg")
    ex1, (s1,) = workflow(db, org.id, [[{"name": "Distillate", "unit": "L"}]])
    complete(
        client,
        ex1,
        s1,
        [(botanicals, 2, "kg"), (mystery, 1, "kg")],
        [{"name": "Distillate", "quantity": 8, "unit": "L"}],
    )
    (distillate,) = produced_lots(db, org.id, s1.id)
    water = lot(db, org.id, "Water", 10, "L")
    price(db, org.id, water.id, 0, 10, kind="free")
    ex2, (s2,) = workflow(db, org.id, [[{"name": "Gin", "unit": "bottles"}]])
    complete(
        client, ex2, s2, [(distillate, 8, "L"), (water, 2, "L")], [{"name": "Gin", "quantity": 14, "unit": "bottles"}]
    )
    body = _detail(client, f"output:{output_defs(s2)[0]['id']}").get_json()
    assert {m["name"]: m["costed"] for m in body["materials"]} == {"Botanicals": True, "Mystery": False, "Water": True}
    assert "Distillate" not in {m["name"] for m in body["materials"]}


def test_readiness_unknown_key_and_isolation_and_permissions(world, db, flask_app):  # noqa: F811
    org, client = world
    spirit = lot(db, org.id, "Spirit", 5, "L")
    ex, (step,) = workflow(db, org.id, [[{"name": "Gin", "unit": "bottles"}]])
    complete(client, ex, step, [(spirit, 5, "L")], [{"name": "Gin", "quantity": 5, "unit": "bottles"}])
    key = f"output:{output_defs(step)[0]['id']}"
    assert _detail(client, "output:not-a-uuid").status_code == 404
    assert _detail(client, "name:nothing-here").status_code == 404
    other = new_org(db)
    try:
        intruder = user_client(db, flask_app, other)
        assert intruder.get(f"{API}/readiness/{key}").status_code == 404
        assert intruder.get(f"{API}/readiness").get_json()["products"] == []
    finally:
        purge(db, other)
    production = user_client(db, flask_app, org, role=UserRole.PRODUCTION)
    assert production.get(f"{API}/readiness").status_code == 403


# --- Add Inventory total paid ----------------------------------------------------------------------------


def _add(client, **extra):
    return client.post(
        "/api/core/inventory",
        json={"name": "Kawakawa", "quantity": "5", "unit": "kg", "inventory_type": "raw_material", **extra},
    )


def test_ac38_total_paid_prices_the_new_lot(world, db):
    org, client = world
    response = _add(client, total_paid="50")
    assert response.status_code == 201, response.get_json()
    item_id = response.get_json()["id"]
    cost = lot_cost(db, org.id, item_id)
    assert (D(cost["unit_cost"]), cost["status"], cost["source"]) == (D("10"), "actual", "manual")
    (entry,) = db.query(LotCostEntry).filter(LotCostEntry.inventory_item_id == item_id).all()
    assert entry.cost_flow_id is not None and D(str(entry.quantity)) == D("5")


def test_ac89_total_paid_ignored_without_permission_or_feature(world, db, flask_app):  # noqa: F811
    org, _ = world
    from app.core.db.repositories.feature_subscription_repo import FeatureSubscriptionRepository

    production = user_client(db, flask_app, org, role=UserRole.PRODUCTION)  # inventory.adjust, no costs.manage
    made = _add(production, total_paid="50")
    assert made.status_code == 201
    assert db.query(LotCostEntry).filter(LotCostEntry.inventory_item_id == made.get_json()["id"]).count() == 0

    FeatureSubscriptionRepository(db).revoke(org.id, "costing")
    db.commit()
    admin = user_client(db, flask_app, org)
    made = _add(admin, total_paid="50")
    assert made.status_code == 201
    assert db.query(LotCostEntry).filter(LotCostEntry.inventory_item_id == made.get_json()["id"]).count() == 0


@pytest.mark.parametrize("bad", ["-1", "abc", "1.00001", True])
def test_ac89_invalid_total_paid_is_400_and_no_lot(world, db, bad):
    org, client = world
    from app.core.db.models.inventory_item import InventoryItem

    before = db.query(InventoryItem).filter(InventoryItem.org_id == org.id).count()
    assert _add(client, total_paid=bad).status_code == 400
    db.expire_all()
    assert db.query(InventoryItem).filter(InventoryItem.org_id == org.id).count() == before


def test_ac40_existing_detail_payloads_carry_no_cost_fields(world, db):
    org, client = world
    made = _add(client, total_paid="50").get_json()
    assert "unit_cost" not in made
    listing = client.get("/api/core/inventory").get_data(as_text=True)
    assert "unit_cost" not in listing


# --- 8.1e-1 review round 1 regressions -------------------------------------------------------------------


def _process(db, org, steps):
    """steps: [(step_number, position, inputs, outputs)] — a process with no batch yet."""
    from uuid import uuid4

    from app.core.db.repositories.process_repo import ProcessRepository

    repo = ProcessRepository(db)
    process = repo.create_process(org_id=org.id, name=f"P {uuid4().hex[:6]}", description="", is_draft=False)
    for number, position, inputs, outputs in steps:
        repo.add_step(
            process_id=process.id,
            org_id=org.id,
            step_number=number,
            position=position,
            name=f"Step {number}",
            inputs=inputs,
            outputs=outputs,
            execution_prompts=[],
        )
    db.commit()
    return process


def test_r1_terminal_step_is_last_by_position_not_step_number(world, db):
    from uuid import uuid4

    org, client = world
    bottled, stale = str(uuid4()), str(uuid4())
    # reordered without renumbering: step 2 now sits first, step 1 last
    _process(
        db,
        org,
        [
            (1, 2000, [], [{"id": bottled, "name": "Bottled Gin", "unit": "bottles", "quantity": "1"}]),
            (
                2,
                1000,
                [{"name": "Juniper", "unit": "kg"}],
                [{"id": stale, "name": "Old Last", "unit": "L", "quantity": "1"}],
            ),
        ],
    )
    keys = {p["key"] for p in _products(client)}
    assert f"output:{bottled}" in keys and f"output:{stale}" not in keys


def test_r1_same_name_products_each_use_their_own_latest_batch(world, db):
    org, client = world
    priced = lot(db, org.id, "Spirit", 20, "L")
    price(db, org.id, priced.id, 100, 20)
    unpriced = lot(db, org.id, "Mystery Spirit", 20, "L")
    ex_a, (a,) = workflow(db, org.id, [[{"name": "Gin", "unit": "bottles"}]])
    ex_b, (b,) = workflow(db, org.id, [[{"name": "Gin", "unit": "bottles"}]])
    complete(client, ex_a, a, [(priced, 5, "L")], [{"name": "Gin", "quantity": 5, "unit": "bottles"}])
    complete(client, ex_b, b, [(unpriced, 5, "L")], [{"name": "Gin", "quantity": 5, "unit": "bottles"}])
    key_a, key_b = (f"output:{output_defs(s)[0]['id']}" for s in (a, b))
    detail_a, detail_b = _detail(client, key_a).get_json(), _detail(client, key_b).get_json()
    assert (detail_a["execution_id"], detail_a["ready"]) == (str(ex_a.id), True)
    assert (detail_b["execution_id"], detail_b["ready"]) == (str(ex_b.id), False)
    listed = {p["key"]: p["ready"] for p in _products(client)}
    assert (listed[key_a], listed[key_b]) == (True, False)


def test_r1_material_walk_terminates_on_a_cycle():
    from types import SimpleNamespace as Flow
    from uuid import uuid4

    from app.features.costing.readiness import _Graph, _material_lots

    e1, e2, wip1, wip2, raw = (uuid4() for _ in range(5))
    graph = _Graph.__new__(_Graph)
    graph.flows_by_exec = {
        e1: [
            Flow(direction="out", inventory_item_id=wip2),
            Flow(direction="out", inventory_item_id=raw),
            Flow(direction="in", inventory_item_id=wip1),
        ],
        e2: [Flow(direction="out", inventory_item_id=wip1), Flow(direction="in", inventory_item_id=wip2)],
    }
    graph.producers = {wip1: {e1}, wip2: {e2}, raw: set()}
    assert _material_lots(graph, e1) == [raw]


def test_r1_readiness_query_count_is_bounded_for_a_catalogue(world, db):
    from uuid import uuid4

    from sqlalchemy import event

    org, client = world
    for n in range(100):
        _process(
            db,
            org,
            [
                (
                    1,
                    1000,
                    [{"name": f"Herb {n % 7}", "unit": "kg"}],
                    [{"id": str(uuid4()), "name": f"Gin {n}", "unit": "bottles", "quantity": "1"}],
                )
            ],
        )
    for n in range(7):
        herb = lot(db, org.id, f"Herb {n}", 5, "kg")
        price(db, org.id, herb.id, 10, 5)
    juniper = lot(db, org.id, "Juniper", 2, "kg")
    coriander = lot(db, org.id, "Coriander", 2, "kg")
    _gin_batch(db, org, client, juniper, coriander)

    statements = []
    bind = db.get_bind()
    engine = getattr(bind, "engine", bind)

    def count(*_args):
        statements.append(1)

    event.listen(engine, "before_cursor_execute", count)
    try:
        products = _products(client)
    finally:
        event.remove(engine, "before_cursor_execute", count)
    assert len(products) >= 101
    assert len(statements) <= 40, f"{len(statements)} queries for {len(products)} products"


def test_r1_total_paid_on_a_batch_output_is_400_and_no_lot(world, db):
    from uuid import uuid4

    from app.core.db.models.inventory_item import InventoryItem

    org, client = world
    juniper = lot(db, org.id, "Juniper", 2, "kg")
    coriander = lot(db, org.id, "Coriander", 2, "kg")
    execution, s2 = _gin_batch(db, org, client, juniper, coriander)
    before = db.query(InventoryItem).filter(InventoryItem.org_id == org.id).count()
    response = client.post(
        "/api/core/inventory",
        headers={"Idempotency-Key": str(uuid4())},
        json={
            "name": "Gin",
            "quantity": "3",
            "unit": "bottles",
            "inventory_type": "final_product",
            "total_paid": "30",
            "source_execution_id": str(execution.id),
            "source_execution_step_id": str(s2.id),
            "source_output_id": output_defs(s2)[0]["id"],
        },
    )
    assert response.status_code == 400, response.get_json()
    db.expire_all()
    assert db.query(InventoryItem).filter(InventoryItem.org_id == org.id).count() == before


@pytest.mark.parametrize("failure", ["costing", "crash"])
def test_r1_pricing_failure_after_insert_leaves_nothing_even_with_idempotency(world, db, monkeypatch, failure):
    from uuid import uuid4

    from app.core.db.models.api_idempotency_key import ApiIdempotencyKey
    from app.core.db.models.inventory_item import InventoryItem
    from app.features.costing import service

    org, client = world

    def broken(*_args, **_kwargs):
        if failure == "costing":
            raise service.CostingError("no price for you")
        raise RuntimeError("boom")

    monkeypatch.setattr(service, "set_lot_price", broken)
    before = db.query(InventoryItem).filter(InventoryItem.org_id == org.id).count()
    response = client.post(
        "/api/core/inventory",
        headers={"Idempotency-Key": str(uuid4())},
        json={
            "name": "Atomic Kawakawa",
            "quantity": "5",
            "unit": "kg",
            "inventory_type": "raw_material",
            "total_paid": "50",
        },
    )
    assert response.status_code == (400 if failure == "costing" else 500)
    db.expire_all()
    assert db.query(InventoryItem).filter(InventoryItem.org_id == org.id).count() == before
    assert db.query(InventoryItem).filter(InventoryItem.name == "Atomic Kawakawa").count() == 0
    assert db.query(ApiIdempotencyKey).filter(ApiIdempotencyKey.org_id == org.id).count() == 0


# Barcode add-quantity with total_paid: 8.1e-2 now prices the new `added` flow (spec AC91,
# tests/test_costing_without_xero.py), replacing 8.1e-1's "not applied".


def test_r1_total_paid_on_untracked_lot_is_all_or_nothing(world, db):
    from app.core.db.models.inventory_item import InventoryItem

    org, client = world
    before = db.query(InventoryItem).filter(InventoryItem.org_id == org.id).count()
    response = _add(client, untracked=True, notes="found in the shed", total_paid="50")
    db.expire_all()
    after = db.query(InventoryItem).filter(InventoryItem.org_id == org.id).count()
    assert response.status_code == 201, response.get_json()
    item_id = response.get_json()["id"]
    assert db.query(LotCostEntry).filter(LotCostEntry.inventory_item_id == item_id).count() == 1
    assert after == before + 1


def test_r2_terminal_step_tie_on_position_matches_execution_creation(world, db):
    """Equal positions: readiness and execution creation pick the same terminal step."""
    from uuid import uuid4

    from app.core.db.models.execution_step import ExecutionStep
    from app.core.db.models.step import Step
    from app.core.db.repositories.execution_repo import ExecutionRepository

    org, client = world
    out_a, out_b = str(uuid4()), str(uuid4())
    process = _process(
        db,
        org,
        [
            (1, 1000, [], [{"id": out_a, "name": "A", "unit": "L", "quantity": "1"}]),
            (2, 1000, [], [{"id": out_b, "name": "B", "unit": "L", "quantity": "1"}]),
        ],
    )
    execution = ExecutionRepository(db).create_execution(process_id=process.id, org_id=org.id)
    db.commit()
    terminal = (
        db.query(Step)
        .join(ExecutionStep, ExecutionStep.step_id == Step.id)
        .filter(ExecutionStep.execution_id == execution.id, ExecutionStep.is_terminal_step.is_(True))
        .one()
    )
    terminal_output = terminal.outputs[0]["id"]
    keys = {p["key"] for p in _products(client)}
    assert f"output:{terminal_output}" in keys
    assert f"output:{({out_a, out_b} - {terminal_output}).pop()}" not in keys


def test_r2_readiness_query_count_with_a_long_price_history(world, db):
    """An unpriced material estimated from many earlier same-name lots stays within budget."""
    from sqlalchemy import event

    org, client = world
    for n in range(40):
        old = lot(db, org.id, "Juniper", 1, "kg")
        price(db, org.id, old.id, 20 + n, 1)
    juniper = lot(db, org.id, "Juniper", 2, "kg")  # this batch's lot: unpriced, estimated
    coriander = lot(db, org.id, "Coriander", 2, "kg")
    price(db, org.id, coriander.id, 10, 2)
    _gin_batch(db, org, client, juniper, coriander)

    statements = []
    bind = db.get_bind()
    engine = getattr(bind, "engine", bind)

    def count(*_args):
        statements.append(1)

    event.listen(engine, "before_cursor_execute", count)
    try:
        products = _products(client)
    finally:
        event.remove(engine, "before_cursor_execute", count)
    assert any(p["ready"] for p in products), "juniper is estimated, so costed"
    assert len(statements) <= 40, f"{len(statements)} queries with 40 earlier juniper lots"


def test_r2_total_paid_on_a_second_site(world, db):
    from app.core.db.models.inventory_item import InventoryItem
    from tests.factories import grant_multi_site

    org, client = world
    grant_multi_site(db, org.id)
    db.commit()
    assert client.put("/api/core/sites/settings", json={"enabled": True}).status_code == 200
    site = client.post("/api/core/sites", json={"name": "Bond store", "kind": "storage"})
    assert site.status_code == 201, site.get_json()
    site_id = site.get_json()["id"]
    made = _add(client, total_paid="50", site_id=site_id)
    assert made.status_code == 201, made.get_json()
    item_id = made.get_json()["id"]
    db.expire_all()
    assert str(db.get(InventoryItem, item_id).site_id) == site_id
    (entry,) = db.query(LotCostEntry).filter(LotCostEntry.inventory_item_id == item_id).all()
    assert D(str(entry.amount)) == D("50")
