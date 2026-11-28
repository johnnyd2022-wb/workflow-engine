"""Inventory request fields aligned with the lot and movement storage types."""

from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, JsonValue, StringConstraints

from app.core.db.models.inventory_item import InventoryType
from app.utils.request_validation import CleanName, CleanText, JsonInput, OptionalIsoDateTime

Quantity = Annotated[Decimal, Field(ge=0, max_digits=18, decimal_places=4)]
PositiveQuantity = Annotated[Quantity, Field(gt=0)]
LotText = Annotated[CleanText, StringConstraints(max_length=255)]
LotName = Annotated[CleanName, StringConstraints(max_length=255)]
LotUnit = Annotated[CleanName, StringConstraints(max_length=50)]
OptionalLotUnit = Annotated[CleanText, StringConstraints(max_length=50)]
InventoryDate = OptionalIsoDateTime
OptionalId = UUID | Literal[""] | None


class LotFields(JsonInput):
    inventory_type: InventoryType = InventoryType.RAW_MATERIAL
    supplier: LotText | None = None
    supplier_batch_number: LotText | None = None
    expiry_date: InventoryDate = None
    purchase_date: InventoryDate = None
    barcode: LotText | None = None
    metadata: dict[str, JsonValue] | None = None
    pack: dict[str, JsonValue] | Annotated[str, StringConstraints(max_length=60)] | None = None


class CreateInventoryInput(LotFields):
    name: LotText | None = None
    unit: OptionalLotUnit | None = None
    quantity: PositiveQuantity
    source_execution_id: OptionalId = None
    source_execution_step_id: OptionalId = None
    source_output_id: OptionalId = None
    source_method: Literal["manual", "csv_upload", "barcode_scan", ""] | None = None
    notes: Annotated[str, StringConstraints(max_length=10_000, pattern=r"^[^\x00]*$")] | None = None
    untracked: bool = False
    remaining_balance_to_reconcile: Quantity | None = None
    site_id: UUID | None = None
    total_paid: Decimal | Literal[""] | None = None


class UpdateInventoryInput(LotFields):
    name: LotName
    unit: LotUnit
    quantity: Quantity


class AdjustQuantityInput(JsonInput):
    new_quantity: Quantity


class ConsumeFifoInput(JsonInput):
    name: LotName
    quantity: PositiveQuantity
    reference: LotText | None = None
    site_id: UUID | None = None
