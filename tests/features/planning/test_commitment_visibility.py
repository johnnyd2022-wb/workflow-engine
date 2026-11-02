"""Where committed stock shows (GL-P07 B2b): an order-by date from the supplier's lead time on
each shortage, a notification for it, the lot's detail saying what's held, and a soft warning
before disposing into a hold."""

from datetime import timedelta

import pytest

from app.core.backend import suppliers
from app.core.db.models.step import Step
from app.core.db.models.supplier import Supplier
from app.features.compliance_checks.checks.planned_material_shortages import run_planned_material_shortages_check
from app.features.planning import batch_service
from app.features.planning import material_adapter as adapter
from tests.features.planning import test_material_adapter as materials

demand_world = materials.demand_world
base_demand_world = materials.base_demand_world
base_board_clients = materials.base_board_clients
demand_clients = materials.demand_clients
flask_app = materials.flask_app
TODAY = materials.TODAY


@pytest.fixture
def short_world(db, demand_world, monkeypatch):
    org_id, other_id, outputs = demand_world

    def build(lead_time_days, start=TODAY):
        _, _, _, own, sibling, _, _, batches = materials.prepare(db, demand_world)
        for batch in batches:
            batch.snapshot = {**batch.snapshot, "material_bindings": []}
            if batch.theoretical_ready_date is not None:  # the ready date moves with the start
                batch.theoretical_ready_date += start - batch.proposed_start_date
            batch.proposed_start_date = start
        sibling.name = "Molasses"  # another material: only the 5 kg lot is sugar
        own.supplier = "Moore Wilson's"
        db.add(Supplier(org_id=org_id, name="Moore Wilson's", lead_time_days=lead_time_days))
        db.flush()
        materials.trusted_boundary(monkeypatch)
        adapter.assess(db, org_id, {}, today=TODAY)
        return org_id, own, batches

    return build


def _shortages(db, org_id):
    return [short for batch in materials.results(db, org_id) for short in batch["shortages"]]


def test_a_shortage_says_who_to_order_from_and_by_when(db, short_world):
    org_id, _, _ = short_world(3, start=TODAY + timedelta(days=10))
    (short,) = _shortages(db, org_id)
    assert (short["material"], short["quantity"], short["unit"]) == ("Sugar", "1", "kg")  # not 1000 g
    assert short["supplier"] == "Moore Wilson's" and short["lead_time_days"] == 3
    assert short["order_by"] == (TODAY + timedelta(days=7)).isoformat() and short["order_now"] is False


def test_an_order_by_date_that_has_come_says_order_now(db, short_world):
    org_id, _, _ = short_world(3)
    (short,) = _shortages(db, org_id)
    assert short["order_by"] == (TODAY - timedelta(days=3)).isoformat() and short["order_now"] is True


def test_without_a_lead_time_the_supplier_is_still_named(db, short_world):
    org_id, _, _ = short_world(None)
    (short,) = _shortages(db, org_id)
    assert short["supplier"] == "Moore Wilson's" and short["order_by"] is None and short["order_now"] is False


def test_a_shortage_becomes_a_notification_due_on_its_order_by_date(db, short_world):
    org_id, _, _ = short_world(3, start=TODAY + timedelta(days=10))
    result = run_planned_material_shortages_check(org_id, db)
    (alert,) = result.data["system_alerts"]
    assert alert["title"] == "Order 1 kg of Sugar"
    assert alert["due_date"] == (TODAY + timedelta(days=7)).isoformat()
    assert "Order from Moore Wilson's by" in alert["description"] and "3-day lead time" in alert["description"]
    assert alert["href"] == "/core/planner/board" and alert["area"] == "Production"
    assert result.flagged is False  # not late yet


def test_an_order_already_late_flags_system_health(db, short_world):
    org_id, _, _ = short_world(3)
    assert run_planned_material_shortages_check(org_id, db).flagged is True


def test_a_stale_check_raises_no_notification(db, short_world):
    org_id, _, batches = short_world(3)
    batches[2].revision += 1  # rescheduled since the check
    db.flush()
    assert run_planned_material_shortages_check(org_id, db).data["system_alerts"] == []


