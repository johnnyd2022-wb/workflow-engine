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


def test_ac41_reconciliation_flow_is_written_with_the_feature_off(db, flask_app):  # noqa: F811
    """AC41 names every live hook, not only create / consume / produce / add: reconciling an
    output into an untracked lot also writes its flow when the org has no costing feature."""
    org = new_org(db, grant=False)
    client = user_client(db, flask_app, org)
    try:
        spirit = lot(db, org.id, "Spirit", 6, "L")
        untracked = lot(
            db,
            org.id,
            "Gin Base",
            10,
            "L",
            inventory_type="work_in_progress",
            extra_data={"untracked": True, "remaining_balance_to_reconcile": "10"},
        )
        execution, (step,) = workflow(db, org.id, [[{"name": "Gin Base", "unit": "L"}]])
        complete(
            client,
            execution,
            step,
            [(spirit, 6, "L")],
            [{"name": "Gin Base", "quantity": 6, "unit": "L", "untracked_item_id": str(untracked.id)}],
        )
        (reconciled,) = flows(db, org.id, untracked.id, kind="reconciled_in")
        assert (reconciled.direction, D(str(reconciled.quantity))) == ("in", D("6"))
        assert reconciled.source_key == f"reconcile:{step.id}:{untracked.id}:0"
        assert (reconciled.execution_id, reconciled.execution_step_id) == (execution.id, step.id)
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


def test_created_kind_prefers_transfer_over_production_provenance():
    """Spec: a transfer destination copies production provenance, so it is `transfer_in` even
    though it also names a source step. Live hooks and the backfill both classify through this."""
    from types import SimpleNamespace

    from app.features.costing.flows import created_kind

    step_id, receipt_id = uuid4(), uuid4()
    both = SimpleNamespace(transfer_receipt_id=receipt_id, source_execution_step_id=step_id)
    assert created_kind(both) == "transfer_in"
    assert created_kind(SimpleNamespace(transfer_receipt_id=None, source_execution_step_id=step_id)) == "produced"
    assert created_kind(SimpleNamespace(transfer_receipt_id=None, source_execution_step_id=None)) == "created"


def test_ac37_backfill_fills_only_the_gaps_and_leaves_live_rows_alone(world, db):
    """A live row and a reconstructed one share a key space: the backfill rebuilds what is missing
    and never rewrites what a live hook already recorded (spec: "neither can duplicate the other")."""
    from app.core.utils.time import utc_now
    from app.features.costing.backfill import backfill_flows
    from app.features.costing.models import CostFlow

    org, _ = world
    item = lot(db, org.id, "Mixed", 2, "kg")
    InventoryRepository(db).add_quantity_to_inventory_item(item.id, org.id, "3")
    db.commit()
    (live_added,) = flows(db, org.id, item.id, kind="added")
    live_added_id, live_added_reason = live_added.id, live_added.write_reason
    (live_created,) = flows(db, org.id, item.id, kind="created")
    db.query(CostFlow).filter(CostFlow.id == live_created.id).delete()
    db.commit()

    started = utc_now()
    assert backfill_flows(db, org.id)["inserted"] == 1
    db.commit()
    by_kind = {r.kind: r for r in flows(db, org.id, item.id)}
    created = by_kind["created"]
    assert (created.reconstructed, created.write_reason, D(str(created.quantity))) == (True, "backfill", D("2"))
    assert created.created_at >= started, "reconstructed rows are stamped when the backfill ran"
    added = by_kind["added"]
    assert (added.id, added.reconstructed, added.write_reason) == (live_added_id, False, live_added_reason)


def test_ac37_live_write_after_backfill_cannot_record_the_same_movement_twice(world, db):
    from app.features.costing.backfill import backfill_flows
    from app.features.costing.flows import FlowConflictError, create_key, insert_flow

    org, _ = world
    item = lot(db, org.id, "Twice", 4, "kg")
    _wipe_flows(db, org.id)
    backfill_flows(db, org.id)
    db.commit()
    (rebuilt,) = flows(db, org.id, item.id)
    rebuilt_id = rebuilt.id
    with pytest.raises(FlowConflictError):
        insert_flow(
            db,
            org_id=org.id,
            inventory_item_id=item.id,
            direction="in",
            kind="created",
            quantity=Decimal("4"),
            source_key=create_key(item.id),
            write_reason="test",
        )
    db.rollback()
    (still,) = flows(db, org.id, item.id)
    assert (still.id, still.reconstructed) == (rebuilt_id, True)


