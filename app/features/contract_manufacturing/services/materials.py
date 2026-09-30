"""Trusted raw-material ownership preflight; receipts stay closed until stock guards land.

Call before any production debit or output deposit, within the same transaction.
The persisted execution and order determine authority; request owner/customer fields
are never accepted. These functions do not commit, mutate stock or infer output title.
"""

from dataclasses import dataclass
from uuid import UUID

from app.core.db.models.execution import Execution
from app.core.db.models.inventory_item import InventoryItem, InventoryType
from app.features.contract_manufacturing.models.orders import (
    MATERIALS_SOURCES,
    ContractOrder,
    ContractOrderExecution,
    ContractOrderLine,
)
from app.features.contract_manufacturing.services.orders import OrderError, identifier


class MaterialScopeError(OrderError):
    pass


@dataclass(frozen=True)
class ExecutionMaterialScope:
    org_id: UUID
    execution_id: UUID
    order_id: UUID | None
    line_id: UUID | None
    customer_id: UUID | None
    materials_source: str


def resolve_execution_material_scope(db, org_id, execution_id):
    """Lock execution → order; link/unlink writers must use the same order.

    The execution lock also protects the absence of an assignment. A caller cannot
    supply a customer ID or substitute a cached order for the locked server records.
    """
    if not isinstance(org_id, UUID):
        raise MaterialScopeError("Authenticated organisation required", 403)
    execution_id = identifier(execution_id, "execution_id")
    execution = (
        db.query(Execution)
        .filter(Execution.org_id == org_id, Execution.id == execution_id)
        .with_for_update()
        .populate_existing()
        .one_or_none()
    )
    if execution is None:
        raise MaterialScopeError("Batch not found", 404)
    assignment = (
        db.query(ContractOrderExecution)
        .filter(ContractOrderExecution.org_id == org_id, ContractOrderExecution.execution_id == execution.id)
        .populate_existing()
        .one_or_none()
    )
    if assignment is None:
        return ExecutionMaterialScope(org_id, execution.id, None, None, None, "producer")
    order = (
        db.query(ContractOrder)
        .filter(ContractOrder.org_id == org_id, ContractOrder.id == assignment.order_id)
        .with_for_update()
        .populate_existing()
        .one_or_none()
    )
    line = (
        db.query(ContractOrderLine)
        .filter(
            ContractOrderLine.org_id == org_id,
            ContractOrderLine.order_id == assignment.order_id,
            ContractOrderLine.id == assignment.line_id,
        )
        .populate_existing()
        .one_or_none()
    )
    if order is None or line is None or line.materials_source not in MATERIALS_SOURCES:
        raise MaterialScopeError("Batch has an invalid contract materials association", 409)
    if order.status != "confirmed":
        raise MaterialScopeError("Contract production requires a confirmed order", 409)
    return ExecutionMaterialScope(org_id, execution.id, order.id, line.id, order.customer_id, line.materials_source)


def validate_material_owner(scope, stock_org_id, stock_owner_id, inventory_type):
    """Validate a trusted stock fact; only raw lots gain customer ownership in 7.2b.

    Producer WIP/final goods keep their explicit producer title, independently of
    raw-material sourcing. Customer-owned non-raw stock needs a later title policy.
    """
    if scope.materials_source not in MATERIALS_SOURCES:
        raise MaterialScopeError("Unknown materials policy", 409)
    if inventory_type not in {item.value for item in InventoryType}:
        raise MaterialScopeError("Unknown material stock type", 409)
    if stock_org_id != scope.org_id:
        raise MaterialScopeError("Material must belong to the execution's organisation", 404)
    if stock_owner_id is not None:
        if not isinstance(stock_owner_id, UUID) or stock_owner_id != scope.customer_id:
            raise MaterialScopeError("Customer materials are usable only for that customer's order", 409)
        if inventory_type != InventoryType.RAW_MATERIAL.value:
            raise MaterialScopeError("Customer ownership of intermediate or finished stock is not available", 409)
    if inventory_type == InventoryType.RAW_MATERIAL.value:
        if scope.materials_source == "producer" and stock_owner_id is not None:
            raise MaterialScopeError("This order line uses producer-owned raw materials", 409)
        if scope.materials_source == "customer" and stock_owner_id is None:
            raise MaterialScopeError("This order line uses customer-owned raw materials", 409)


def validate_execution_materials(db, org_id, execution_id, actual_inputs, actual_outputs):
    """Resolve scope and validate ALL selected/reconciliation lots before any write.

    Requires the coordinated inventory owner column. Missing ownership schema fails
    closed rather than silently treating a customer's lot as producer-owned.
    """
    scope = resolve_execution_material_scope(db, org_id, execution_id)
    item_ids = set()
    for entries, key in ((actual_inputs, "inventory_item_id"), (actual_outputs, "untracked_item_id")):
        if entries is not None and not isinstance(entries, list):
            raise MaterialScopeError("Production materials must be a list")
        for entry in entries or []:
            if not isinstance(entry, dict):
                raise MaterialScopeError("Each production material must be an object")
            if entry.get(key):
                item_ids.add(identifier(entry[key], key))
    if not item_ids:
        return scope
    items = (
        db.query(InventoryItem)
        .filter(InventoryItem.org_id == org_id, InventoryItem.id.in_(item_ids))
        .order_by(InventoryItem.id)
        .with_for_update()
        .populate_existing()
        .all()
    )
    if len(items) != len(item_ids):
        raise MaterialScopeError("Production material not found", 404)
    for item in items:
        if not hasattr(item, "contract_customer_id"):
            raise MaterialScopeError("Customer material ownership guards are not available yet", 409)
        if (item.extra_data or {}).get("contract_customer_id"):
            raise MaterialScopeError("Legacy customer ownership must be resolved before consumption", 409)
        validate_material_owner(scope, item.org_id, item.contract_customer_id, item.inventory_type)
    return scope
