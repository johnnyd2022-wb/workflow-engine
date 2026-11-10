"""Live-cogs 8.1a: cost_flows hooks, output identity and the backfill.

Spec .agents/specs/live-cogs.md, "cost_flows" and AC36 / AC37 / AC41 / AC52. Written before the
implementation.
"""

from decimal import Decimal
from uuid import UUID, uuid4

import pytest

from app.core.db.models.inventory_item import InventoryItem
from app.core.db.repositories.inventory_repo import InventoryRepository
from tests.costing_helpers import (
    D,
    complete,
    flows,
    lot,
    new_org,
    output_defs,
    produced_lots,
    purge,
    user_client,
    workflow,
)
from tests.test_compliant_routes import flask_app  # noqa: F401 -- fixture re-export


@pytest.fixture
def world(db, flask_app):  # noqa: F811
    org = new_org(db)
    client = user_client(db, flask_app, org)
    yield org, client
    purge(db, org)


def _all_flows(db, org_id):
    from app.features.costing.models import CostFlow

    db.expire_all()
    return db.query(CostFlow).filter(CostFlow.org_id == org_id).all()


def _shape(rows):
    return sorted((r.kind, D(str(r.quantity))) for r in rows)


# --- AC36: hooks ------------------------------------------------------------------------


def test_ac36_add_inventory_api_writes_one_created_flow(world, db):
    org, client = world
    response = client.post(
        "/api/core/inventory", json={"name": "Juniper", "quantity": "5", "unit": "kg", "inventory_type": "raw_material"}
    )
    assert response.status_code in (200, 201), response.get_json()
    item_id = UUID(response.get_json()["id"])
    (row,) = flows(db, org.id, item_id)
    assert (row.direction, row.kind, D(str(row.quantity))) == ("in", "created", D("5"))
    assert row.source_key == f"create:{item_id}" and row.reconstructed is False


def test_ac36_add_quantity_writes_added_flow_only_when_it_rises(world, db):
    org, _ = world
    item = lot(db, org.id, "Juniper", 2, "kg")
    repo = InventoryRepository(db)
    repo.add_quantity_to_inventory_item(item.id, org.id, "3")
    repo.add_quantity_to_inventory_item(item.id, org.id, "0")
    db.commit()
    assert _shape(flows(db, org.id, item.id)) == [("added", D("3")), ("created", D("2"))]
    (added,) = flows(db, org.id, item.id, kind="added")
    from app.core.db.models.entity_event import EntityEvent

    (event,) = (
        db.query(EntityEvent)
        .filter(EntityEvent.entity_id == item.id, EntityEvent.event_type == "inventory_item.quantity_adjusted")
        .all()
    )
    assert added.source_key == f"add:{event.id}"


def test_ac36_rolled_back_stock_write_leaves_no_flow(world, db):
    org, _ = world
    repo = InventoryRepository(db)
    item = repo.create_inventory_item(
        org_id=org.id, name="Ghost", quantity="1", unit="kg", inventory_type="raw_material", commit=False
    )
    item_id = item.id
    db.rollback()
    assert db.get(InventoryItem, item_id) is None
    assert flows(db, org.id, item_id) == []


def test_ac36_step_completion_writes_consumed_and_produced(world, db):
    org, client = world
    juniper = lot(db, org.id, "Juniper", 1, "kg")
    spirit = lot(db, org.id, "Spirit", 10, "L")
    execution, (step,) = workflow(db, org.id, [[{"name": "Gin", "unit": "bottles"}]])
    complete(
        client,
        execution,
        step,
        # the same lot used by two inputs is summed; 500 g of a kg lot is 0.5 kg
        [(juniper, 300, "g"), (juniper, 200, "g"), (spirit, 10, "L")],
        [{"name": "Gin", "quantity": 20, "unit": "bottles"}],
    )
    (consumed_juniper,) = flows(db, org.id, juniper.id, kind="consumed")
    assert D(str(consumed_juniper.quantity)) == D("0.5")
    assert consumed_juniper.direction == "out" and consumed_juniper.execution_step_id == step.id
    assert consumed_juniper.source_key == f"consume:{step.id}:{juniper.id}"
    (gin,) = produced_lots(db, org.id, step.id)
    (produced,) = flows(db, org.id, gin.id)
    assert (produced.kind, D(str(produced.quantity)), produced.execution_id) == ("produced", D("20"), execution.id)
    assert produced.step_number == 1