def test_ac37_backfill_does_not_turn_a_manual_correction_into_an_added_flow(world, db):
    """Only `add_quantity_to_inventory_item` writes an `added` flow live. A recount that raises a lot
    also emits a quantity_adjusted event with a positive delta, but under another reason."""
    from app.features.costing.backfill import backfill_flows

    org, _ = world
    item = lot(db, org.id, "Recounted", 2, "kg")
    InventoryRepository(db).set_inventory_item_quantity(item.id, org.id, "5")
    db.commit()
    assert _shape(flows(db, org.id, item.id)) == [("created", D("2"))], "the live hook ignores a recount"
    _wipe_flows(db, org.id)
    backfill_flows(db, org.id)
    db.commit()
    assert _shape(flows(db, org.id, item.id)) == [("created", D("2"))]


def test_ac37_backfill_sums_each_lot_across_inputs_in_the_lots_own_unit(world, db):
    from app.features.costing.backfill import backfill_flows

    org, client = world
    juniper = lot(db, org.id, "Juniper", 1, "kg")
    execution, (step,) = workflow(db, org.id, [[{"name": "Gin", "unit": "bottles"}]])
    complete(
        client,
        execution,
        step,
        [(juniper, 300, "g"), (juniper, 200, "g")],
        [{"name": "Gin", "quantity": 20, "unit": "bottles"}],
    )
    (live,) = flows(db, org.id, juniper.id, kind="consumed")
    live_key, live_quantity = live.source_key, D(str(live.quantity))
    _wipe_flows(db, org.id)
    backfill_flows(db, org.id)
    db.commit()
    (rebuilt,) = flows(db, org.id, juniper.id, kind="consumed")
    assert (rebuilt.source_key, D(str(rebuilt.quantity)), rebuilt.reconstructed) == (live_key, D("0.5"), True)
    assert live_quantity == D("0.5"), "the live hook and the backfill agree"


@pytest.mark.parametrize(
    "tamper",
    [
        pytest.param({"inventory_item_id": "not-a-uuid"}, id="malformed-lot-id"),
        pytest.param({"unit": "bottles"}, id="unit-that-cannot-convert"),
        pytest.param({"quantity": "0"}, id="zero-quantity"),
        pytest.param({"quantity": "plenty"}, id="non-numeric-quantity"),
        pytest.param(None, id="lot-since-deleted"),
    ],
)
def test_ac37_backfill_skips_and_counts_an_input_it_cannot_cost(world, db, tamper):
    """Spec: an input whose lot no longer exists, or whose unit can't convert, is skipped and
    counted in the command's output; the step's other inputs are still reconstructed."""
    from sqlalchemy.orm.attributes import flag_modified

    from app.core.db.models.execution_step import ExecutionStep
    from app.features.costing.backfill import backfill_flows

    org, client = world
    kept = lot(db, org.id, "Kept", 2, "kg")
    doomed = lot(db, org.id, "Doomed", 1, "kg")
    kept_id, doomed_id = kept.id, doomed.id
    execution, (step,) = workflow(db, org.id, [[{"name": "Gin", "unit": "L"}]])
    complete(
        client, execution, step, [(kept, 2, "kg"), (doomed, 1, "kg")], [{"name": "Gin", "quantity": 3, "unit": "L"}]
    )
    assert len(flows(db, org.id, doomed_id, kind="consumed")) == 1, "control: live recorded both inputs"

    if tamper is None:
        db.delete(db.get(InventoryItem, doomed_id))
    else:
        row = db.get(ExecutionStep, step.id)
        inputs = [dict(entry) for entry in row.actual_inputs]
        (target,) = [entry for entry in inputs if entry["inventory_item_id"] == str(doomed_id)]
        target.update(tamper)
        row.actual_inputs = inputs
        flag_modified(row, "actual_inputs")
    db.commit()
    _wipe_flows(db, org.id)

    result = backfill_flows(db, org.id)
    db.commit()
    assert result["skipped_inputs"] == 1
    consumed = [r for r in _all_flows(db, org.id) if r.kind == "consumed"]
    assert [(r.inventory_item_id, D(str(r.quantity))) for r in consumed] == [(kept_id, D("2"))]


