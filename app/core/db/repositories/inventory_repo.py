"""Inventory repository with tenancy enforcement"""

from datetime import date
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.db.models.inventory_item import InventoryItem


class InventoryRepository:
    """Repository for inventory operations with automatic tenancy enforcement"""

    def __init__(self, db: Session):
        self.db = db

    def create_inventory_item(
        self,
        org_id: UUID,
        name: str,
        quantity: str,
        unit: str,
        inventory_type: str,
        supplier: str | None = None,
        purchase_date: date | None = None,
        supplier_batch_number: str | None = None,
        expiry_date: date | None = None,
        source_execution_id: UUID | None = None,
        source_execution_step_id: UUID | None = None,
        source_step_name: str | None = None,
        extra_data: dict | None = None,
    ) -> InventoryItem:
        """Create a new inventory item"""
        item = InventoryItem(
            org_id=org_id,
            name=name,
            quantity=quantity,
            unit=unit,
            inventory_type=inventory_type,
            supplier=supplier,
            purchase_date=purchase_date,
            supplier_batch_number=supplier_batch_number,
            expiry_date=expiry_date,
            source_execution_id=source_execution_id,
            source_execution_step_id=source_execution_step_id,
            source_step_name=source_step_name,
            extra_data=extra_data or {},
        )
        self.db.add(item)
        self.db.flush()
        _ = item.id
        self.db.commit()
        return item

    def get_inventory_item_by_id(self, item_id: UUID, org_id: UUID | None = None) -> InventoryItem | None:
        """Get inventory item by ID, optionally scoped to org"""
        query = self.db.query(InventoryItem).filter(InventoryItem.id == item_id)
        if org_id:
            query = query.filter(InventoryItem.org_id == org_id)
        return query.first()

    def list_inventory_items(
        self, org_id: UUID, inventory_type: str | None = None, process_id: UUID | None = None
    ) -> list[InventoryItem]:
        """List inventory items for an organisation, optionally filtered by type or process"""
        query = self.db.query(InventoryItem).filter(InventoryItem.org_id == org_id)
        if inventory_type:
            query = query.filter(InventoryItem.inventory_type == inventory_type)
        if process_id:
            # Filter by process through execution
            from app.core.db.models.execution import Execution

            query = query.join(Execution, InventoryItem.source_execution_id == Execution.id).filter(
                Execution.process_id == process_id
            )
        return query.order_by(InventoryItem.created_at.desc()).all()

    def update_inventory_item(
        self,
        item_id: UUID,
        org_id: UUID,
        name: str | None = None,
        quantity: str | None = None,
        unit: str | None = None,
        extra_data: dict | None = None,
    ) -> InventoryItem | None:
        """Update inventory item (must belong to org)"""
        item = self.get_inventory_item_by_id(item_id, org_id)
        if not item:
            return None

        if name is not None:
            item.name = name
        if quantity is not None:
            item.quantity = quantity
        if unit is not None:
            item.unit = unit
        if extra_data is not None:
            item.extra_data = extra_data

        self.db.commit()
        self.db.expire(item, ["updated_at"])
        _ = item.updated_at
        return item

    def delete_inventory_item(self, item_id: UUID, org_id: UUID) -> bool:
        """Delete inventory item"""
        item = self.get_inventory_item_by_id(item_id, org_id)
        if not item:
            return False

        self.db.delete(item)
        self.db.commit()
        return True
