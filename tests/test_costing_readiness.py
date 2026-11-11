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
