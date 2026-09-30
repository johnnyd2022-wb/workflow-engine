"""Validate a received stock fragment against immutable dispatch/receipt facts."""

from decimal import Decimal

from app.core.db.models.inventory_item import InventoryItem
from app.core.db.models.site_transfer import SiteStockReceipt, SiteStockTransfer
from app.core.db.site_guard import SiteScopeError

PROVENANCE_FIELDS = (
    "contract_customer_id",
    "name",
    "unit",
    "inventory_type",
    "supplier",
    "purchase_date",
    "supplier_batch_number",
    "expiry_date",
    "source_execution_id",
    "source_execution_step_id",
    "source_output_id",
    "source_step_name",
)


def _scalar(value):
    return str(value) if value is not None else None


def receipt_proofs(session, affected):
    ids = {obj.transfer_receipt_id for obj in affected if isinstance(obj, InventoryItem) and obj.transfer_receipt_id}
    if not ids:
        return {}
    org_ids = {obj.org_id for obj in affected}
    rows = (
        session.query(SiteStockReceipt, SiteStockTransfer)
        .join(
            SiteStockTransfer,
            (SiteStockReceipt.org_id == SiteStockTransfer.org_id)
            & (SiteStockReceipt.transfer_id == SiteStockTransfer.id),
        )
        .filter(SiteStockReceipt.id.in_(ids), SiteStockReceipt.org_id.in_(org_ids))
        .with_for_update(read=True)
        .all()
    )
    return {(receipt.org_id, receipt.id): (receipt, transfer) for receipt, transfer in rows}


def validate_receipt_fragment(session, item, proof):
    if proof is None:
        raise SiteScopeError("Recorded receipt not found in this organisation")
    receipt, transfer = proof
    if item.site_id != transfer.destination_site_id or item.location_id != transfer.destination_location_id:
        raise SiteScopeError("Received stock must stay at its recorded destination")
    for key in PROVENANCE_FIELDS:
        if _scalar(getattr(item, key)) != _scalar(transfer.source_snapshot.get(key)):
            raise SiteScopeError("Received stock must preserve its recorded source lineage, product and unit")
    if item.barcode is not None:
        raise SiteScopeError("A received fragment cannot duplicate its source barcode")
    if item in session.new and Decimal(str(item.quantity)) != receipt.quantity:
        raise SiteScopeError("Received stock must equal the approved receipt quantity")
    if item.extra_data != {
        **transfer.source_snapshot.get("extra_data", {}),
        "moved_from_item_id": str(transfer.source_item_id),
        "original_barcode": transfer.source_snapshot.get("barcode"),
        "site_transfer_id": str(transfer.id),
    }:
        raise SiteScopeError("Received stock must preserve its recorded source metadata")
