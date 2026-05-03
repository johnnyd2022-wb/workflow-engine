"""Inventory repository with tenancy enforcement"""

from datetime import date
from decimal import Decimal, InvalidOperation
from uuid import UUID

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.core.db.models.inventory_item import InventoryItem
from app.core.domain.inventory_quantity_guard import (
    InventoryQuantityWriteReason,
    allow_inventory_quantity_write,
)
from app.core.utils.inventory_quantity import coerce_stored_quantity, parse_stored_quantity_to_decimal

_UNTRACKED_EXTRA_FILTER = {"untracked": True}


def _parse_quantity(value: object | None) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None


class InventoryRepository:
    """Repository for inventory operations with automatic tenancy enforcement"""

    def __init__(self, db: Session):
        self.db = db

    def find_by_barcode(self, org_id: UUID, barcode: str) -> InventoryItem | None:
        """Return the first inventory item with this barcode in the org (for product-level lookup)."""
        if not barcode or not barcode.strip():
            return None
        return (
            self.db.query(InventoryItem)
            .filter(InventoryItem.org_id == org_id, InventoryItem.barcode == barcode.strip())
            .limit(1)
            .first()
        )

    def create_inventory_item(
        self,
        org_id: UUID,
        name: str,
        quantity: str | Decimal,
        unit: str,
        inventory_type: str,
        supplier: str | None = None,
        barcode: str | None = None,
        purchase_date: date | None = None,
        supplier_batch_number: str | None = None,
        expiry_date: date | None = None,
        source_execution_id: UUID | None = None,
        source_execution_step_id: UUID | None = None,
        source_output_id: UUID | None = None,
        source_step_name: str | None = None,
        extra_data: dict | None = None,
        commit: bool = True,
    ) -> InventoryItem:
        """Create a new inventory item. If commit=False, caller is responsible for commit (e.g. atomic reconciliation)."""
        with allow_inventory_quantity_write(InventoryQuantityWriteReason.REPOSITORY_CREATE):
            item = InventoryItem(
                org_id=org_id,
                name=name,
                quantity=coerce_stored_quantity(quantity),
                unit=unit,
                inventory_type=inventory_type,
                supplier=supplier,
                barcode=barcode,
                purchase_date=purchase_date,
                supplier_batch_number=supplier_batch_number,
                expiry_date=expiry_date,
                source_execution_id=source_execution_id,
                source_execution_step_id=source_execution_step_id,
                source_output_id=source_output_id,
                source_step_name=source_step_name,
                extra_data=extra_data or {},
            )
            self.db.add(item)
            self.db.flush()
            _ = item.id
            if commit:
                self.db.commit()
        return item

    def add_quantity_to_inventory_item(
        self,
        item_id: UUID,
        org_id: UUID,
        quantity_to_add: str,
        extra_data_merge: dict | None = None,
        commit: bool = True,
    ) -> InventoryItem | None:
        """Add quantity to an existing inventory item (e.g. repeat barcode scan). Merges extra_data_merge into item.extra_data.
        Uses SELECT ... FOR UPDATE to avoid lost updates under concurrent add-quantity for the same item.
        """
        item = self.get_inventory_item_by_id_for_update(item_id, org_id)
        if not item:
            return None
        current = parse_stored_quantity_to_decimal(item.quantity)
        add_val = _parse_quantity(quantity_to_add) or Decimal("0")
        if add_val <= 0:
            if commit:
                self.db.commit()
            return item
        with allow_inventory_quantity_write(InventoryQuantityWriteReason.REPOSITORY_ADD_QUANTITY):
            item.quantity = coerce_stored_quantity(current + add_val)
            if extra_data_merge:
                # Merge audit etc. into extra_data; for high volume consider a relational InventoryAuditEntry table
                merged = dict(item.extra_data or {})
                for key, value in extra_data_merge.items():
                    if key == "inventory_audit_history" and isinstance(value, list):
                        existing = list(merged.get(key) or [])
                        merged[key] = existing + value
                    else:
                        merged[key] = value
                item.extra_data = merged
            if commit:
                self.db.commit()
        self.db.expire(item, ["updated_at"])
        _ = item.updated_at
        return item

    def get_inventory_item_by_id(self, item_id: UUID, org_id: UUID | None = None) -> InventoryItem | None:
        """Get inventory item by ID, optionally scoped to org"""
        query = self.db.query(InventoryItem).filter(InventoryItem.id == item_id)
        if org_id:
            query = query.filter(InventoryItem.org_id == org_id)
        return query.first()

    def get_inventory_item_by_id_for_update(self, item_id: UUID, org_id: UUID) -> InventoryItem | None:
        """Get inventory item by ID with row-level lock (FOR UPDATE). Use for reconciliation to avoid race conditions."""
        return (
            self.db.query(InventoryItem)
            .filter(InventoryItem.id == item_id, InventoryItem.org_id == org_id)
            .with_for_update()
            .one_or_none()
        )

    def get_untracked_items(
        self,
        org_id: UUID,
        name: str | None = None,
        unit: str | None = None,
        process_id: UUID | None = None,
        quantity_gt_zero: bool = True,
    ) -> list[InventoryItem]:
        """
        Query untracked inventory items: extra_data.untracked == True, optionally filtered by name, unit, process.
        When quantity_gt_zero is True (default), only returns items with quantity > 0 (for checks and matching).
        """
        from app.core.db.models.execution import Execution

        query = (
            self.db.query(InventoryItem)
            .filter(InventoryItem.org_id == org_id)
            .filter(InventoryItem.extra_data.isnot(None))
            .filter(InventoryItem.extra_data.contains(_UNTRACKED_EXTRA_FILTER))
        )
        if name is not None and name != "":
            query = query.filter(InventoryItem.name.ilike(name.strip()))
        if unit is not None and unit != "":
            query = query.filter(InventoryItem.unit == unit.strip())
        if process_id is not None:
            tagged_pid = InventoryItem.extra_data["producing_process_id"].astext == str(process_id)
            query = query.outerjoin(Execution, InventoryItem.source_execution_id == Execution.id).filter(
                Execution.org_id == org_id,
                or_(Execution.process_id == process_id, tagged_pid),
            )
        items = query.all()
        if quantity_gt_zero:
            items = [i for i in items if parse_stored_quantity_to_decimal(i.quantity) > 0]
        return items

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

            # Also include manually-added untracked items that are tagged to a process in extra_data.
            tagged_pid = InventoryItem.extra_data["producing_process_id"].astext == str(process_id)
            query = query.outerjoin(Execution, InventoryItem.source_execution_id == Execution.id).filter(
                or_(Execution.process_id == process_id, tagged_pid)
            )
        return query.order_by(InventoryItem.created_at.desc()).all()

    def update_inventory_item(
        self,
        item_id: UUID,
        org_id: UUID,
        name: str | None = None,
        quantity: str | Decimal | None = None,
        unit: str | None = None,
        extra_data: dict | None = None,
        commit: bool = True,
    ) -> InventoryItem | None:
        """Update inventory item (must belong to org). If commit=False, caller is responsible for commit."""
        item = self.get_inventory_item_by_id(item_id, org_id)
        if not item:
            return None

        if name is not None:
            item.name = name
        if unit is not None:
            item.unit = unit
        if extra_data is not None:
            item.extra_data = extra_data

        if quantity is not None:
            with allow_inventory_quantity_write(InventoryQuantityWriteReason.REPOSITORY_UPDATE):
                item.quantity = coerce_stored_quantity(quantity)
                if commit:
                    self.db.commit()
        elif commit:
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
