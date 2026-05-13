"""Inventory repository with tenancy enforcement"""

from datetime import date
from decimal import Decimal, InvalidOperation
from uuid import UUID

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.core.backend.event_writer import EventWriter
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


def _item_snapshot(item: InventoryItem) -> dict:
    return {
        "id": str(item.id),
        "org_id": str(item.org_id),
        "name": item.name,
        "quantity": str(item.quantity),
        "unit": item.unit,
        "inventory_type": item.inventory_type,
        "supplier": item.supplier,
        "barcode": item.barcode,
        "purchase_date": item.purchase_date.isoformat() if item.purchase_date else None,
        "supplier_batch_number": item.supplier_batch_number,
        "expiry_date": item.expiry_date.isoformat() if item.expiry_date else None,
        "source_execution_id": str(item.source_execution_id) if item.source_execution_id else None,
        "source_execution_step_id": str(item.source_execution_step_id) if item.source_execution_step_id else None,
        "source_output_id": str(item.source_output_id) if item.source_output_id else None,
        "source_step_name": item.source_step_name,
        "extra_data": item.extra_data or {},
        "display_label": item.display_label,
    }


def _detect_add_method(extra_data: dict | None, source_execution_id) -> str:
    """Infer how an item was added from its metadata."""
    extra = extra_data or {}
    if source_execution_id:
        return "execution_output"
    if extra.get("barcode_scan"):
        return "barcode_scan"
    if extra.get("csv_import"):
        return "csv_import"
    return "manual"


def _build_display_label(item: InventoryItem) -> str:
    parts = [item.name]
    if item.supplier_batch_number:
        parts.append(f"Batch #{item.supplier_batch_number}")
    if item.quantity is not None:
        parts.append(f"{item.quantity} {item.unit}")
    return " · ".join(parts)


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
        """Create a new inventory item. If commit=False, caller is responsible for commit."""
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
            item.display_label = _build_display_label(item)
            self.db.add(item)
            self.db.flush()
            _ = item.id

            add_method = _detect_add_method(extra_data, source_execution_id)
            ew = EventWriter(self.db, org_id)
            ew.emit(
                event_type="inventory_item.created",
                entity_type="inventory_item",
                entity_id=item.id,
                payload={
                    **_item_snapshot(item),
                    "add_method": add_method,
                },
            )

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
        """Add quantity to an existing inventory item. Uses SELECT FOR UPDATE to avoid race conditions."""
        item = self.get_inventory_item_by_id_for_update(item_id, org_id)
        if not item:
            return None
        current = parse_stored_quantity_to_decimal(item.quantity)
        add_val = _parse_quantity(quantity_to_add) or Decimal("0")
        if add_val <= 0:
            if commit:
                self.db.commit()
            return item

        quantity_before = str(current)

        with allow_inventory_quantity_write(InventoryQuantityWriteReason.REPOSITORY_ADD_QUANTITY):
            item.quantity = coerce_stored_quantity(current + add_val)
            if extra_data_merge:
                merged = dict(item.extra_data or {})
                for key, value in extra_data_merge.items():
                    if key == "inventory_audit_history" and isinstance(value, list):
                        existing = list(merged.get(key) or [])
                        merged[key] = existing + value
                    else:
                        merged[key] = value
                item.extra_data = merged

            ew = EventWriter(self.db, org_id)
            ew.emit(
                event_type="inventory_item.quantity_adjusted",
                entity_type="inventory_item",
                entity_id=item.id,
                payload={
                    **_item_snapshot(item),
                    "quantity_before": quantity_before,
                    "quantity_after": str(item.quantity),
                    "delta": str(add_val),
                    "reason": InventoryQuantityWriteReason.REPOSITORY_ADD_QUANTITY.value,
                },
                diff={"quantity": {"before": quantity_before, "after": str(item.quantity)}},
            )

            if commit:
                self.db.commit()
        self.db.expire(item, ["updated_at"])
        _ = item.updated_at
        return item

    def set_inventory_item_quantity(
        self,
        item_id: UUID,
        org_id: UUID,
        new_quantity: str,
        commit: bool = True,
    ) -> InventoryItem | None:
        """Set inventory quantity to an absolute value, emitting a quantity_adjusted event."""
        item = self.get_inventory_item_by_id_for_update(item_id, org_id)
        if not item:
            return None
        current = parse_stored_quantity_to_decimal(item.quantity)
        target = _parse_quantity(new_quantity)
        if target is None or target < 0:
            raise ValueError("new_quantity must be a non-negative number")
        quantity_before = str(current)
        if current == target:
            if commit:
                self.db.commit()
            return item
        with allow_inventory_quantity_write(InventoryQuantityWriteReason.MANUAL_API_UPDATE):
            item.quantity = coerce_stored_quantity(target)
        ew = EventWriter(self.db, org_id)
        ew.emit(
            event_type="inventory_item.quantity_adjusted",
            entity_type="inventory_item",
            entity_id=item.id,
            payload={
                **_item_snapshot(item),
                "quantity_before": quantity_before,
                "quantity_after": str(item.quantity),
                "delta": str(target - current),
                "reason": "manual_correction",
            },
            diff={"quantity": {"before": quantity_before, "after": str(item.quantity)}},
        )
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
        """Get inventory item by ID with row-level lock (FOR UPDATE)."""
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
            from app.core.db.models.execution import Execution

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
        """Update inventory item (must belong to org)."""
        item = self.get_inventory_item_by_id(item_id, org_id)
        if not item:
            return None

        diff: dict = {}
        if name is not None and name != item.name:
            diff["name"] = {"before": item.name, "after": name}
            item.name = name
        if unit is not None and unit != item.unit:
            diff["unit"] = {"before": item.unit, "after": unit}
            item.unit = unit
        if extra_data is not None:
            item.extra_data = extra_data

        if quantity is not None:
            qty_before = str(item.quantity)
            with allow_inventory_quantity_write(InventoryQuantityWriteReason.REPOSITORY_UPDATE):
                item.quantity = coerce_stored_quantity(quantity)
                if str(item.quantity) != qty_before:
                    diff["quantity"] = {"before": qty_before, "after": str(item.quantity)}

                ew = EventWriter(self.db, org_id)
                ew.emit(
                    event_type="inventory_item.updated",
                    entity_type="inventory_item",
                    entity_id=item.id,
                    payload=_item_snapshot(item),
                    diff=diff or None,
                )
                if commit:
                    self.db.commit()
        else:
            ew = EventWriter(self.db, org_id)
            ew.emit(
                event_type="inventory_item.updated",
                entity_type="inventory_item",
                entity_id=item.id,
                payload=_item_snapshot(item),
                diff=diff or None,
            )
            if commit:
                self.db.commit()

        self.db.expire(item, ["updated_at"])
        _ = item.updated_at
        return item

    def delete_inventory_item(self, item_id: UUID, org_id: UUID) -> bool:
        """Delete inventory item — emits tombstone event before deletion."""
        item = self.get_inventory_item_by_id(item_id, org_id)
        if not item:
            return False

        snapshot = _item_snapshot(item)
        ew = EventWriter(self.db, org_id)
        ew.emit(
            event_type="inventory_item.deleted",
            entity_type="inventory_item",
            entity_id=item.id,
            payload=snapshot,
        )
        self.db.delete(item)
        self.db.commit()
        return True
