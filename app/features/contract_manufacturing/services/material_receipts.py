"""Recorded free-issue raw receipts; no producer purchase or output title inferred."""

import hashlib
import json
from datetime import date
from decimal import Decimal, InvalidOperation
from uuid import UUID, uuid4

from sqlalchemy import text

from app.core.backend.event_writer import EventWriter
from app.core.db.models.inventory_item import InventoryItem
from app.core.db.models.organisation import Organisation
from app.core.db.models.site import Site
from app.core.db.models.stock_location import StockLocation
from app.core.db.models.user import User
from app.core.db.repositories.inventory_repo import InventoryRepository
from app.core.db.site_operations import resolve_site
from app.core.security.permissions import has_permission
from app.core.utils.unit_conversion import whole_count_error
from app.features.contract_manufacturing.models import ContractCustomer, ContractMaterialReceipt
from app.features.contract_manufacturing.services.orders import OrderError, identifier, object_body, text_value
from app.features.contract_manufacturing.services.stock_guard import recorded_material_receipt


def _date(value, field):
    if value in (None, ""):
        return None
    try:
        return date.fromisoformat(value)
    except (ValueError, TypeError):
        raise OrderError(f"{field} must be an ISO date") from None


def receive_material(db, org_id, customer_id, actor_id, key, data):
    if not isinstance(org_id, UUID):
        raise OrderError("Authenticated organisation required", 403)
    if not isinstance(data, dict):
        raise OrderError("JSON object required")
    object_body(
        data,
        {
            "name",
            "quantity",
            "unit",
            "supplier",
            "supplier_batch_number",
            "purchase_date",
            "expiry_date",
            "evidence_reference",
            "site_id",
            "location_id",
            "barcode",
        },
    )
    customer_id = identifier(customer_id, "customer_id")
    key = text_value(key, "Idempotency-Key", 128)
    request_hash = hashlib.sha256(
        json.dumps({"customer_id": str(customer_id), "data": data}, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    lock_key = int.from_bytes(hashlib.sha256(f"contract-raw:{org_id}:{key}".encode()).digest()[:8], "big", signed=True)
    db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": lock_key})
    org = (
        db.query(Organisation.contract_materials_enabled)
        .filter(Organisation.id == org_id)
        .with_for_update(read=True)
        .one_or_none()
    )
    actor = (
        db.query(User)
        .filter(User.org_id == org_id, User.id == identifier(actor_id, "actor_id"), User.is_active.is_(True))
        .one_or_none()
    )
    if actor is None or not has_permission(actor, "inventory.adjust"):
        raise OrderError("Receiving customer materials requires inventory.adjust", 403)
    if org is None or not org.contract_materials_enabled:
        raise OrderError("Customer material operations are switched off", 409)
    customer = (
        db.query(ContractCustomer)
        .filter(ContractCustomer.org_id == org_id, ContractCustomer.id == customer_id)
        .with_for_update(read=True)
        .populate_existing()
        .one_or_none()
    )
    if customer is None:
        raise OrderError("Customer not found", 404)
    prior = (
        db.query(ContractMaterialReceipt)
        .filter(ContractMaterialReceipt.org_id == org_id, ContractMaterialReceipt.idempotency_key == key)
        .one_or_none()
    )
    if prior:
        if prior.request_hash != request_hash:
            raise OrderError("Idempotency key already used for different receipt details", 409)
        return prior, True
    if not customer.is_active:
        raise OrderError("Customer is inactive", 409)
    name = text_value(data.get("name"), "name", 255)
    unit = text_value(data.get("unit"), "unit", 50)
    try:
        amount = Decimal(str(data.get("quantity")))
    except (InvalidOperation, ValueError, TypeError):
        raise OrderError("quantity must be a positive decimal") from None
    if (
        not amount.is_finite()
        or amount <= 0
        or amount >= Decimal("100000000000000")
        or amount != amount.quantize(Decimal("0.0001"))
    ):
        raise OrderError("quantity must be positive within storage limits, with at most four decimal places")
    count_error = whole_count_error(amount, unit, what=name)
    if count_error:
        raise OrderError(count_error)
    site_id = resolve_site(db, org_id, identifier(data["site_id"], "site_id") if data.get("site_id") else None)
    if site_id is None:
        default = (
            db.query(Site)
            .filter(Site.org_id == org_id, Site.is_default.is_(True), Site.is_active.is_(True))
            .with_for_update(read=True)
            .one_or_none()
        )
        site_id = default.id if default else None
    location_id = identifier(data["location_id"], "location_id") if data.get("location_id") else None
    if (
        location_id is not None
        and db.query(StockLocation.id)
        .filter(
            StockLocation.org_id == org_id,
            StockLocation.id == location_id,
            StockLocation.site_id == site_id,
            StockLocation.is_active.is_(True),
        )
        .with_for_update(read=True)
        .first()
        is None
    ):
        raise OrderError("Location must be active and belong to the selected site", 404)
    purchase = _date(data.get("purchase_date"), "purchase_date")
    expiry = _date(data.get("expiry_date"), "expiry_date")
    if purchase and expiry and expiry < purchase:
        raise OrderError("Expiry cannot be before receipt purchase date")
    supplier = text_value(data.get("supplier"), "supplier", 255, False)
    batch = text_value(data.get("supplier_batch_number"), "supplier_batch_number", 255, False)
    original_barcode = text_value(data.get("barcode"), "barcode", 255, False)
    snapshot = {
        "name": name,
        "unit": unit,
        "supplier": supplier,
        "supplier_batch_number": batch,
        "purchase_date": str(purchase) if purchase else None,
        "expiry_date": str(expiry) if expiry else None,
        "site_id": str(site_id) if site_id else None,
        "location_id": str(location_id) if location_id else None,
        "original_barcode": original_barcode,
        "free_issue_acquisition_cost": "0",
    }
    receipt = ContractMaterialReceipt(
        id=uuid4(),
        org_id=org_id,
        customer_id=customer.id,
        inventory_item_id=uuid4(),
        quantity=amount,
        unit=unit,
        evidence_reference=text_value(data.get("evidence_reference"), "evidence_reference", 255),
        stock_snapshot=snapshot,
        idempotency_key=key,
        request_hash=request_hash,
        received_by=actor.id,
    )
    with recorded_material_receipt():
        db.add(receipt)
        db.flush()
        InventoryRepository(db).create_inventory_item(
            org_id=org_id,
            inventory_item_id=receipt.inventory_item_id,
            name=name,
            quantity=amount,
            unit=unit,
            inventory_type="raw_material",
            supplier=supplier,
            supplier_batch_number=batch,
            purchase_date=purchase,
            expiry_date=expiry,
            site_id=site_id,
            location_id=location_id,
            contract_customer_id=customer.id,
            material_receipt_id=receipt.id,
            barcode=None,
            extra_data={
                "original_barcode": original_barcode,
                "free_issue_acquisition_cost": "0",
                "origin_material_receipt_id": str(receipt.id),
            },
            commit=False,
        )
        EventWriter(db, org_id).emit(
            event_type="contract.material_received",
            entity_type="contract_material_receipt",
            entity_id=receipt.id,
            payload={
                "customer_id": str(customer.id),
                "inventory_item_id": str(receipt.inventory_item_id),
                "quantity": str(amount),
                "unit": unit,
                "evidence_reference": receipt.evidence_reference,
                "producer_acquisition_value_included": False,
            },
        )
    return receipt, False


def customer_materials(db, org_id, customer_id):
    customer_id = identifier(customer_id, "customer_id")
    if (
        db.query(ContractCustomer.id)
        .filter(ContractCustomer.org_id == org_id, ContractCustomer.id == customer_id)
        .first()
        is None
    ):
        raise OrderError("Customer not found", 404)
    return (
        db.query(InventoryItem)
        .filter(InventoryItem.org_id == org_id, InventoryItem.contract_customer_id == customer_id)
        .order_by(InventoryItem.created_at.desc(), InventoryItem.id)
        .limit(1000)
        .all()
    )


def material_dto(item):
    return {
        "id": str(item.id),
        "name": item.name,
        "quantity": str(item.quantity),
        "unit": item.unit,
        "contract_customer_id": str(item.contract_customer_id),
        "supplier_batch_number": item.supplier_batch_number,
        "site_id": str(item.site_id) if item.site_id else None,
        "location_id": str(item.location_id) if item.location_id else None,
        "material_receipt_id": str(item.material_receipt_id) if item.material_receipt_id else None,
        "transfer_receipt_id": str(item.transfer_receipt_id) if item.transfer_receipt_id else None,
        "producer_acquisition_value_included": False,
        "free_issue_acquisition_cost": "0",
    }
