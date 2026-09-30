"""Raw owner policy and trusted server scope; customer receipts are not enabled."""

from dataclasses import FrozenInstanceError, replace
from queue import Queue
from threading import Event, Thread
from time import monotonic, sleep
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.features.contract_manufacturing.services.materials import (
    ExecutionMaterialScope,
    MaterialScopeError,
    resolve_execution_material_scope,
    validate_execution_materials,
    validate_material_owner,
)
from app.features.contract_manufacturing.services.orders import ContractOrderService
from tests.factories import ExecutionFactory, InventoryItemFactory, ProcessFactory
from tests.test_compliant_routes import flask_app  # noqa: F401 -- fixture
from tests.test_contract_orders import _customer, _order, world  # noqa: F401 -- fixture


@pytest.mark.parametrize(
    "policy,owner,allowed",
    [
        ("producer", "producer", True),
        ("producer", "customer", False),
        ("producer", "other", False),
        ("customer", "producer", False),
        ("customer", "customer", True),
        ("customer", "other", False),
        ("mixed", "producer", True),
        ("mixed", "customer", True),
        ("mixed", "other", False),
    ],
)
def test_raw_material_sources(policy, owner, allowed):
    scope = ExecutionMaterialScope(uuid4(), uuid4(), uuid4(), uuid4(), uuid4(), policy)
    owner_id = {"producer": None, "customer": scope.customer_id, "other": uuid4()}[owner]
    if allowed:
        validate_material_owner(scope, scope.org_id, owner_id, "raw_material")
    else:
        with pytest.raises(MaterialScopeError):
            validate_material_owner(scope, scope.org_id, owner_id, "raw_material")


def test_unassigned_execution_cannot_use_customer_stock():
    scope = ExecutionMaterialScope(uuid4(), uuid4(), None, None, None, "producer")
    validate_material_owner(scope, scope.org_id, None, "raw_material")
    with pytest.raises(MaterialScopeError):
        validate_material_owner(scope, scope.org_id, uuid4(), "raw_material")


@pytest.mark.parametrize("kind", ["work_in_progress", "final_product"])
@pytest.mark.parametrize("policy", ["producer", "customer", "mixed"])
def test_finished_and_intermediate_title_independent_of_raw_source(kind, policy):
    scope = ExecutionMaterialScope(uuid4(), uuid4(), uuid4(), uuid4(), uuid4(), policy)
    validate_material_owner(scope, scope.org_id, None, kind)
    with pytest.raises(MaterialScopeError, match="intermediate or finished"):
        validate_material_owner(scope, scope.org_id, scope.customer_id, kind)


def test_scope_is_frozen_and_unknown_facts_fail_closed():
    scope = ExecutionMaterialScope(uuid4(), uuid4(), uuid4(), uuid4(), uuid4(), "mixed")
    with pytest.raises(FrozenInstanceError):
        scope.customer_id = uuid4()
    for changed_scope, org, owner, kind in [
        (scope, uuid4(), None, "raw_material"),
        (scope, scope.org_id, str(scope.customer_id), "raw_material"),
        (replace(scope, materials_source="unknown"), scope.org_id, None, "work_in_progress"),
        (scope, scope.org_id, None, "unknown"),
    ]:
        with pytest.raises(MaterialScopeError):
            validate_material_owner(changed_scope, org, owner, kind)


def _batch(db, org_id):
    process = ProcessFactory(org_id=org_id)
    execution = ExecutionFactory(org_id=org_id, process_id=process.id)
    db.commit()
    return execution


def test_scope_comes_from_scoped_execution_assignment(db, world):  # noqa: F811
    org = world["orgs"][0]
    customer = _customer(world["clients"][0])
    order = _order(world["clients"][0], customer["id"])
    execution = _batch(db, org.id)
    scope = resolve_execution_material_scope(db, org.id, execution.id)
    assert scope.customer_id is None and scope.materials_source == "producer"
    service = ContractOrderService(db, org.id)
    service.link_batch(order["id"], order["lines"][0]["id"], execution.id)
    scope = resolve_execution_material_scope(db, org.id, execution.id)
    assert scope == ExecutionMaterialScope(
        org.id, execution.id, UUID(order["id"]), UUID(order["lines"][0]["id"]), UUID(customer["id"]), "mixed"
    )
    service.unlink_batch(order["id"], order["lines"][0]["id"], execution.id)
    assert resolve_execution_material_scope(db, org.id, execution.id).customer_id is None


