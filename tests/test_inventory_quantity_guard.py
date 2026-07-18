"""Tests for the inventory quantity-write guard (app/core/domain/inventory_quantity_guard.py).

The guard is the mechanism that prevents untracked mutations of inventory_items.quantity:
a `before_flush` listener raises InventoryQuantityWriteForbiddenError when an InventoryItem's
quantity changes outside an `allow_inventory_quantity_write(reason)` block. Every "the guard
protects us" claim elsewhere in the app rests on this behaviour, and until now nothing proved
it. These tests prove both halves: the guard blocks the unauthorized path, and it lets the
authorized repository paths through — and that it re-arms after each allowed block so a leaked
authorization can't silently permit the next write.

The guard is registered globally on the Session class at import of app.core.db, so it is
active for every session the test suite uses.
"""

from decimal import Decimal

import pytest

from app.core.db.models.inventory_item import InventoryItem
from app.core.db.models.organisation import Organisation
from app.core.db.repositories.inventory_repo import InventoryRepository
from app.core.domain.inventory_quantity_guard import (
    InventoryQuantityWriteForbiddenError,
    InventoryQuantityWriteReason,
    allow_inventory_quantity_write,
)
from tests.factories import InventoryItemFactory, OrganisationFactory


@pytest.fixture
def org(db):
    """A throwaway org, with all its inventory items cleaned up afterwards."""
    organisation = OrganisationFactory()
    db.commit()
    yield organisation
    # Roll back first: a test that asserted a guard rejection leaves the session mid-flush,
    # and the cleanup below must run on a clean session or it leaks the org into the next run.
    db.rollback()
    db.query(InventoryItem).filter(InventoryItem.org_id == organisation.id).delete(synchronize_session=False)
    db.query(Organisation).filter(Organisation.id == organisation.id).delete(synchronize_session=False)
    db.commit()


def test_direct_quantity_mutation_outside_allow_block_is_rejected(db, org):
    item = InventoryItemFactory(org_id=org.id, quantity="10")

    item.quantity = Decimal("999")
    with pytest.raises(InventoryQuantityWriteForbiddenError):
        db.flush()
    db.rollback()

    # The rejected change never reached the database.
    refreshed = db.get(InventoryItem, item.id)
    assert refreshed.quantity == Decimal("10")


def test_repository_create_path_writes_quantity(db, org):
    item = InventoryItemFactory(org_id=org.id, quantity="42")
    # REPOSITORY_CREATE is an authorized reason: the create committed with the quantity set.
    assert item.quantity == Decimal("42")


def test_repository_add_quantity_path_writes_quantity(db, org):
    item = InventoryItemFactory(org_id=org.id, quantity="10")

    updated = InventoryRepository(db).add_quantity_to_inventory_item(item.id, org.id, "5")

    assert updated is not None
    assert updated.quantity == Decimal("15")


def test_repository_set_quantity_path_writes_quantity(db, org):
    item = InventoryItemFactory(org_id=org.id, quantity="10")

    updated = InventoryRepository(db).set_inventory_item_quantity(item.id, org.id, "3")

    assert updated is not None
    assert updated.quantity == Decimal("3")


def test_nested_allow_block_is_rejected():
    with pytest.raises(RuntimeError, match="Nested"):
        with allow_inventory_quantity_write(InventoryQuantityWriteReason.MANUAL_API_UPDATE):
            with allow_inventory_quantity_write(InventoryQuantityWriteReason.MANUAL_API_UPDATE):
                pass


def test_guard_rearms_after_an_allowed_block(db, org):
    item = InventoryItemFactory(org_id=org.id, quantity="10")

    # An authorized write succeeds inside the block...
    with allow_inventory_quantity_write(InventoryQuantityWriteReason.MANUAL_API_UPDATE):
        item.quantity = Decimal("5")
        db.flush()
    db.commit()
    assert db.get(InventoryItem, item.id).quantity == Decimal("5")

    # ...and the guard is armed again the moment the block exits. If the authorization
    # token leaked, this second unguarded write would slip through and the test would fail.
    item.quantity = Decimal("7")
    with pytest.raises(InventoryQuantityWriteForbiddenError):
        db.flush()
    db.rollback()
    assert db.get(InventoryItem, item.id).quantity == Decimal("5")
