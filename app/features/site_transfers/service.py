"""Atomic producer-owned stock dispatch and receipt, with policy evaluation.

Callers own commit/rollback. Policy callbacks must perform no external I/O or writes.
Transit stays on the books here and is never an InventoryItem/FIFO candidate.
"""

import hashlib
import json
from datetime import date
from decimal import Decimal, InvalidOperation
from types import MappingProxyType
from uuid import UUID, uuid4

from sqlalchemy import text

from app.core.backend.event_writer import EventWriter
from app.core.db.models.inventory_item import InventoryItem
from app.core.db.models.inventory_movement import InventoryMovement
from app.core.db.models.organisation import Organisation
from app.core.db.models.site import Site
from app.core.db.models.site_transfer import SiteStockReceipt, SiteStockTransfer
from app.core.db.models.stock_location import StockLocation
from app.core.db.models.user import User
from app.core.db.repositories.inventory_repo import InventoryRepository, _item_snapshot
from app.core.db.site_operations import resolve_site
from app.core.db.transfer_guard import allow_transfer_accounting
from app.core.domain.inventory_quantity_guard import InventoryQuantityWriteReason, allow_inventory_quantity_write
from app.core.domain.stock_movements import StockMovementContext
from app.core.security.access_policy import has_permission
from app.core.utils.unit_conversion import is_count_unit


class TransferError(ValueError):
    pass


def _id(value):
    try:
        return UUID(str(value))
    except (ValueError, TypeError):
        raise TransferError("Invalid stock, site or location ID") from None


def _quantity(value, *, positive=False, unit=None):
    try:
        amount = Decimal(str(value))
        if (
            not amount.is_finite()
            or amount < 0
            or amount > Decimal("99999999999999.9999")
            or amount != amount.quantize(Decimal("0.0001"))
            or (positive and amount == 0)
        ):
            raise ValueError
    except (InvalidOperation, ValueError, TypeError):
        raise TransferError("Quantity must be a finite nonnegative number with at most four decimal places") from None
    if unit and is_count_unit(unit) and amount != amount.to_integral_value():
        raise TransferError("Counted goods must move in whole numbers")
    return amount


def _date(value):
    try:
        day = date.today() if value is None else date.fromisoformat(value)
        if day > date.today():
            raise ValueError
        return day
    except (ValueError, TypeError):
        raise TransferError("Choose a valid movement date, no later than today") from None


def _string(value, name, limit, required=True):
    if not isinstance(value, str) or len(value.strip()) > limit or (required and not value.strip()):
        raise TransferError(f"{name} must be {'nonempty ' if required else ''}text, up to {limit} characters")
    return value.strip()


def _freeze(value):
    if isinstance(value, dict):
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_freeze(item) for item in value)
    return value


