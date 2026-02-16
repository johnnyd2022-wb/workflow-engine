"""Wastage repository: create wastage records and list for trace/sourcemap"""

from datetime import datetime
from uuid import UUID

from sqlalchemy.orm import Session

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
        recorded_by: str | None = None,
        recorded_at: datetime | None = None,
    ) -> InventoryWastage:
        """Create a wastage record. Caller must deduct from inventory item quantity."""
        record = InventoryWastage(
            org_id=org_id,
            inventory_item_id=inventory_item_id,
            quantity_wasted=quantity_wasted,
            unit=unit,
            recorded_by=recorded_by,
            recorded_at=recorded_at or datetime.utcnow(),
        )
        self.db.add(record)
        self.db.flush()
        _ = record.id
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
