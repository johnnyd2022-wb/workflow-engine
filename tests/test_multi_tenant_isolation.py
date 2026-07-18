"""Tenant-isolation tests for the org-scoped repositories.

Multi-tenancy is the product's core security boundary: every row carries an org_id and no
org may read or mutate another org's data. Until now nothing proved it — the seeded
two-org world (`two_org_two_user`) existed but no test used it, and the one file named
`test_multi_tenant_api.py` is a manual `main()` script, not a pytest suite. These tests are
the automated proof, exercised through the same repository methods the routes call.

Each resource is checked two ways that must both hold: a request from org A for org B's
record returns nothing / does not act (the hostile-neighbour case), AND the same request
for org A's own record succeeds (the control — so the test proves scoping, not a blanket
deny that would pass vacuously).

Wastage isolation is covered in Batch 3 alongside the wastage factory.
"""

import pytest

from app.core.db.models.execution import Execution
from app.core.db.models.inventory_item import InventoryItem
from app.core.db.models.process import Process
from app.core.db.repositories.execution_repo import ExecutionRepository
from app.core.db.repositories.inventory_repo import InventoryRepository
from app.core.db.repositories.process_repo import ProcessRepository
from tests.factories import ExecutionFactory, InventoryItemFactory, ProcessFactory


@pytest.fixture
def world(db, two_org_two_user):
    """The two-org world plus one process, execution and inventory item in each org."""
    org_a = two_org_two_user["org_a"]
    org_b = two_org_two_user["org_b"]

    process_a = ProcessFactory(org_id=org_a.id)
    process_b = ProcessFactory(org_id=org_b.id)
    execution_a = ExecutionFactory(org_id=org_a.id, process_id=process_a.id)
    execution_b = ExecutionFactory(org_id=org_b.id, process_id=process_b.id)
    item_a = InventoryItemFactory(org_id=org_a.id)
    item_b = InventoryItemFactory(org_id=org_b.id)
    db.commit()

    yield {
        "org_a": org_a,
        "org_b": org_b,
        "process_a": process_a,
        "process_b": process_b,
        "execution_a": execution_a,
        "execution_b": execution_b,
        "item_a": item_a,
        "item_b": item_b,
    }

    # Clean children before two_org_two_user tears down the orgs (FK order). Roll back first
    # in case a test left the session mid-transaction.
    db.rollback()
    for org_id in (org_a.id, org_b.id):
        db.query(Execution).filter(Execution.org_id == org_id).delete(synchronize_session=False)
        db.query(InventoryItem).filter(InventoryItem.org_id == org_id).delete(synchronize_session=False)
        db.query(Process).filter(Process.org_id == org_id).delete(synchronize_session=False)
    db.commit()


# --- Process ---------------------------------------------------------------------------


def test_process_get_by_id_is_org_scoped(db, world):
    repo = ProcessRepository(db)
    # org A cannot fetch org B's process...
    assert repo.get_process_by_id(world["process_b"].id, world["org_a"].id) is None
    # ...but can fetch its own (control).
    own = repo.get_process_by_id(world["process_a"].id, world["org_a"].id)
    assert own is not None and own.id == world["process_a"].id


def test_process_list_excludes_other_org(db, world):
    listed = ProcessRepository(db).list_processes(world["org_a"].id)
    ids = {p.id for p in listed}
    assert world["process_a"].id in ids
    assert world["process_b"].id not in ids


def test_process_delete_is_org_scoped(db, world):
    repo = ProcessRepository(db)
    # org A's attempt to delete org B's process does nothing...
    assert repo.delete_process(world["process_b"].id, world["org_a"].id) is False
    db.commit()
    # ...and org B's process still exists.
    assert repo.get_process_by_id(world["process_b"].id, world["org_b"].id) is not None


# --- Execution -------------------------------------------------------------------------


def test_execution_get_by_id_is_org_scoped(db, world):
    repo = ExecutionRepository(db)
    assert repo.get_execution_by_id(world["execution_b"].id, world["org_a"].id) is None
    own = repo.get_execution_by_id(world["execution_a"].id, world["org_a"].id)
    assert own is not None and own.id == world["execution_a"].id


def test_execution_list_excludes_other_org(db, world):
    listed = ExecutionRepository(db).list_executions(world["org_a"].id)
    ids = {e.id for e in listed}
    assert world["execution_a"].id in ids
    assert world["execution_b"].id not in ids


# --- Inventory -------------------------------------------------------------------------


def test_inventory_get_by_id_is_org_scoped(db, world):
    repo = InventoryRepository(db)
    assert repo.get_inventory_item_by_id(world["item_b"].id, world["org_a"].id) is None
    own = repo.get_inventory_item_by_id(world["item_a"].id, world["org_a"].id)
    assert own is not None and own.id == world["item_a"].id


def test_inventory_list_excludes_other_org(db, world):
    listed = InventoryRepository(db).list_inventory_items(world["org_a"].id)
    ids = {i.id for i in listed}
    assert world["item_a"].id in ids
    assert world["item_b"].id not in ids
