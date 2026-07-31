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

from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

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


def test_raw_sql_insert_outside_guard_is_rejected_by_postgres_trigger(db, org):
    """AC11: the DB trigger holds even when SQLAlchemy's own event pipeline never runs.

    Every test above proves the Python-side halves of the guard (before_flush,
    the repository paths). None of them prove the PostgreSQL trigger itself — the
    layer that is the only thing standing between a raw INSERT/UPDATE (a bulk-load
    script, a `psql` session, a driver that doesn't fire SQLAlchemy events) and an
    untracked quantity change. `engine.raw_connection()` returns the underlying DBAPI
    connection with no `before_execute` listener attached, so a statement run through
    its cursor genuinely bypasses the ORM and the engine-level GUC sync alike — only
    the trigger's own `current_setting('app.inventory_qty_guard')` default of '0' is
    left standing between this INSERT and the table.
    """
    engine = db.get_bind()
    if getattr(engine.dialect, "name", None) != "postgresql":
        pytest.skip("the quantity guard trigger is PostgreSQL-only")

    item_id = uuid4()
    now = datetime.now(UTC)
    raw_conn = engine.raw_connection()
    try:
        cur = raw_conn.cursor()
        with pytest.raises(Exception) as excinfo:
            cur.execute(
                """
                INSERT INTO inventory_items
                    (id, org_id, name, quantity, unit, inventory_type, created_at, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (str(item_id), str(org.id), "Bypass Attempt", "5", "kg", "raw_material", now, now),
            )
        assert "quantity INSERT blocked" in str(excinfo.value)
    finally:
        raw_conn.rollback()
        raw_conn.close()

    # The rejected statement never reached the table.
    assert db.get(InventoryItem, item_id) is None


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
