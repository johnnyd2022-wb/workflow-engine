"""Step timing comes from the workflow (GL-P07 B1): how long each step takes and then waits is set
once on the workflow, the planner uses it without retyping, and a batch's use-by date keeps a
later order from being planned against stock that will have expired."""

from datetime import timedelta
from decimal import Decimal

import pytest

from app.core.db.models.step import Step
from app.features.planning import batch_service as service
from app.features.planning import demand_service
from app.features.planning.engine import BatchRule, Demand, StockKey, build_plan
from tests.features.planning import test_batches as batches

demand_world = batches.demand_world
base_demand_world = batches.base_demand_world
TODAY = batches.TODAY


def _step(db, org_id):
    return db.query(Step).filter(Step.org_id == org_id).one()


def _workflow_setting(db, org_id, output_id, **changes):
    data = batches.setting_payload(db, org_id, output_id, **changes)
    del data["steps"]
    return data


def test_the_planner_uses_the_workflows_own_timings(db, demand_world):
    org_id, _, outputs = demand_world
    step = _step(db, org_id)
    step.duration_minutes, step.wait_minutes = 60, 2820
    db.flush()
    (row,) = [w for w in service.workflow_catalog(db, org_id) if w["id"] == str(outputs[org_id])]
    assert row["timed_in_workflow"] is True
    assert (row["steps"][0]["duration_minutes"], row["steps"][0]["wait_minutes"]) == (60, 2820)

    batches.native_recipe(db, org_id, step.process_id)
    setting = service.save_setting(db, org_id, step.process_id, _workflow_setting(db, org_id, outputs[org_id]))
    assert [(s["duration_minutes"], s["waiting_minutes"]) for s in setting.snapshot["steps"]] == [(60, 2820)]
    assert setting.snapshot["elapsed_seconds"] == 2 * 86400
    demand = demand_service.create_demand(
        db, org_id, batches.payload(outputs[org_id], due_date=(TODAY + timedelta(days=5)).isoformat())
    )
    rows, _ = service.plan_demand(db, org_id, demand.id, {}, today=TODAY)
    assert rows[0].proposed_start_date == TODAY + timedelta(days=3)  # two days' work and wait, backwards from day 5


def test_a_workflow_without_timings_still_asks_for_them(db, demand_world):
    org_id, _, outputs = demand_world
    step = _step(db, org_id)
    step.duration_minutes = 60  # the wait isn't set yet
    db.flush()
    (row,) = [w for w in service.workflow_catalog(db, org_id) if w["id"] == str(outputs[org_id])]
    assert row["timed_in_workflow"] is False
    with pytest.raises(ValueError, match="Set how long each step takes"):
        service.save_setting(db, org_id, step.process_id, _workflow_setting(db, org_id, outputs[org_id]))
    # Typed on the board, as before.
    service.save_setting(db, org_id, step.process_id, batches.setting_payload(db, org_id, outputs[org_id]))


def test_changing_a_steps_timing_makes_the_saved_setting_stale(db, demand_world):
    org_id, _, outputs = demand_world
    step = _step(db, org_id)
    service.save_setting(db, org_id, step.process_id, batches.setting_payload(db, org_id, outputs[org_id]))

    def stale():
        (row,) = [w for w in service.workflow_catalog(db, org_id) if w["id"] == str(outputs[org_id])]
        return row["stale"]

    assert stale() is False  # a step with no timing keeps the fingerprint it had before this change
    step.wait_minutes = 600
    db.flush()
    assert stale() is True


def test_a_batch_carries_its_use_by_date(db, demand_world):
    org_id, _, outputs = demand_world
    step = _step(db, org_id)
    step.outputs = [
        {
            **step.outputs[0],
            "extra_data": {
                "custom_expiry": {
                    "enabled": True,
                    "mode": "fixed_duration",
                    "duration_value": 30,
                    "duration_unit": "days",
                },
                "ready_date": {"enabled": True, "mode": "fixed_duration", "duration_value": 7, "duration_unit": "days"},
            },
        }
    ]
    db.flush()
    _, setting, _, rows = batches.planned(db, demand_world)
    assert setting.snapshot["use_by"] == {"ready_wait_seconds": 7 * 86400, "shelf_life_seconds": 30 * 86400}
    ready = rows[0].theoretical_ready_date
    # Made seven days before it's ready; good for thirty days from when it was made.
    assert rows[0].snapshot["use_by_date"] == (ready + timedelta(days=23)).isoformat()


def test_a_shelf_life_set_at_production_gives_no_use_by_date(db, demand_world):
    org_id, _, outputs = demand_world
    step = _step(db, org_id)
    step.outputs = [{**step.outputs[0], "extra_data": {"custom_expiry": {"enabled": True, "mode": "set_at_execution"}}}]
    db.flush()
    _, setting, _, rows = batches.planned(db, demand_world)
    assert setting.snapshot["use_by"] is None and rows[0].snapshot["use_by_date"] is None


def test_a_later_order_is_never_planned_against_surplus_that_has_expired():
    key = StockKey("gin", "bottles", None)
    rule = BatchRule(key, "wf", Decimal(100), timedelta(days=1), shelf_life=timedelta(days=10))
    early = Demand("early", key, Decimal(30), TODAY + timedelta(days=2), 0)

    def later(days):
        return Demand("later", key, Decimal(50), TODAY + timedelta(days=days), 0)

    # 70 left over from the first batch: enough for the later order while it's in date.
    plan = build_plan((early, later(8)), (), (rule,), today=TODAY)
    assert [b.demand_id for b in plan.batches] == ["early"]
    assert plan.batches[0].use_by_date == TODAY + timedelta(days=12)
    # Past its use-by, the later order gets its own batch.
    plan = build_plan((early, later(20)), (), (rule,), today=TODAY)
    assert [b.demand_id for b in plan.batches] == ["early", "later"]