def test_unassigned_preflight_serializes_with_concurrent_assignment(db, world):  # noqa: F811
    org_id = world["orgs"][0].id
    customer = _customer(world["clients"][0])
    order = _order(world["clients"][0], customer["id"])
    execution_id = _batch(db, org_id).id
    db.commit()
    bind = db.get_bind()
    result = Queue()
    finished = Event()
    with Session(bind) as preflight:
        scope = resolve_execution_material_scope(preflight, org_id, execution_id)
        assert scope.customer_id is None
        blocker_pid = preflight.execute(text("SELECT pg_backend_pid()")).scalar_one()

        def link():
            with Session(bind) as writer:
                try:
                    writer.execute(text("SET LOCAL lock_timeout = '5s'"))
                    result.put(writer.execute(text("SELECT pg_backend_pid()")).scalar_one())
                    ContractOrderService(writer, org_id).link_batch(order["id"], order["lines"][0]["id"], execution_id)
                    writer.commit()
                    result.put(None)
                except Exception as error:
                    result.put(error)
                finally:
                    finished.set()

        worker = Thread(target=link)
        worker.start()
        try:
            writer_pid = result.get(timeout=5)
            deadline = monotonic() + 3
            while monotonic() < deadline:
                blockers = preflight.execute(text("SELECT pg_blocking_pids(:pid)"), {"pid": writer_pid}).scalar_one()
                if blocker_pid in blockers:
                    break
                sleep(0.01)
            assert blocker_pid in blockers, "Assignment must wait for the complete preflight transaction"
            assert not finished.is_set()
            with pytest.raises(MaterialScopeError):
                validate_material_owner(scope, org_id, UUID(customer["id"]), "raw_material")
        finally:
            preflight.rollback()
            worker.join(timeout=6)
        assert not worker.is_alive()
        assert result.get(timeout=1) is None
        fresh = resolve_execution_material_scope(preflight, org_id, execution_id)
        assert fresh.customer_id == UUID(customer["id"])


def test_foreign_execution_and_untrusted_org_cannot_resolve_scope(db, world):  # noqa: F811
    org = world["orgs"][0]
    foreign = _batch(db, world["orgs"][1].id)
    for org_id, batch_id in [(org.id, foreign.id), (org.id, uuid4()), (str(org.id), foreign.id)]:
        with pytest.raises(MaterialScopeError) as error:
            resolve_execution_material_scope(db, org_id, batch_id)
        assert error.value.status in {403, 404}


def test_cancelled_order_has_no_production_authority(db, world):  # noqa: F811
    org = world["orgs"][0]
    customer = _customer(world["clients"][0])
    order = _order(world["clients"][0], customer["id"])
    execution = _batch(db, org.id)
    service = ContractOrderService(db, org.id)
    service.link_batch(order["id"], order["lines"][0]["id"], execution.id)
    service.update_order(order["id"], {"status": "cancelled"})
    with pytest.raises(MaterialScopeError, match="confirmed order"):
        resolve_execution_material_scope(db, org.id, execution.id)


def test_preflight_rejects_all_foreign_inputs_before_any_quantity_write(db, world):  # noqa: F811
    org = world["orgs"][0]
    execution = _batch(db, org.id)
    own = InventoryItemFactory(org_id=org.id, quantity="5")
    foreign = InventoryItemFactory(org_id=world["orgs"][1].id, quantity="7")
    db.commit()
    for inputs, outputs in [
        ([{"inventory_item_id": str(own.id)}, {"inventory_item_id": str(foreign.id)}], []),
        ([{"inventory_item_id": str(own.id)}], [{"untracked_item_id": str(foreign.id)}]),
    ]:
        with pytest.raises(MaterialScopeError, match="not found"):
            validate_execution_materials(db, org.id, execution.id, inputs, outputs)
        db.refresh(own)
        db.refresh(foreign)
        assert own.quantity == 5 and foreign.quantity == 7


def test_producer_preflight_does_not_enable_customer_receipts(db, world):  # noqa: F811
    org = world["orgs"][0]
    execution = _batch(db, org.id)
    lot = InventoryItemFactory(org_id=org.id, quantity="5")
    db.commit()
    scope = validate_execution_materials(db, org.id, execution.id, [{"inventory_item_id": str(lot.id)}], [])
    assert scope.customer_id is None
    assert not org.contract_materials_enabled
    db.refresh(lot)
    assert lot.quantity == 5


@pytest.mark.parametrize(
    "inputs,outputs", [({}, []), ([None], []), ([], [False]), ([], [{"untracked_item_id": "bad"}])]
)
def test_malformed_selection_rejected(db, world, inputs, outputs):  # noqa: F811
    execution = _batch(db, world["orgs"][0].id)
    with pytest.raises(ValueError):
        validate_execution_materials(db, execution.org_id, execution.id, inputs, outputs)
