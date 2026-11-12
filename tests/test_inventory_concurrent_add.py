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
from tests.costing_helpers import flows, lot, new_org, purge


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
            for session, qty, ref in ((first, "2", "delivery-a"), (second, "3", "delivery-b")):
                InventoryRepository(session).add_quantity_to_inventory_item(
                    item.id,
                    org.id,
                    qty,
                    extra_data_merge={"inventory_audit_history": [{"source_method": "barcode", "ref": ref}]},
                )  # each commits; the second still held its stale copy
        db.expire_all()
        refreshed = db.get(InventoryItem, item.id)
        assert Decimal(str(refreshed.quantity)) == Decimal("10")
        refs = [entry.get("ref") for entry in (refreshed.extra_data or {}).get("inventory_audit_history", [])]
        assert refs[-2:] == ["delivery-a", "delivery-b"], "neither delivery's audit entry is overwritten"
        added = sorted(Decimal(str(f.quantity)) for f in flows(db, org.id, item.id, kind="added"))
        assert added == [Decimal("2"), Decimal("3")], "each delivery leaves its own stock flow"
        from app.core.db.models.entity_event import EntityEvent

        events = (
            db.query(EntityEvent)
            .filter(
                EntityEvent.org_id == org.id,
                EntityEvent.entity_id == item.id,
                EntityEvent.event_type == "inventory_item.quantity_adjusted",
            )
            .all()
        )
        steps = sorted(
            (Decimal(e.payload["quantity_before"]), Decimal(e.payload["quantity_after"]), Decimal(e.payload["delta"]))
            for e in events
        )
        assert steps == [
            (Decimal("5"), Decimal("7"), Decimal("2")),
            (Decimal("7"), Decimal("10"), Decimal("3")),
        ], "the activity history shows 5 to 7 then 7 to 10, not two changes from 5"
    finally:
        first.close()
        second.close()
        purge(db, org)
