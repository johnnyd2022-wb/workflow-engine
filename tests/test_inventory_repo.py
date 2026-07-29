"""Repository-level tests for InventoryRepository.update_inventory_item and
delete_inventory_item (app/core/db/repositories/inventory_repo.py, lines 397-468) — the
two least-covered mutations on the repository per the coverage audit.

update_inventory_item has two distinct branches depending on whether `quantity` is
supplied: only the quantity branch touches inventory_items.quantity (through the
allow_inventory_quantity_write guard) and records a quantity diff; the other branch must
leave quantity untouched. delete_inventory_item's whole point is a tombstone
(inventory_item.deleted) written BEFORE the row is removed (spec AC6) — entity_events is
append-only and has no FK to inventory_items, so the event must still resolve, with the
pre-deletion snapshot, after the row is gone.
"""

from decimal import Decimal

import pytest

from app.core.db.models.entity_event import EntityEvent
from app.core.db.models.inventory_item import InventoryItem
from app.core.db.models.organisation import Organisation
from app.core.db.repositories.inventory_repo import InventoryRepository
from tests.factories import InventoryItemFactory, OrganisationFactory


@pytest.fixture
def org(db):
    organisation = OrganisationFactory()
    db.commit()
    org_id = organisation.id
    yield organisation
    db.rollback()
    db.query(EntityEvent).filter(EntityEvent.org_id == org_id).delete(synchronize_session=False)
    db.query(InventoryItem).filter(InventoryItem.org_id == org_id).delete(synchronize_session=False)
    db.query(Organisation).filter(Organisation.id == org_id).delete(synchronize_session=False)
    db.commit()


def _latest_event(db, entity_id, event_type):
    return (
        db.query(EntityEvent)
        .filter(EntityEvent.entity_id == entity_id, EntityEvent.event_type == event_type)
        .order_by(EntityEvent.created_at.desc())
        .first()
    )


# --- update_inventory_item: quantity supplied ---------------------------------------------


def test_update_inventory_item_with_quantity_changes_value_and_emits_diff(db, org):
    item = InventoryItemFactory(org_id=org.id, quantity="10", name="Widget")
    db.commit()

    updated = InventoryRepository(db).update_inventory_item(item.id, org.id, quantity="25")

    assert updated is not None
    assert updated.quantity == Decimal("25.0000")

    event = _latest_event(db, item.id, "inventory_item.updated")
    assert event is not None, "quantity branch must still emit inventory_item.updated"
    assert event.diff is not None
    assert event.diff["quantity"] == {"before": "10.0000", "after": "25.0000"}


def test_update_inventory_item_with_unchanged_quantity_omits_quantity_from_diff(db, org):
    """Setting quantity to the same (quantized) value must not record a spurious diff —
    the route compares the quantized before/after strings, not the raw input."""
    item = InventoryItemFactory(org_id=org.id, quantity="10", name="Widget")
    db.commit()

    InventoryRepository(db).update_inventory_item(item.id, org.id, quantity="10.0000")

    event = _latest_event(db, item.id, "inventory_item.updated")
    assert event is not None
    assert not (event.diff and "quantity" in event.diff)


# --- update_inventory_item: quantity NOT supplied ------------------------------------------


def test_update_inventory_item_without_quantity_leaves_quantity_untouched(db, org):
    item = InventoryItemFactory(org_id=org.id, quantity="10", name="Old Name")
    db.commit()

    updated = InventoryRepository(db).update_inventory_item(item.id, org.id, name="New Name")

    assert updated is not None
    assert updated.name == "New Name"
    assert updated.quantity == Decimal("10.0000"), "the no-quantity branch must never touch on-hand quantity"


def test_update_inventory_item_without_quantity_still_emits_event_with_field_diff(db, org):
    item = InventoryItemFactory(org_id=org.id, quantity="10", name="Old Name", unit="kg")
    db.commit()

    InventoryRepository(db).update_inventory_item(item.id, org.id, name="New Name")

    event = _latest_event(db, item.id, "inventory_item.updated")
    assert event is not None, "the no-quantity branch must still write an audit event"
    assert event.diff["name"] == {"before": "Old Name", "after": "New Name"}
    assert "quantity" not in (event.diff or {}), "no-quantity branch must not fabricate a quantity diff"


# --- update_inventory_item: org scoping -----------------------------------------------------


def test_update_inventory_item_returns_none_for_item_in_another_org(db, org):
    other_org = OrganisationFactory()
    db.commit()
    item = InventoryItemFactory(org_id=other_org.id, quantity="10")
    db.commit()

    try:
        result = InventoryRepository(db).update_inventory_item(item.id, org.id, name="Hijacked")
        assert result is None
        db.expire_all()
        assert db.get(InventoryItem, item.id).name != "Hijacked"
    finally:
        db.query(InventoryItem).filter(InventoryItem.org_id == other_org.id).delete(synchronize_session=False)
        db.query(Organisation).filter(Organisation.id == other_org.id).delete(synchronize_session=False)
        db.commit()


# --- delete_inventory_item: tombstone-before-row-gone (AC6) ---------------------------------


def test_delete_inventory_item_removes_the_row(db, org):
    item = InventoryItemFactory(org_id=org.id, quantity="10")
    db.commit()
    item_id = item.id

    result = InventoryRepository(db).delete_inventory_item(item_id, org.id)

    assert result is True
    assert db.query(InventoryItem).filter(InventoryItem.id == item_id).first() is None


def test_delete_inventory_item_emits_tombstone_with_pre_deletion_snapshot(db, org):
    """The tombstone event must carry the item's data as it was BEFORE deletion — since the
    row is gone afterward, the only way to prove that ordering is to read the snapshot back
    out of the (still-existing) event row and check it matches what was deleted."""
    item = InventoryItemFactory(org_id=org.id, quantity="42", name="Doomed Widget", unit="kg")
    db.commit()
    item_id = item.id

    InventoryRepository(db).delete_inventory_item(item_id, org.id)

    event = _latest_event(db, item_id, "inventory_item.deleted")
    assert event is not None, "delete must emit an inventory_item.deleted tombstone"
    assert event.payload["name"] == "Doomed Widget"
    assert event.payload["quantity"] == "42.0000"
    assert event.payload["unit"] == "kg"


def test_delete_inventory_item_returns_false_for_item_in_another_org(db, org):
    other_org = OrganisationFactory()
    db.commit()
    item = InventoryItemFactory(org_id=other_org.id, quantity="10")
    db.commit()

    try:
        result = InventoryRepository(db).delete_inventory_item(item.id, org.id)
        assert result is False
        db.expire_all()
        assert db.get(InventoryItem, item.id) is not None, "a foreign-org delete attempt must not remove the row"
    finally:
        db.query(InventoryItem).filter(InventoryItem.org_id == other_org.id).delete(synchronize_session=False)
        db.query(Organisation).filter(Organisation.id == other_org.id).delete(synchronize_session=False)
        db.commit()