def test_ac41_flows_are_written_with_the_feature_off(db, flask_app):  # noqa: F811
    org = new_org(db, grant=False)
    client = user_client(db, flask_app, org)
    try:
        spirit = lot(db, org.id, "Spirit", 10, "L")
        execution, (step,) = workflow(db, org.id, [[{"name": "Gin", "unit": "L"}]])
        complete(client, execution, step, [(spirit, 10, "L")], [{"name": "Gin", "quantity": 10, "unit": "L"}])
        rows = sorted(
            (r.direction, r.kind, D(str(r.quantity)), r.source_key.split(":")[0]) for r in _all_flows(db, org.id)
        )
        assert rows == [
            ("in", "created", D("10"), "create"),
            ("in", "produced", D("10"), "create"),
            ("out", "consumed", D("10"), "consume"),
        ]
        from app.core.db.repositories.inventory_repo import InventoryRepository as Repo

        Repo(db).add_quantity_to_inventory_item(spirit.id, org.id, "2")
        db.commit()
        assert [r.kind for r in flows(db, org.id, spirit.id, kind="added")] == ["added"]
    finally:
        purge(db, org)


# --- AC52: output identity ------------------------------------------------------------


def test_ac52_output_id_sent_by_client_is_stored(world, db):
    org, client = world
    execution, (step,) = workflow(db, org.id, [[{"name": "Gin", "unit": "bottles"}]])
    (definition,) = output_defs(step)
    complete(
        client, execution, step, [], [{"name": "Gin", "quantity": 5, "unit": "bottles", "output_id": definition["id"]}]
    )
    (gin,) = produced_lots(db, org.id, step.id)
    assert str(gin.source_output_id) == definition["id"]
    (row,) = flows(db, org.id, gin.id)
    assert str(row.source_output_id) == definition["id"]


def test_ac52_unique_name_resolves_to_definition_id(world, db):
    org, client = world
    execution, (step,) = workflow(db, org.id, [[{"name": "Gin", "unit": "bottles"}]])
    (definition,) = output_defs(step)
    complete(client, execution, step, [], [{"name": " Gin ", "quantity": 5, "unit": "bottles"}])
    (gin,) = produced_lots(db, org.id, step.id)
    assert str(gin.source_output_id) == definition["id"]


def test_ac52_duplicate_names_resolve_to_null(world, db):
    org, client = world
    execution, (step,) = workflow(db, org.id, [[{"name": "Gin", "unit": "bottles"}, {"name": "Gin", "unit": "L"}]])
    complete(client, execution, step, [], [{"name": "Gin", "quantity": 5, "unit": "bottles"}])
    (gin,) = produced_lots(db, org.id, step.id)
    assert gin.source_output_id is None


def test_ac52_renamed_definition_still_matches_by_id(world, db):
    org, client = world
    execution, (step,) = workflow(db, org.id, [[{"name": "Gin", "unit": "bottles"}]])
    (definition,) = output_defs(step)
    complete(
        client,
        execution,
        step,
        [],
        [{"name": "Gin (old name)", "quantity": 5, "unit": "bottles", "output_id": definition["id"]}],
    )
    (gin,) = produced_lots(db, org.id, step.id)
    assert str(gin.source_output_id) == definition["id"]