def test_ac37_backfill_does_not_reconstruct_historical_reconciliations(world, db):
    """Spec: their untracked lots stay unknown and are listed as missing inputs."""
    from app.features.costing.backfill import backfill_flows

    org, client = world
    spirit = lot(db, org.id, "Spirit", 6, "L")
    untracked = lot(
        db,
        org.id,
        "Gin Base",
        10,
        "L",
        inventory_type="work_in_progress",
        extra_data={"untracked": True, "remaining_balance_to_reconcile": "10"},
    )
    execution, (step,) = workflow(db, org.id, [[{"name": "Gin Base", "unit": "L"}]])
    complete(
        client,
        execution,
        step,
        [(spirit, 6, "L")],
        [{"name": "Gin Base", "quantity": 6, "unit": "L", "untracked_item_id": str(untracked.id)}],
    )
    assert len(flows(db, org.id, untracked.id, kind="reconciled_in")) == 1, "control: live recorded it"
    _wipe_flows(db, org.id)
    backfill_flows(db, org.id)
    db.commit()
    assert [r for r in _all_flows(db, org.id) if r.kind == "reconciled_in"] == []
    assert _shape(flows(db, org.id, untracked.id)) == [("created", D("10"))]
    assert _shape(flows(db, org.id, spirit.id)) == [("consumed", D("6")), ("created", D("6"))]


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


# --- cost_flows schema: each CHECK / FK is a database rule, so each gets a row that breaks only it ------


def _schema_flow(db, org, item, step=None, **overrides):
    """A row the schema accepts, unless ``overrides`` break it. With ``step`` it names a real
    execution and step, so the composite FKs hold and only the rule under test can fire."""
    from app.features.costing.models import CostFlow

    fields = dict(
        org_id=org.id,
        inventory_item_id=item.id,
        direction="in",
        kind="created",
        quantity=Decimal("1"),
        source_key=f"schema:{uuid4()}",
        write_reason="test",
        reconstructed=False,
    )
    if step is not None:
        fields.update(execution_id=step.execution_id, execution_step_id=step.id, step_number=step.step_number)
    fields.update(overrides)
    return CostFlow(**fields)


def _assert_rejected(db, row, constraint):
    from sqlalchemy.exc import IntegrityError

    db.add(row)
    # Quoted, so "fk_cost_flows_execution" cannot also match "fk_cost_flows_execution_step".
    with pytest.raises(IntegrityError, match=f'"{constraint}"'):
        db.flush()
    db.rollback()


_INFLOW_KINDS = ["created", "added", "produced", "transfer_in", "reconciled_in"]
_EXECUTION_KINDS = [("produced", "in"), ("reconciled_in", "in"), ("consumed", "out")]


def test_cost_flow_schema_accepts_a_valid_row_of_every_kind(world, db):
    """Control for the rejection tests below: the helper's rows are valid until deliberately broken."""
    org, _ = world
    item = lot(db, org.id, "Control", 1, "kg")
    execution, (step,) = workflow(db, org.id, [[{"name": "Gin", "unit": "L"}]])
    for kind in _INFLOW_KINDS:
        db.add(_schema_flow(db, org, item, step, direction="in", kind=kind))
    db.add(_schema_flow(db, org, item, step, direction="out", kind="consumed"))
    db.add(_schema_flow(db, org, item, None, direction="in", kind="created"))  # no execution needed
    db.flush()
    db.rollback()


@pytest.mark.parametrize(
    ("direction", "kind"),
    [("out", kind) for kind in _INFLOW_KINDS] + [("in", "consumed")],
    ids=lambda value: str(value),
)
def test_cost_flow_direction_must_match_its_kind(world, db, direction, kind):
    org, _ = world
    item = lot(db, org.id, "Directed", 1, "kg")
    execution, (step,) = workflow(db, org.id, [[{"name": "Gin", "unit": "L"}]])
    # a full execution reference, so only the direction/kind rule can reject it
    _assert_rejected(db, _schema_flow(db, org, item, step, direction=direction, kind=kind), "ck_cost_flows_kind")