@pytest.mark.parametrize(("raw", "stored"), [("5", 5), (0, 0), ("", None), (None, None), (365, 365)])
def test_supplier_lead_time_is_whole_days_up_to_a_year(raw, stored):
    assert suppliers.clean_fields({"lead_time_days": raw})["lead_time_days"] == stored


@pytest.mark.parametrize("raw", [-1, 366, "1.5", "two", True, 2.5])
def test_a_bad_lead_time_is_refused(raw):
    with pytest.raises(suppliers.SupplierError, match="whole number of days"):
        suppliers.clean_fields({"lead_time_days": raw})


def test_a_lead_time_change_is_recorded_with_what_changed(db, demand_world, flask_app):
    from app.core.db.models.entity_event import EntityEvent

    org_id = demand_world[0]
    with flask_app.test_request_context():
        created = suppliers.create_supplier(db, org_id, None, {"name": "Davis Trading", "lead_time_days": "4"})
        assert created["lead_time_days"] == 4
        updated = suppliers.update_supplier(db, org_id, None, batch_service._id(created["id"]), {"lead_time_days": 0})
    assert updated["lead_time_days"] == 0  # zero is a lead time, not a blank
    (change,) = db.query(EntityEvent).filter(EntityEvent.org_id == org_id, EntityEvent.event_type == "supplier.updated")
    assert change.diff == {"lead_time_days": {"before": 4, "after": 0}}
    db.query(EntityEvent).filter(EntityEvent.org_id == org_id).delete(synchronize_session=False)
    db.query(Supplier).filter(Supplier.org_id == org_id).delete(synchronize_session=False)
    db.commit()


@pytest.fixture
def held_client(db, base_board_clients, monkeypatch):
    """A signed-in business whose 5 kg of sugar is held: 2 kg for each of two planned batches."""
    client, org_id, output = base_board_clients[0]
    step = db.query(Step).filter(Step.org_id == org_id).one()
    step.inputs = [{"name": "Sugar", "quantity": "2", "unit": "kg"}]
    lot = materials.lot(db, org_id)
    materials.fixtures.native_recipe(db, org_id, step.process_id)
    batch_service.save_setting(
        db, org_id, step.process_id, materials.fixtures.setting_payload(db, org_id, output, material_lots=[])
    )
    from app.features.planning import demand_service

    demand = demand_service.create_demand(
        db, org_id, materials.fixtures.payload(output, due_date=(TODAY + timedelta(days=2)).isoformat())
    )
    batch_service.plan_demand(db, org_id, demand.id, {}, today=TODAY)
    materials.trusted_boundary(monkeypatch)
    adapter.assess(db, org_id, {}, today=TODAY)
    db.commit()
    yield client, org_id, lot
    db.rollback()
    ids = [row[1] for row in base_board_clients]
    for model in (
        materials.PlanningMaterialBatchAssessment,
        materials.PlanningMaterialAssessment,  # its commitments go with it
        materials.InventoryMovement,
        materials.InventoryItem,
    ):
        db.query(model).filter(model.org_id.in_(ids)).delete(synchronize_session=False)
    db.commit()


def test_the_lot_lists_what_planned_batches_hold_on_it(held_client):
    client, _, lot = held_client
    rows = client.get("/api/core/inventory?type=raw_material").get_json()["inventory_items"]
    (row,) = [item for item in rows if item["id"] == str(lot.id)]
    assert [(hold["quantity"], hold["unit"]) for hold in row["committed"]] == [("2", "kg"), ("2", "kg")]
    assert row["committed"][0]["batch"].endswith("batch 1")


def test_disposing_into_a_hold_warns_but_isnt_blocked(held_client):
    client, _, lot = held_client
    page = client.get(f"/core/inventory/dispose/confirm?inventory_item_id={lot.id}&quantity_wasted=4")
    text = page.get_data(as_text=True)
    assert page.status_code == 200 and "Planned batches hold 4 kg of this lot" in text
    assert "check materials on the Production board" in text
    # Disposing only what's free says nothing.
    page = client.get(f"/core/inventory/dispose/confirm?inventory_item_id={lot.id}&quantity_wasted=1")
    assert "Planned batches hold" not in page.get_data(as_text=True)