def test_ac52_undeclared_output_id_is_rejected(world, db):
    org, client = world
    execution, (step,) = workflow(db, org.id, [[{"name": "Gin", "unit": "bottles"}]])
    response = complete(
        client,
        execution,
        step,
        [],
        [{"name": "Gin", "quantity": 5, "unit": "bottles", "output_id": str(uuid4())}],
        expect=400,
    )
    assert response.status_code == 400
    assert produced_lots(db, org.id, step.id) == []


def test_ac52_library_stock_line_has_no_output_id(world, db):
    org, client = world
    execution, (step,) = workflow(db, org.id, [[{"name": "Gin", "unit": "bottles"}]])
    complete(
        client, execution, step, [], [{"name": "Gin", "quantity": 5, "unit": "bottles", "library_remainder_ml": "200"}]
    )
    lots = {i.name: i for i in produced_lots(db, org.id, step.id)}
    assert lots["Gin"].source_output_id is not None
    assert lots["Gin - Library stock"].source_output_id is None


# --- AC37: backfill ----------------------------------------------------------------------


def _wipe_flows(db, org_id):
    from app.features.costing.models import CostFlow

    db.query(CostFlow).filter(CostFlow.org_id == org_id).delete()
    db.commit()


def test_ac37_backfill_reconstructs_worked_examples_and_is_idempotent(world, db):
    from app.features.costing.backfill import backfill_flows

    org, client = world
    only = lot(db, org.id, "Create Only", 4, "kg")
    grown = lot(db, org.id, "Grown", 2, "kg")
    InventoryRepository(db).add_quantity_to_inventory_item(grown.id, org.id, "3")
    db.commit()
    execution, (step,) = workflow(db, org.id, [[{"name": "Out", "unit": "kg"}]])
    complete(client, execution, step, [(grown, 2, "kg")], [{"name": "Out", "quantity": 1, "unit": "kg"}])
    (out,) = produced_lots(db, org.id, step.id)
    live = {(r.source_key, r.kind, D(str(r.quantity))) for r in _all_flows(db, org.id)}

    _wipe_flows(db, org.id)
    first = backfill_flows(db, org.id)
    db.commit()
    rebuilt = _all_flows(db, org.id)
    assert all(r.reconstructed for r in rebuilt)
    assert {(r.source_key, r.kind, D(str(r.quantity))) for r in rebuilt} == live
    assert _shape(flows(db, org.id, only.id)) == [("created", D("4"))]
    assert _shape(flows(db, org.id, grown.id)) == [("added", D("3")), ("consumed", D("2")), ("created", D("2"))]
    assert _shape(flows(db, org.id, out.id)) == [("produced", D("1"))]
    assert first["inserted"] == len(rebuilt)

    snapshot = sorted((str(r.id), r.source_key) for r in _all_flows(db, org.id))
    assert backfill_flows(db, org.id)["inserted"] == 0
    db.commit()
    assert sorted((str(r.id), r.source_key) for r in _all_flows(db, org.id)) == snapshot
    later = lot(db, org.id, "Later", 1, "kg")
    assert backfill_flows(db, org.id)["inserted"] == 0
    db.commit()
    assert len(flows(db, org.id, later.id)) == 1


def test_ac37_backfill_without_created_event_uses_current_plus_consumed(world, db):
    """A lot from before events existed (factory-made, no entity event): created quantity =
    current on-hand + what steps consumed from it."""
    from app.features.costing.backfill import backfill_flows
    from tests.factories import InventoryItemFactory

    org, client = world
    from sqlalchemy import text

    from app.core.db.models.entity_event import EntityEvent

    old = InventoryItemFactory(org_id=org.id, name="Old Spirit", quantity="10", unit="L", inventory_type="raw_material")
    db.commit()
    execution, (step,) = workflow(db, org.id, [[{"name": "Out", "unit": "L"}]])
    complete(client, execution, step, [(old, 4, "L")], [{"name": "Out", "quantity": 4, "unit": "L"}])
    _wipe_flows(db, org.id)
    # Make it a genuine legacy lot: no created event to read the original quantity from.
    db.execute(text("SELECT set_config('app.migration_mode','1',true)"))
    db.execute(
        text("DELETE FROM entity_events WHERE entity_id = :id AND event_type = 'inventory_item.created'"),
        {"id": old.id},
    )
    db.commit()
    assert (
        db.query(EntityEvent)
        .filter(EntityEvent.entity_id == old.id, EntityEvent.event_type == "inventory_item.created")
        .count()
        == 0
    )
    backfill_flows(db, org.id)
    db.commit()
    (created,) = flows(db, org.id, old.id, kind="created")
    assert D(str(created.quantity)) == D("10"), "6 on hand + 4 consumed"