@pytest.mark.parametrize(
    "missing",
    [
        pytest.param(("execution_id", "execution_step_id"), id="no-execution"),
        pytest.param(("execution_step_id",), id="no-step"),
        pytest.param(("step_number",), id="no-step-number"),
    ],
)
@pytest.mark.parametrize(("kind", "direction"), _EXECUTION_KINDS)
def test_cost_flow_execution_kinds_must_name_execution_step_and_number(world, db, kind, direction, missing):
    org, _ = world
    item = lot(db, org.id, "Anchored", 1, "kg")
    execution, (step,) = workflow(db, org.id, [[{"name": "Gin", "unit": "L"}]])
    row = _schema_flow(db, org, item, step, direction=direction, kind=kind, **{name: None for name in missing})
    _assert_rejected(db, row, "ck_cost_flows_execution_kinds")


def test_cost_flow_step_needs_its_execution(world, db):
    """A kind that doesn't require execution fields can still not name a step without its execution."""
    org, _ = world
    item = lot(db, org.id, "Orphan Step", 1, "kg")
    execution, (step,) = workflow(db, org.id, [[{"name": "Gin", "unit": "L"}]])
    row = _schema_flow(db, org, item, step, direction="in", kind="created", execution_id=None, step_number=None)
    _assert_rejected(db, row, "ck_cost_flows_step_needs_execution")


def test_cost_flow_execution_must_belong_to_the_same_org(world, db):
    """The composite (org_id, execution_id) key: another org's execution is unrepresentable."""
    org, _ = world
    other = new_org(db)
    try:
        item = lot(db, org.id, "Mine", 1, "kg")
        theirs, _steps = workflow(db, other.id, [[{"name": "Gin", "unit": "L"}]])
        row = _schema_flow(db, org, item, None, direction="in", kind="created", execution_id=theirs.id)
        _assert_rejected(db, row, "fk_cost_flows_execution")
    finally:
        purge(db, other)


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


@pytest.mark.parametrize("occupied", ["cost_flows", "lot_cost_entries", "costing_settings"])
def test_migration_downgrade_refuses_every_costing_table(monkeypatch, occupied):
    import app.core.db.migrations.versions.costing_engine_001 as migration

    class _Result:
        def __init__(self, found):
            self.found = found

        def first(self):
            return (1,) if self.found else None

    class _Bind:
        def execute(self, statement):
            return _Result(f"FROM {occupied} " in str(statement))

    monkeypatch.setattr(migration.op, "get_bind", lambda: _Bind())
    monkeypatch.setattr(
        migration.op,
        "drop_table",
        lambda *_args, **_kwargs: pytest.fail("downgrade changed schema after finding data"),
    )

    with pytest.raises(RuntimeError, match=occupied):
        migration.downgrade()


def test_migration_creates_tenant_org_indexes_and_the_concurrent_step_key(db):
    """Checked on the migrated schema itself (round-tripped down/up in CI's migration job and
    locally): the TenantScoped org indexes exist, and the execution_steps key is a valid
    unique index attached as a constraint (built CONCURRENTLY, so never left invalid)."""
    from sqlalchemy import text

    names = {r[0] for r in db.execute(text("SELECT indexname FROM pg_indexes WHERE schemaname = 'public'"))}
    assert {"ix_cost_flows_org_id", "ix_lot_cost_entries_org_id", "ix_costing_settings_org_id"} <= names
    row = db.execute(
        text(
            "SELECT i.indisvalid, i.indisunique, con.contype FROM pg_index i "
            "JOIN pg_class c ON c.oid = i.indexrelid "
            "LEFT JOIN pg_constraint con ON con.conindid = i.indexrelid AND con.contype = 'u' "
            "WHERE c.relname = 'uq_execution_steps_org_execution_id'"
        )
    ).one()
    assert row == (True, True, "u")
