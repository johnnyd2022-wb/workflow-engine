"""Immutable physical facts supplied to a generic movement-policy provider."""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from uuid import UUID


@dataclass(frozen=True)
class StockMovementContext:
    operation: str
    source_site_id: UUID
    destination_site_id: UUID
    source_location_id: UUID | None
    destination_location_id: UUID | None
    source_item_id: UUID
    product_name: str
    inventory_type: str
    quantity: Decimal
    unit: str
    occurred_on: date
    carrier: str
    consignment_reference: str
    approval: Mapping
    transfer_id: UUID
    receipt_id: UUID | None
    actor_id: UUID
    source_snapshot: Mapping
    dispatch_evidence: str
    loss_reason: str | None = None
    damaged_quantity: Decimal = Decimal("0")
    short_quantity: Decimal = Decimal("0")