def test_ac37_backfill_is_org_scoped(world, db):
    from app.features.costing.backfill import backfill_flows

    org, _ = world
    other = new_org(db)
    try:
        mine = lot(db, org.id, "Mine", 1, "kg")
        lot(db, other.id, "Theirs", 1, "kg")
        _wipe_flows(db, org.id)
        _wipe_flows(db, other.id)
        assert backfill_flows(db, org.id)["inserted"] == 1
        db.commit()
        assert [r.inventory_item_id for r in _all_flows(db, org.id)] == [mine.id]
        assert _all_flows(db, other.id) == []
    finally:
        purge(db, other)


def test_ac36_flows_cascade_when_a_lot_is_deleted(world, db):
    org, _ = world
    item = lot(db, org.id, "Temporary", 1, "kg")
    item_id = item.id
    db.delete(db.get(InventoryItem, item_id))
    db.commit()
    assert flows(db, org.id, item_id) == []


def test_source_key_is_unique_per_org(world, db):
    from sqlalchemy.exc import IntegrityError

    from app.features.costing.models import CostFlow

    org, _ = world
    item = lot(db, org.id, "Keyed", 1, "kg")
    (row,) = flows(db, org.id, item.id)
    db.add(
        CostFlow(
            org_id=org.id,
            inventory_item_id=item.id,
            direction="in",
            kind="added",
            quantity=Decimal("1"),
            source_key=row.source_key,
            write_reason="test",
            reconstructed=False,
        )
    )
    with pytest.raises(IntegrityError, match="uq_cost_flows_source_key"):
        db.flush()
    db.rollback()


def test_flow_kinds_are_constrained(world, db):
    from sqlalchemy.exc import IntegrityError

    from app.features.costing.models import CostFlow

    org, _ = world
    item = lot(db, org.id, "Checked", 1, "kg")
    db.add(
        CostFlow(
            org_id=org.id,
            inventory_item_id=item.id,
            direction="in",
            kind="teleported",
            quantity=Decimal("1"),
            source_key=f"x:{uuid4()}",
            write_reason="test",
            reconstructed=False,
        )
    )
    with pytest.raises(IntegrityError):
        db.flush()
    db.rollback()
    db.add(
        CostFlow(
            org_id=org.id,
            inventory_item_id=item.id,
            direction="in",
            kind="created",
            quantity=Decimal("0"),
            source_key=f"x:{uuid4()}",
            write_reason="test",
            reconstructed=False,
        )
    )
    with pytest.raises(IntegrityError):
        db.flush()
    db.rollback()


def test_ac36_failed_step_completion_leaves_no_consumed_flow(world, db):
    """A completion that fails after the stock checks (here: an undeclared output_id) writes
    neither the stock decrement nor any flow."""
    org, client = world
    spirit = lot(db, org.id, "Spirit", 10, "L")
    execution, (step,) = workflow(db, org.id, [[{"name": "Gin", "unit": "L"}]])
    complete(
        client,
        execution,
        step,
        [(spirit, 4, "L")],
        [{"name": "Gin", "quantity": 4, "unit": "L", "output_id": str(uuid4())}],
        expect=400,
    )
    db.expire_all()
    assert D(str(db.get(InventoryItem, spirit.id).quantity)) == D("10")
    assert flows(db, org.id, spirit.id, kind="consumed") == []
