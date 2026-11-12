"""Lost update on add-quantity: a session that already loaded the lot must add to the committed figure.

Deterministic version of the concurrent barcode delivery test (review !706): both sessions read the
lot at quantity 5 before either commits; the first adds 2 and commits; the second, still holding its
stale copy, adds 3. The lot must end at 10, not 8.
"""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy.orm import Session

from app.core.db.models.inventory_item import InventoryItem
from app.core.db.repositories.inventory_repo import InventoryRepository
from app.core.security.tenant_scope import unscoped
from tests.costing_helpers import lot, new_org, purge


def test_a_stale_session_adds_to_the_committed_quantity(db):
    org = new_org(db, grant=False)
    item = lot(db, org.id, "Concurrent lot", 5, "kg")
    db.commit()
    first, second = Session(bind=db.get_bind()), Session(bind=db.get_bind())
    try:
        with unscoped():
            stale_first = first.get(InventoryItem, item.id)
            stale_second = second.get(InventoryItem, item.id)
            assert Decimal(str(stale_first.quantity)) == Decimal(str(stale_second.quantity)) == Decimal("5")
            InventoryRepository(first).add_quantity_to_inventory_item(item.id, org.id, "2")  # commits
            InventoryRepository(second).add_quantity_to_inventory_item(item.id, org.id, "3")  # stale copy loaded
        db.expire_all()
        assert Decimal(str(db.get(InventoryItem, item.id).quantity)) == Decimal("10")
    finally:
        first.close()
        second.close()
        purge(db, org)
