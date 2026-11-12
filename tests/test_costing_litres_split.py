"""Live-cogs 8.1f-3d: opt-in litres basis for free joint outputs."""

import pytest

from app.features.compliant.models.alcohol_product_profile import AlcoholProductProfile
from tests.costing_helpers import (
    D,
    complete,
    execution_cost,
    lot,
    new_org,
    price,
    purge,
    user_client,
    workflow,
)
from tests.test_compliant_routes import flask_app  # noqa: F401 -- fixture re-export

API = "/api/core/costing"


@pytest.fixture
def world(db, flask_app):  # noqa: F811
    org = new_org(db)
    client = user_client(db, flask_app, org)
    spirit = lot(db, org.id, "Neutral spirit", 10, "L")
    price(db, org.id, spirit.id, 90, 10)
    execution, (step,) = workflow(db, org.id, [[{"name": "Gin", "unit": "bottles"}]])
    yield {"org": org, "client": client, "spirit": spirit, "execution": execution, "step": step}
    purge(db, org)


def _produce(world, db, *, profile_volume=700, cost_share=None):
    if cost_share is not None:
        execution, (step,) = workflow(
            db,
            world["org"].id,
            [[{"name": "Gin", "unit": "bottles", "cost_share": {"mode": "percent", "value": cost_share}}]],
        )
        world["execution"], world["step"] = execution, step
    step = world["step"]
    definitions = list(step.step.outputs)
    complete(
        world["client"],
        world["execution"],
        step,
        [(world["spirit"], 10, "L")],
        [
            {
                "name": "Gin",
                "quantity": 10,
                "unit": "bottles",
                "output_id": definitions[0]["id"],
                "library_remainder_ml": "2000",
            }
        ],
    )
    # Actual output creation makes the companion library lot; associate the profile by the base name.
    if profile_volume is not None:
        db.add(
            AlcoholProductProfile(
                org_id=world["org"].id,
                inventory_name="Gin",
                product_type="spirit",
                pack_volume_ml=profile_volume,
                is_active=True,
            )
        )
    db.flush()


def _settings(db, org_id, split_basis):
    from app.features.costing import service

    return service.set_settings(db, org_id, split_basis=split_basis)


def test_ac120_quantity_basis_keeps_library_remainder_at_zero_share(world, db):
    _produce(world, db)
    result = execution_cost(db, world["org"].id, world["execution"].id)
    values = {row["name"]: D(row["known_amount"]) for row in result["outputs"]}
    assert values["Gin"] == D("90")
    assert values["Gin - Library stock"] == D("0")


def test_ac121_litres_basis_splits_bottles_and_library_stock_exactly(world, db):
    _produce(world, db)
    _settings(db, world["org"].id, "litres")
    result = execution_cost(db, world["org"].id, world["execution"].id)
    values = {row["name"]: D(row["known_amount"]) for row in result["outputs"]}
    assert values["Gin"] == D("70.0000")
    assert values["Gin - Library stock"] == D("20.0000")
    assert sum(values.values()) == D("90.0000")
    assert result["split_assumed"] is False


def test_ac122_missing_pack_volume_falls_back_to_quantity_and_marks_assumed(world, db):
    _produce(world, db, profile_volume=None)
    _settings(db, world["org"].id, "litres")
    result = execution_cost(db, world["org"].id, world["execution"].id)
    values = {row["name"]: D(row["known_amount"]) for row in result["outputs"]}
    assert values["Gin"] == D("90")
    assert values["Gin - Library stock"] == D("0")
    assert result["split_assumed"] is True


def test_ac123_percent_cost_share_is_preserved_under_litres_basis(world, db):
    _produce(world, db, cost_share=30)
    _settings(db, world["org"].id, "litres")
    result = execution_cost(db, world["org"].id, world["execution"].id)
    values = {row["name"]: D(row["known_amount"]) for row in result["outputs"]}
    assert values["Gin"] == D("27.0000")
    assert values["Gin - Library stock"] == D("63.0000")
    assert sum(values.values()) == D("90.0000")


def test_ac124_settings_get_put_validation_and_tenant_isolation(world, db, flask_app):  # noqa: F811
    client = world["client"]
    assert client.get(f"{API}/settings").get_json() == {
        "use_last_known_price": True,
        "split_basis": "quantity",
    }
    response = client.put(f"{API}/settings", json={"split_basis": "litres"})
    assert response.status_code == 200
    assert response.get_json()["split_basis"] == "litres"
    assert client.put(f"{API}/settings", json={"split_basis": "volume"}).status_code == 400

    other = new_org(db)
    try:
        other_client = user_client(db, flask_app, other)
        assert other_client.get(f"{API}/settings").get_json()["split_basis"] == "quantity"
    finally:
        purge(db, other)


def test_ac125_split_basis_migration_has_default_and_check_constraint(db):
    from sqlalchemy import inspect

    inspector = inspect(db.get_bind())
    columns = {column["name"]: column for column in inspector.get_columns("costing_settings")}
    assert columns["split_basis"]["nullable"] is False
    assert "quantity" in columns["split_basis"]["default"]
    constraints = inspector.get_check_constraints("costing_settings")
    assert any(
        constraint["name"] == "ck_costing_settings_split_basis" and "litres" in constraint["sqltext"]
        for constraint in constraints
    )
