"""Inventory repository with tenancy enforcement"""

from datetime import date
from decimal import Decimal, InvalidOperation
from uuid import UUID

from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from app.core.backend.event_writer import EventWriter
from app.core.db.models.inventory_item import InventoryItem
from app.core.domain.inventory_quantity_guard import (
    InventoryQuantityWriteReason,
    allow_inventory_quantity_write,
)
from app.core.utils.inventory_quantity import coerce_stored_quantity, parse_stored_quantity_to_decimal
from app.observability import get_logger, start_span

logger = get_logger(__name__)

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

    def _assert_source_refs_belong_to_org(
        self,
        org_id: UUID,
        source_execution_id: UUID | None,
        source_execution_step_id: UUID | None,
        source_output_id: UUID | None = None,
    ) -> None:
        """Reject provenance references that point outside `org_id`.

        All three are accepted from client JSON by `POST /api/core/inventory`, and
        `executions` / `execution_steps` are global tables — nothing in the schema stops a
        row in org A from referencing org B's execution. That reference is then followed by
        lineage enrichment, so an unvalidated reference is a cross-tenant read primitive,
        not just a cosmetic data-integrity problem.

        `source_output_id` is the odd one out: it is `steps.outputs[].id` inside a JSONB
        array with no foreign key at all, so there is nothing to join against. It is only
        meaningful relative to a step, and validating it therefore means requiring the step
        it belongs to and checking membership in that step's declared outputs. An output id
        with no step is unverifiable by construction, so it is refused rather than trusted.

        Same shape as `ExecutionRepository.create_execution`, which already refuses to build
        an execution against a process outside the org.
        """
        from app.core.db.models.execution import Execution
        from app.core.db.models.execution_step import ExecutionStep
        from app.core.db.models.step import Step

        def _deny(reason: str, ref_kind: str, ref_id: object) -> None:
            """Log the refusal before raising.

            A rejected cross-tenant reference is a tenant-boundary probe, and the route
            turns it into an ordinary 400 — so without this it leaves no trace at all and
            prod-sentinel has nothing to find. Same `access_denied` event name the auth
            decorators use (app/core/security/permissions.py), so one query covers both.
            """
            logger.warning(
                "access_denied",
                reason=reason,
                feature="inventory",
                org_id=str(org_id),
                ref_kind=ref_kind,
                ref_id=str(ref_id),
            )

        if source_execution_id is not None:
            owned = (
                self.db.query(Execution.id)
                .filter(Execution.id == source_execution_id, Execution.org_id == org_id)
                .first()
            )
            if not owned:
                _deny("cross_org_source_execution", "source_execution_id", source_execution_id)
                raise ValueError("source_execution_id not found in this organisation")

        owned_step_row = None
        if source_execution_step_id is not None:
            owned_step_row = (
                self.db.query(ExecutionStep)
                .join(Execution, ExecutionStep.execution_id == Execution.id)
                .filter(ExecutionStep.id == source_execution_step_id, Execution.org_id == org_id)
                .first()
            )
            if not owned_step_row:
                _deny("cross_org_source_execution_step", "source_execution_step_id", source_execution_step_id)
                raise ValueError("source_execution_step_id not found in this organisation")

        if source_output_id is not None:
            if owned_step_row is None:
                _deny("source_output_without_step", "source_output_id", source_output_id)
                raise ValueError("source_output_id requires a source_execution_step_id in this organisation")
            step_def = self.db.query(Step).filter(Step.id == owned_step_row.step_id).first()
            declared = (step_def.outputs if step_def else None) or []
            if not any(str(o.get("id")) == str(source_output_id) for o in declared if isinstance(o, dict)):
                _deny("source_output_not_declared_by_step", "source_output_id", source_output_id)
                raise ValueError("source_output_id is not an output of that execution step")

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
        with start_span(
            "inventory.create",
            attributes={
                "org_id": str(org_id),
                "inventory_type": inventory_type,
                "has_source_execution": source_execution_id is not None,
            },
        ):
            self._assert_source_refs_belong_to_org(
                org_id, source_execution_id, source_execution_step_id, source_output_id
            )
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
        with start_span(
            "inventory.quantity_adjust",
            attributes={
                "org_id": str(org_id),
                "inventory_item_id": str(item_id),
                "reason": InventoryQuantityWriteReason.REPOSITORY_ADD_QUANTITY.value,
            },
        ):
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
        with start_span(
            "inventory.quantity_set",
            attributes={
                "org_id": str(org_id),
                "inventory_item_id": str(item_id),
                "reason": InventoryQuantityWriteReason.MANUAL_API_UPDATE.value,
            },
        ):
            item = self.get_inventory_item_by_id_for_update(item_id, org_id)
            if not item:
                return None
            current = parse_stored_quantity_to_decimal(item.quantity)
            target = _parse_quantity(new_quantity)
            # is_finite() must be checked BEFORE any ordering comparison: Decimal("NaN") < 0
            # raises InvalidOperation, which is not a ValueError, so it escapes the route's
            # handler as an unlogged non-JSON 500 instead of a 400.
            if target is None or not target.is_finite() or target < 0:
                raise ValueError("new_quantity must be a non-negative finite number")
            quantity_before = str(current)
            if current == target:
                if commit:
                    self.db.commit()
                return item
            with allow_inventory_quantity_write(InventoryQuantityWriteReason.MANUAL_API_UPDATE):
                item.quantity = coerce_stored_quantity(target)
                # Flush while the write reason is active: the guard authorizes quantity
                # writes at flush time, and EventWriter.emit() below flushes outside this
                # context, where the guard would reject the pending change.
                self.db.flush()
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
            # `Execution.org_id == org_id` belongs inside the join predicate, not beside it:
            # without it the WHERE clause can match on another tenant's execution even though
            # the SELECT stays org-scoped. `get_untracked_items` above already scopes its
            # equivalent join; this one had drifted.
            query = query.outerjoin(Execution, InventoryItem.source_execution_id == Execution.id).filter(
                or_(and_(Execution.org_id == org_id, Execution.process_id == process_id), tagged_pid)
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
        with start_span(
            "inventory.update",
            attributes={"org_id": str(org_id), "inventory_item_id": str(item_id)},
        ):
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
        with start_span(
            "inventory.delete",
            attributes={"org_id": str(org_id), "inventory_item_id": str(item_id)},
        ):
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
