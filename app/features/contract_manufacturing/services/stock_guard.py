"""Receipt-backed raw title and transaction-bound debit proofs, including old APIs."""

from contextlib import contextmanager
from contextvars import ContextVar
from decimal import Decimal

from sqlalchemy import event, inspect
from sqlalchemy.orm import Session, scoped_session

from app.features.contract_manufacturing.services.materials import MaterialScopeError

_receipt_write = ContextVar("_contract_receipt_write", default=False)
PREFLIGHT_KEY = "contract_material_preflight"


@contextmanager
def recorded_material_receipt():
    token = _receipt_write.set(True)
    try:
        yield
    finally:
        _receipt_write.reset(token)


def remember_preflight(session, scope, items):
    # Scoped sessions proxy info/transactions; proof never outlives the transaction.
    if isinstance(session, scoped_session):
        session = session()
    session.info[PREFLIGHT_KEY] = (
        session.get_transaction(),
        scope,
        {row.id: (row.org_id, row.contract_customer_id, row.unit) for row in items},
    )


def _validate_receipt(session, item):
    from app.features.contract_manufacturing.models.material_receipt import ContractMaterialReceipt

    if not _receipt_write.get():
        raise MaterialScopeError("Customer raw stock must be received through the recorded material service", 409)
    receipt = (
        session.query(ContractMaterialReceipt)
        .filter(
            ContractMaterialReceipt.org_id == item.org_id,
            ContractMaterialReceipt.id == item.material_receipt_id,
            ContractMaterialReceipt.customer_id == item.contract_customer_id,
            ContractMaterialReceipt.inventory_item_id == item.id,
        )
        .one_or_none()
    )
    if receipt is None or receipt.quantity != item.quantity or receipt.unit != item.unit:
        raise MaterialScopeError("Material receipt must match its owned lot and quantity", 409)
    for field in (
        "name",
        "supplier",
        "supplier_batch_number",
        "expiry_date",
        "purchase_date",
        "site_id",
        "location_id",
    ):
        actual = getattr(item, field)
        actual = str(actual) if actual is not None else None
        if receipt.stock_snapshot.get(field) != actual:
            raise MaterialScopeError("Customer raw stock must preserve its receipt facts", 409)


def _before_flush(session, _flush_context, _instances):
    from app.core.db.models.inventory_item import InventoryItem
    from app.core.db.models.inventory_wastage import InventoryWastage
    from app.core.db.models.site_transfer import SiteStockTransfer
    from app.core.db.transfer_guard import transfer_accounting_allowed
    from app.core.domain.inventory_quantity_guard import InventoryQuantityWriteReason, inventory_quantity_write_reason
    from app.features.contract_manufacturing.models.material_receipt import ContractMaterialReceipt

    for receipt in session.new | session.dirty | session.deleted:
        if isinstance(receipt, ContractMaterialReceipt):
            if not _receipt_write.get() or receipt not in session.new:
                raise MaterialScopeError("Material receipt evidence is immutable and service-owned", 409)
    identity = (
        "contract_customer_id",
        "material_receipt_id",
        "name",
        "unit",
        "inventory_type",
        "supplier",
        "supplier_batch_number",
        "source_execution_id",
        "source_execution_step_id",
        "source_output_id",
        "source_step_name",
        "site_id",
        "location_id",
        "expiry_date",
        "purchase_date",
        "barcode",
        "extra_data",
    )
    for item in session.new | session.dirty | session.deleted:
        if not isinstance(item, InventoryItem):
            continue
        state = inspect(item)
        if item not in session.new and any(state.attrs[key].history.has_changes() for key in identity[:2]):
            raise MaterialScopeError("Stock title and receipt proof cannot be changed", 409)
        if "contract_customer_id" in (item.extra_data or {}):
            raise MaterialScopeError("Legacy customer ownership must be explicitly resolved", 409)
        if item.contract_customer_id is None:
            continue
        if item in session.deleted:
            raise MaterialScopeError("Customer stock and its lineage cannot be deleted", 409)
        if (item.extra_data or {}).get("untracked"):
            raise MaterialScopeError("Customer raw stock cannot become untracked reconciliation stock", 409)
        if item.inventory_type != "raw_material":
            raise MaterialScopeError("Only raw materials can carry customer title", 409)
        if item in session.new:
            if item.transfer_receipt_id:
                # Generic receipt proof validates owner alongside all provenance fields.
                continue
            _validate_receipt(session, item)
            continue
        if any(state.attrs[key].history.has_changes() for key in identity[2:]):
            raise MaterialScopeError("Customer raw stock identity and lineage cannot be edited", 409)
        history = state.attrs.quantity.history
        if not history.has_changes():
            continue
        if not history.deleted:
            raise MaterialScopeError("Customer stock quantity requires a locked original balance", 409)
        delta = Decimal(str(item.quantity)) - Decimal(str(history.deleted[0]))
        if delta >= 0 or item.quantity < 0:
            raise MaterialScopeError("Receive a distinct recorded lot rather than adjust customer stock", 409)
        proof = session.info.get(PREFLIGHT_KEY)
        if proof and proof[0] is session.get_transaction():
            reason = inventory_quantity_write_reason()
            if reason in {
                str(InventoryQuantityWriteReason.EXECUTION_STEP_INVENTORY),
                InventoryQuantityWriteReason.EXECUTION_STEP_INVENTORY.value,
            }:
                if proof[2].get(item.id) == (item.org_id, item.contract_customer_id, item.unit):
                    continue
        if transfer_accounting_allowed() and any(
            isinstance(row, SiteStockTransfer)
            and row.org_id == item.org_id
            and row.source_item_id == item.id
            and row.quantity == -delta
            and row.source_snapshot.get("contract_customer_id") == str(item.contract_customer_id)
            for row in session.new
        ):
            continue
        if inventory_quantity_write_reason() in {
            str(InventoryQuantityWriteReason.WASTAGE_RECORD),
            InventoryQuantityWriteReason.WASTAGE_RECORD.value,
        } and any(
            isinstance(row, InventoryWastage)
            and row.org_id == item.org_id
            and row.inventory_item_id == item.id
            and Decimal(row.quantity_wasted) == -delta
            and row.unit == item.unit
            and (row.reason or "").strip()
            for row in session.new
        ):
            continue
        raise MaterialScopeError("Customer stock debit requires trusted production, transfer or wastage evidence", 409)


def register_material_stock_guard():
    if not getattr(register_material_stock_guard, "_registered", False):
        event.listen(Session, "before_flush", _before_flush)
        event.listen(Session, "after_transaction_end", _clear_preflight)
        register_material_stock_guard._registered = True


def _clear_preflight(session, transaction):
    if transaction.parent is None:
        session.info.pop(PREFLIGHT_KEY, None)
