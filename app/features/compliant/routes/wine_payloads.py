"""Typed input for the wine plan, register and export records."""

from datetime import date
from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field

from app.features.compliant.routes.register_payloads import OptionalUUID
from app.features.compliant.routes.validation_payloads import OptionalDate
from app.utils.request_validation import CleanName, CleanText, JsonInput

EvidenceReference = Annotated[CleanText, Field(max_length=1024)]
Litres = Annotated[Decimal, Field(gt=0, le=10_000_000)]


class WinePlanInput(JsonInput):
    mode: Literal["registered", "exempt"]
    plan_reference: CleanText | None = Field(default=None, max_length=200)
    verifier: CleanText | None = Field(default=None, max_length=200)
    next_verification: OptionalDate = None
    exemption_start: OptionalDate = None
    wine_exporter: bool = False
    wine_swnz: bool = False
    wine_organic: bool = False


class WineRecordInput(JsonInput):
    framework: CleanName = Field(max_length=80)
    control: CleanName = Field(max_length=120)
    title: CleanName = Field(max_length=255)
    done_on: OptionalDate = None
    next_due: OptionalDate = None
    evidence_reference: EvidenceReference | None = None


class WineProblemInput(JsonInput):
    kind: Literal["critical", "export", "recall"]
    description: CleanName = Field(max_length=500)
    lot_id: OptionalUUID = None


class WineLabelApprovalInput(JsonInput):
    lot_id: UUID | None = None
    label_version: CleanName = Field(max_length=120)
    evidence_reference: EvidenceReference | None = None


class WineEligibilityInput(JsonInput):
    lot_id: UUID
    form: Literal["packaged", "bulk"] | None = None
    granted_on: OptionalDate = None
    ees_reference: CleanText | None = Field(default=None, max_length=120)
    eligible_litres: Litres | None = None
    markets: CleanText | None = Field(default=None, max_length=300)


class WineConsignmentInput(JsonInput):
    kind: Literal["commercial", "trade_sample", "small_trade"]
    litres: Litres
    shipped_on: date
    market: CleanName = Field(max_length=80)
    consignee: CleanName = Field(max_length=200)
    customs_entry: CleanText | None = Field(default=None, max_length=120)
    eligibility_id: OptionalUUID = None
    lot_id: OptionalUUID = None
    not_for_sale_marked: bool | Literal["1"] = False
