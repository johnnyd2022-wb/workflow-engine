"""Live-cogs 8.1f-3b: duty at today's excise settings on the batch cost card."""

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import event

from app.core.db.models.inventory_item import InventoryItem
from app.core.db.repositories.feature_subscription_repo import FeatureSubscriptionRepository
from app.core.db.repositories.inventory_repo import InventoryRepository
from app.features.compliant.models.alcohol_product_profile import AlcoholProductProfile
from app.features.compliant.models.compliance_profile import ComplianceProfile
from app.features.compliant.models.excise import ExciseRate
from app.features.compliant.modules.nz_alcohol import excise
from tests.costing_helpers import complete, lot, new_org, price, purge, user_client, workflow
from tests.test_compliant_routes import flask_app  # noqa: F401 -- fixture re-export

ROOT = Path(__file__).resolve().parents[1]
API = "/api/core/costing/executions/{}/cost"


@pytest.fixture
def world(db, flask_app):  # noqa: F811
    org = new_org(db)
    FeatureSubscriptionRepository(db).grant(org.id, "compliant")
    db.add(ComplianceProfile(org_id=org.id, enabled=True, industry_module="nz_alcohol"))
    db.add(
        AlcoholProductProfile(
            org_id=org.id,
            inventory_name="House Gin",
            product_type="spirits",
            pack_volume_ml=Decimal("700"),
            abv_percent=Decimal("44"),
            customs_product_code="2208.50.00",
        )
    )
    db.add(
        ExciseRate(
            org_id=org.id,
            tariff_item="2208.50.00",
            rate_per_lal=Decimal("70.1234"),
            effective_from=date(2026, 7, 1),
        )
    )
    db.commit()
    client = user_client(db, flask_app, org)
    yield {"org": org, "client": client}
    purge(db, org)


def _batch(db, world, output_count=1, *, name="House Gin"):
    spirit = lot(db, world["org"].id, "Neutral spirit", 100, "L")
    price(db, world["org"].id, spirit.id, 50, 100)
    execution, (step,) = workflow(
        db, world["org"].id, [[{"name": f"{name} {i}", "unit": "bottles"} for i in range(output_count)]]
    )
    outputs = [
        {"name": name if output_count == 1 else f"{name} {i}", "quantity": 100, "unit": "bottles"}
        for i in range(output_count)
    ]
    complete(world["client"], execution, step, inputs=[(spirit, 10, "L")], outputs=outputs)
    rows = [
        db.query(InventoryItem)
        .filter_by(org_id=world["org"].id, source_execution_step_id=step.id, name=out["name"])
        .one()
        for out in outputs
    ]
    return execution, rows


def _response(world, execution):
    response = world["client"].get(API.format(execution.id))
    assert response.status_code == 200, response.get_json()
    return response.get_json()


def test_ac115_gin_duty_per_unit_and_landed_cost_match_excise_measure(db, world):
    execution, (item,) = _batch(db, world)
    body = _response(world, execution)
    output = body["outputs"][0]
    measured = excise.measure(
        db, world["org"].id, [(item, Decimal("100"))], date.fromisoformat(body["duty_today"]["on"])
    )[0]
    expected_total = Decimal(measured["duty"])
    expected_per_unit = expected_total / Decimal("100")

    assert body["duty_today"]["tracked"] is True
    assert output["duty_today"]["total"] == str(expected_total.quantize(Decimal("0.0001")))
    assert Decimal(output["duty_today"]["per_unit"]) == expected_per_unit.quantize(Decimal("0.0001"))
    assert Decimal(output["duty_today"]["landed_per_unit"]) == Decimal(output["unit_cost"]) + Decimal(
        output["duty_today"]["per_unit"]
    )


def test_reconciled_output_duty_uses_producing_step_abv(db, world):
    from app.features.compliant.modules.nz_alcohol.workflow_rules import ABV_PROMPT_LABEL

    spirit = lot(db, world["org"].id, "Neutral spirit", 10, "L")
    execution, (step,) = workflow(db, world["org"].id, [[{"name": "House Gin", "unit": "bottles"}]])
    existing = lot(
        db,
        world["org"].id,
        "House Gin",
        100,
        "bottles",
        inventory_type="work_in_progress",
        extra_data={"untracked": True, "remaining_balance_to_reconcile": "100"},
    )
    response = world["client"].post(
        f"/api/core/executions/{execution.id}/steps/{step.id}/complete",
        json={
            "actual_inputs": [
                {"name": spirit.name, "quantity": "10", "unit": "L", "inventory_item_id": str(spirit.id)}
            ],
            "actual_outputs": [
                {
                    "name": "House Gin",
                    "quantity": "100",
                    "unit": "bottles",
                    "untracked_item_id": str(existing.id),
                }
            ],
            "execution_data": {ABV_PROMPT_LABEL: "40"},
        },
    )
    assert response.status_code == 200, response.get_json()
    body = _response(world, execution)
    output = body["outputs"][0]
    assert output["execution_step_id"] == str(step.id)
    measured = excise.measure(
        db,
        world["org"].id,
        [(existing, Decimal("100"))],
        date.fromisoformat(body["duty_today"]["on"]),
        step_overrides=[step.id],
    )[0]
    assert output["duty_today"]["total"] == str(Decimal(measured["duty"]).quantize(Decimal("0.0001")))