def _hash(data):
    return hashlib.sha256(json.dumps(data, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


def _key_lock(session, org_id, key, operation):
    key = _string(key, "Idempotency-Key", 128)
    lock = int.from_bytes(
        hashlib.sha256(f"site-transfers:{operation}:{org_id}:{key}".encode()).digest()[:8], "big", signed=True
    )
    session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": lock})
    return key


def _actor_and_release(session, org_id, actor_id):
    org = (
        session.query(Organisation.multiple_sites_enabled, Organisation.multiple_site_operations_enabled)
        .filter(Organisation.id == org_id)
        .with_for_update(read=True)
        .one_or_none()
    )
    if not org or not org.multiple_sites_enabled or not org.multiple_site_operations_enabled:
        raise TransferError("Site transfer operations are not released yet")
    actor = session.query(User).filter(User.org_id == org_id, User.id == actor_id).one_or_none()
    if not actor or not has_permission(actor, "inventory.adjust"):
        raise TransferError("Receiving, dispatching and confirming losses require inventory.adjust")


def _location(session, org_id, site_id, location_id):
    if location_id is None:
        return
    row = (
        session.query(StockLocation)
        .filter(
            StockLocation.org_id == org_id,
            StockLocation.id == location_id,
            StockLocation.site_id == site_id,
            StockLocation.is_active.is_(True),
        )
        .with_for_update(read=True)
        .one_or_none()
    )
    if row is None:
        raise TransferError("Location must be active and belong to the selected site")


def _decision(policy, session, org_id, context):
    if policy is None:
        raise TransferError("A stock movement policy provider is required")
    result = policy(session, org_id, context)
    if result.allowed is not True:
        raise TransferError(result.reason or "This stock movement is not permitted")
    # Copy canonical provider evidence into this ledger, not a mutable provider object.
    evidence = (
        json.loads(result.evidence) if isinstance(result.evidence, str) else json.loads(json.dumps(result.evidence))
    )
    if not isinstance(evidence, dict):
        raise TransferError("Movement policy evidence must be a JSON object")
    return evidence


def _context(
    transfer,
    operation,
    quantity,
    occurred_on,
    approval,
    actor_id,
    receipt_id=None,
    loss_reason=None,
    damaged_quantity=Decimal("0"),
    short_quantity=Decimal("0"),
    prepared_context=None,
):
    return StockMovementContext(
        operation=operation,
        source_site_id=transfer.source_site_id,
        destination_site_id=transfer.destination_site_id,
        source_location_id=transfer.source_location_id,
        destination_location_id=transfer.destination_location_id,
        source_item_id=transfer.source_item_id,
        product_name=transfer.source_snapshot["name"],
        inventory_type=transfer.source_snapshot["inventory_type"],
        quantity=quantity,
        unit=transfer.unit,
        occurred_on=occurred_on,
        carrier=transfer.carrier,
        consignment_reference=transfer.consignment_reference,
        approval=_freeze(approval),
        transfer_id=transfer.id,
        receipt_id=receipt_id,
        actor_id=actor_id,
        source_snapshot=_freeze(transfer.source_snapshot),
        dispatch_evidence=json.dumps(transfer.decision_snapshot or {}, sort_keys=True),
        loss_reason=loss_reason,
        damaged_quantity=damaged_quantity,
        short_quantity=short_quantity,
        prepared_context=_freeze(prepared_context or {}),
    )


def get_transfer(session, org_id, transfer_id, lock=False):
    query = session.query(SiteStockTransfer).filter(
        SiteStockTransfer.org_id == org_id, SiteStockTransfer.id == _id(transfer_id)
    )
    return query.with_for_update().populate_existing().one_or_none() if lock else query.one_or_none()


def dispatch(session, org_id, actor_id, key, data, policy, prepare_context=None):
    if not isinstance(data, dict) or set(data) - {
        "source_item_id",
        "destination_site_id",
        "destination_location_id",
        "quantity",
        "carrier",
        "consignment_reference",
        "occurred_on",
        "approval",
    }:
        raise TransferError("Unknown dispatch field")
    # Keep advisory idempotency serialization before module preparation. Contract
    # preparation may lock Step -> Execution -> Order; the Org/Site/Inventory locks
    # below must never precede those locks.
    key = _key_lock(session, org_id, key, "dispatch")
    request_hash = _hash(data)
    prior = (
        session.query(SiteStockTransfer)
        .filter(SiteStockTransfer.org_id == org_id, SiteStockTransfer.idempotency_key == key)
        .one_or_none()
    )
    if prior:
        _actor_and_release(session, org_id, actor_id)
        if prior.request_hash != request_hash:
            raise TransferError("Idempotency key already used for different dispatch details")
        return prior, True
    prepared = prepare_context(session, org_id, _id(data.get("source_item_id"))) if prepare_context else {}
    if not isinstance(prepared, dict):
        raise TransferError("Movement preparation must return a plain evidence object")
    _actor_and_release(session, org_id, actor_id)
    item = (
        session.query(InventoryItem)
        .filter(InventoryItem.org_id == org_id, InventoryItem.id == _id(data.get("source_item_id")))
        .with_for_update()
        .populate_existing()
        .one_or_none()
    )
    if item is None:
        raise TransferError("Source stock not found")
    if "contract_customer_id" in (item.extra_data or {}):
        raise TransferError("Legacy customer ownership must be resolved before transfer")
    if item.contract_customer_id is not None:
        enabled = (
            session.query(Organisation.contract_materials_enabled)
            .filter(Organisation.id == org_id)
            .with_for_update(read=True)
            .scalar()
        )
        if not enabled:
            raise TransferError("Customer material operations are switched off")
    source_site = resolve_site(session, org_id, item.site_id)
    destination_site = resolve_site(session, org_id, _id(data.get("destination_site_id")))
    destination_location = _id(data["destination_location_id"]) if data.get("destination_location_id") else None
    _location(session, org_id, source_site, item.location_id)
    _location(session, org_id, destination_site, destination_location)
    if source_site == destination_site and item.location_id == destination_location:
        raise TransferError("Choose a different destination")
    amount = _quantity(data.get("quantity"), positive=True, unit=item.unit)
    if amount > item.quantity:
        raise TransferError("Dispatch quantity exceeds available shelf stock")
    approval = data.get("approval", {})
    if not isinstance(approval, dict):
        raise TransferError("approval must be an object")
    sites = {
        site.id: site
        for site in session.query(Site).filter(Site.org_id == org_id, Site.id.in_({source_site, destination_site}))
    }
    snapshot = _item_snapshot(item)
    snapshot["barcode"] = item.barcode or (item.extra_data or {}).get("original_barcode")
    snapshot["contract_customer_id"] = str(item.contract_customer_id) if item.contract_customer_id else None
    snapshot["source_site"] = {
        "id": str(source_site),
        "name": sites[source_site].name,
        "address": sites[source_site].address,
    }
    snapshot["destination_site"] = {
        "id": str(destination_site),
        "name": sites[destination_site].name,
        "address": sites[destination_site].address,
    }
    transfer = SiteStockTransfer(
        id=uuid4(),
        org_id=org_id,
        source_item_id=item.id,
        source_site_id=source_site,
        destination_site_id=destination_site,
        source_location_id=item.location_id,
        destination_location_id=destination_location,
        quantity=amount,
        received_quantity=0,
        loss_quantity=0,
        unit=item.unit,
        carrier=_string(data.get("carrier"), "Carrier", 120),
        consignment_reference=_string(data.get("consignment_reference"), "Consignment reference", 160),
        occurred_on=_date(data.get("occurred_on")),
        source_snapshot=snapshot,
        decision_snapshot={},
        idempotency_key=key,
        request_hash=request_hash,
        created_by_user_id=actor_id,
    )
    transfer.decision_snapshot = _decision(
        policy,
        session,
        org_id,
        _context(transfer, "dispatch", amount, transfer.occurred_on, approval, actor_id, prepared_context=prepared),
    )
    before = item.quantity
    with allow_transfer_accounting(), allow_inventory_quantity_write(InventoryQuantityWriteReason.STOCK_TRANSFER):
        session.add(transfer)
        item.quantity -= amount
        session.flush()
        session.add(
            InventoryMovement(
                org_id=org_id,
                inventory_item_id=item.id,
                movement_type="TRANSFER_OUT",
                quantity=-amount,
                unit=item.unit,
                movement_metadata={"site_transfer_id": str(transfer.id)},
            )
        )
        EventWriter(session, org_id).emit(
            event_type="inventory_item.quantity_adjusted",
            entity_type="inventory_item",
            entity_id=item.id,
            payload={
                **_item_snapshot(item),
                "quantity_before": str(before),
                "quantity_after": str(item.quantity),
                "delta": str(-amount),
                "reason": "site_transfer_dispatch",
                "site_transfer_id": str(transfer.id),
            },
        )
    return transfer, False


def receive(session, org_id, actor_id, transfer_id, key, data, policy):
    if not isinstance(data, dict) or set(data) - {
        "quantity",
        "damaged_quantity",
        "short_quantity",
        "confirm_loss",
        "loss_reason",
        "occurred_on",
    }:
        raise TransferError("Unknown receipt field")
    _actor_and_release(session, org_id, actor_id)
    key = _key_lock(session, org_id, key, "receipt")
    request_hash = _hash({"transfer_id": str(_id(transfer_id)), **data})
    prior = (
        session.query(SiteStockReceipt)
        .filter(SiteStockReceipt.org_id == org_id, SiteStockReceipt.idempotency_key == key)
        .one_or_none()
    )
    if prior:
        if prior.request_hash != request_hash:
            raise TransferError("Idempotency key already used for different receipt details")
        return prior, True
    transfer = get_transfer(session, org_id, transfer_id, lock=True)
    if transfer is None:
        raise TransferError("Transfer not found")
    resolve_site(session, org_id, transfer.source_site_id)
    resolve_site(session, org_id, transfer.destination_site_id)
    _location(session, org_id, transfer.destination_site_id, transfer.destination_location_id)
    good = _quantity(data.get("quantity", 0), unit=transfer.unit)
    damaged = _quantity(data.get("damaged_quantity", 0), unit=transfer.unit)
    short = _quantity(data.get("short_quantity", 0), unit=transfer.unit)
    loss, resolved = damaged + short, good + damaged + short
    if resolved == 0 or resolved > transfer.quantity - transfer.received_quantity - transfer.loss_quantity:
        raise TransferError(
            "Receipt and confirmed loss must be positive and cannot exceed remaining transit stock; overages need review"
        )
    if loss and data.get("confirm_loss") is not True:
        raise TransferError("A discrepancy remains in transit until its loss is explicitly confirmed")
    reason = _string(data.get("loss_reason"), "Loss reason", 500) if loss else None
    occurred = _date(data.get("occurred_on"))
    if occurred < transfer.occurred_on:
        raise TransferError("Receipt date cannot precede dispatch")
    receipt_id = uuid4()
    decisions = {}
    if good:
        decisions["receipt"] = _decision(
            policy, session, org_id, _context(transfer, "receipt", good, occurred, {}, actor_id, receipt_id)
        )
    if loss:
        decisions["loss"] = _decision(
            policy,
            session,
            org_id,
            _context(
                transfer,
                "loss",
                loss,
                occurred,
                {},
                actor_id,
                receipt_id,
                loss_reason=reason,
                damaged_quantity=damaged,
                short_quantity=short,
            ),
        )
    receipt = SiteStockReceipt(
        id=receipt_id,
        org_id=org_id,
        transfer_id=transfer.id,
        quantity=good,
        damaged_quantity=damaged,
        short_quantity=short,
        loss_reason=reason,
        occurred_on=occurred,
        decision_snapshot=decisions,
        idempotency_key=key,
        request_hash=request_hash,
        created_by_user_id=actor_id,
    )
    with allow_transfer_accounting():
        session.add(receipt)
        session.flush()
        if good:
            source = transfer.source_snapshot
            values = {
                key: source.get(key)
                for key in ("name", "unit", "inventory_type", "supplier", "supplier_batch_number", "source_step_name")
            }
            for key in ("source_execution_id", "source_execution_step_id", "source_output_id"):
                values[key] = _id(source[key]) if source.get(key) else None
            for key in ("purchase_date", "expiry_date"):
                values[key] = date.fromisoformat(source[key]) if source.get(key) else None
            item = InventoryRepository(session).create_inventory_item(
                org_id=org_id,
                quantity=good,
                barcode=None,
                site_id=transfer.destination_site_id,
                location_id=transfer.destination_location_id,
                transfer_receipt_id=receipt.id,
                contract_customer_id=_id(source["contract_customer_id"])
                if source.get("contract_customer_id")
                else None,
                extra_data={
                    **source.get("extra_data", {}),
                    "moved_from_item_id": str(transfer.source_item_id),
                    "original_barcode": source.get("barcode"),
                    "site_transfer_id": str(transfer.id),
                },
                commit=False,
                write_reason=InventoryQuantityWriteReason.STOCK_TRANSFER,
                **values,
            )
            session.add(
                InventoryMovement(
                    org_id=org_id,
                    inventory_item_id=item.id,
                    movement_type="TRANSFER_IN",
                    quantity=good,
                    unit=transfer.unit,
                    movement_metadata={"site_transfer_id": str(transfer.id), "receipt_id": str(receipt.id)},
                )
            )
        transfer.received_quantity += good
        transfer.loss_quantity += loss
        session.flush()
        EventWriter(session, org_id).emit(
            event_type="site_transfer.received",
            entity_type="site_transfer",
            entity_id=transfer.id,
            payload={
                "site_transfer_id": str(transfer.id),
                "receipt_id": str(receipt.id),
                "received_quantity": str(good),
                "confirmed_loss_quantity": str(loss),
                "loss_reason": reason,
            },
        )
    return receipt, False


def serialise_transfer(transfer):
    transit = transfer.quantity - transfer.received_quantity - transfer.loss_quantity
    return {
        "id": str(transfer.id),
        "source_item_id": str(transfer.source_item_id),
        "source_site_id": str(transfer.source_site_id),
        "destination_site_id": str(transfer.destination_site_id),
        "source_location_id": str(transfer.source_location_id) if transfer.source_location_id else None,
        "destination_location_id": str(transfer.destination_location_id) if transfer.destination_location_id else None,
        "product_name": transfer.source_snapshot["name"],
        "quantity": str(transfer.quantity),
        "received_quantity": str(transfer.received_quantity),
        "confirmed_loss_quantity": str(transfer.loss_quantity),
        "transit_quantity": str(transit),
        "unit": transfer.unit,
        "carrier": transfer.carrier,
        "consignment_reference": transfer.consignment_reference,
        "occurred_on": transfer.occurred_on.isoformat(),
        "status": "received"
        if transit == 0
        else ("part_received" if transfer.received_quantity or transfer.loss_quantity else "in_transit"),
    }
