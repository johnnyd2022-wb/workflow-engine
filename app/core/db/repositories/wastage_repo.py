"""Wastage repository: create wastage records and list for trace/sourcemap"""

from datetime import datetime
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.backend.event_writer import EventWriter
from app.core.db.models.inventory_wastage import InventoryWastage


class WastageRepository:
    def __init__(self, db: Session):
        self.db = db

    def create_wastage_record(
        self,
        org_id: UUID,
        inventory_item_id: UUID,
        quantity_wasted: str,
        unit: str,
        reason: str,
        recorded_by: str | None = None,
        recorded_at: datetime | None = None,
        causation_id: UUID | None = None,
    ) -> InventoryWastage:
        """Create a wastage record. Caller must deduct from inventory item quantity.

        causation_id: pass the execution.step_completed event id when called from
        within a step completion so the causal chain is preserved.
        """
        record = InventoryWastage(
            org_id=org_id,
            inventory_item_id=inventory_item_id,
            quantity_wasted=quantity_wasted,
            unit=unit,
            reason=reason,
            recorded_by=recorded_by,
            recorded_at=recorded_at or datetime.utcnow(),
        )
        self.db.add(record)
        self.db.flush()
        _ = record.id

        ew = EventWriter(self.db, org_id)
        ew.emit(
            event_type="inventory_item.wasted",
            entity_type="inventory_item",
            entity_id=inventory_item_id,
            payload={
                "wastage_id": str(record.id),
                "inventory_item_id": str(inventory_item_id),
                "quantity_wasted": quantity_wasted,
                "unit": unit,
                "reason": reason,
                "recorded_by": recorded_by,
                "recorded_at": record.recorded_at.isoformat() if record.recorded_at else None,
            },
            causation_id=causation_id,
        )

        self.db.commit()
        return record

    def list_wastage_records(
        self,
        org_id: UUID,
        inventory_item_id: UUID | None = None,
        limit: int = 500,
    ):
        """List wastage records for sourcemap/trace, optionally filtered by item."""
        q = (
            self.db.query(InventoryWastage)
            .filter(InventoryWastage.org_id == org_id)
            .order_by(InventoryWastage.recorded_at.desc())
        )
        if inventory_item_id:
            q = q.filter(InventoryWastage.inventory_item_id == inventory_item_id)
        return q.limit(limit).all()