def test_reconciled_output_ignores_the_older_lots_recorded_abv(db, world):
    """Review r3: the producing step's 40% wins over a stale 44% on the lot it was reconciled into."""
    from app.features.compliant.modules.nz_alcohol.workflow_rules import ABV_PROMPT_LABEL

    spirit = lot(db, world["org"].id, "Neutral spirit", 10, "L")
    execution, (step,) = workflow(db, world["org"].id, [[{"name": "House Gin", "unit": "bottles"}]])
    existing = lot(
        db,
        world["org"].id,
        "House Gin",
        100,
        "bottles",
        inventory_type="work_in_progress",
        extra_data={"untracked": True, "remaining_balance_to_reconcile": "100", "abv_percent": "44"},
    )
    response = world["client"].post(
        f"/api/core/executions/{execution.id}/steps/{step.id}/complete",
        json={
            "actual_inputs": [
                {"name": spirit.name, "quantity": "10", "unit": "L", "inventory_item_id": str(spirit.id)}
            ],
            "actual_outputs": [
                {
                    "name": "House Gin",
                    "quantity": "100",
                    "unit": "bottles",
                    "untracked_item_id": str(existing.id),
                }
            ],
            "execution_data": {ABV_PROMPT_LABEL: "40"},
        },
    )
    assert response.status_code == 200, response.get_json()
    body = _response(world, execution)
    output = body["outputs"][0]
    assert output["execution_step_id"] == str(step.id)
    measured = excise.measure(
        db,
        world["org"].id,
        [(existing, Decimal("100"))],
        date.fromisoformat(body["duty_today"]["on"]),
        step_overrides=[step.id],
    )[0]
    assert Decimal(measured["abv_percent"]) == Decimal("40")
    assert output["duty_today"]["total"] == str(Decimal(measured["duty"]).quantize(Decimal("0.0001")))
    stale = excise.measure(
        db, world["org"].id, [(existing, Decimal("100"))], date.fromisoformat(body["duty_today"]["on"])
    )[0]
    assert Decimal(stale["abv_percent"]) == Decimal("44") and Decimal(stale["duty"]) > Decimal(measured["duty"])


def test_ac116_nz_alcohol_off_is_not_tracked(db, world):
    from app.features.compliant.models.compliance_profile import ComplianceProfile

    execution, _ = _batch(db, world)
    profile = db.query(ComplianceProfile).filter_by(org_id=world["org"].id).one()
    profile.enabled = False
    db.commit()
    body = _response(world, execution)
    assert body["duty_today"]["tracked"] is False
    assert all(value is None for key, value in body["duty_today"].items() if key != "on" and key != "tracked")


def test_ac117_missing_alcohol_profile_is_tracked_with_reason(db, world):
    db.query(AlcoholProductProfile).filter_by(org_id=world["org"].id).delete()
    db.commit()
    execution, _ = _batch(db, world)
    body = _response(world, execution)
    output = body["outputs"][0]
    assert body["duty_today"]["tracked"] is True
    assert output["duty_today"]["per_unit"] is None and output["duty_today"]["total"] is None
    assert output["duty_today"]["missing"] == "Not an excise product or no rate set"


def test_ac118_duty_uses_produced_quantity_not_remaining_stock(db, world):
    execution, (item,) = _batch(db, world)
    before = _response(world, execution)["outputs"][0]["duty_today"]
    InventoryRepository(db).consume_final_product_lot(world["org"].id, item.id, "50")
    db.expire_all()
    assert Decimal(str(item.quantity)) == Decimal("50")
    after = _response(world, execution)["outputs"][0]["duty_today"]
    assert after == before


def test_ac119_measure_query_count_is_constant_for_two_and_five_outputs(db, world):
    executions = [_batch(db, world, 2)[0], _batch(db, world, 5)[0]]
    query_counts = []
    for execution in executions:
        count = 0

        def count_query(*_args):
            nonlocal count
            count += 1

        event.listen(db.get_bind(), "before_cursor_execute", count_query)
        try:
            _response(world, execution)
        finally:
            event.remove(db.get_bind(), "before_cursor_execute", count_query)
        query_counts.append(count)
    assert abs(query_counts[0] - query_counts[1]) <= 1, query_counts


def test_ac126_excise_measure_runs_once_for_all_output_lots(db, world, monkeypatch):
    execution, _ = _batch(db, world, 5)
    calls = 0
    original = excise.measure

    def counted(*args, **kwargs):
        nonlocal calls
        calls += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(excise, "measure", counted)
    _response(world, execution)
    assert calls == 1


def test_ac127_execution_duty_remains_org_isolated(db, flask_app, world):  # noqa: F811
    execution, _ = _batch(db, world)
    other = new_org(db)
    try:
        intruder = user_client(db, flask_app, other)
        assert intruder.get(API.format(execution.id)).status_code == 404
    finally:
        purge(db, other)


def test_ac128_batch_card_reads_duty_today():
    source = (ROOT / "app/features/costing/frontend/static/cost-ui.js").read_text()
    batch_card = source.split("function batchCard", 1)[1].split(
        "/* ---------------------------------------------------------------- Add Inventory field", 1
    )[0]
    assert "duty_today" in batch_card
