"""Request fields for compliance reports, excise and national programme verification."""

from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BeforeValidator, ConfigDict, Field, field_validator, model_validator

from app.utils.request_validation import CleanName, CleanText, JsonInput, StoredJson, validate_json_storage


def _optional_date(value):
    if value == "":
        return None
    return date.fromisoformat(value) if isinstance(value, str) else value


def _optional_decimal(value):
    if value == "":
        return None
    if type(value) in (str, int, float):
        try:
            return Decimal(str(value))
        except InvalidOperation:
            raise ValueError("Enter a number.") from None
    return value


OptionalDate = Annotated[date | None, BeforeValidator(_optional_date)]
OptionalDecimal = Annotated[Decimal | None, BeforeValidator(_optional_decimal)]


class ReportInput(JsonInput):
    period_start: OptionalDate = None
    period_end: OptionalDate = None


class ExciseSettingsInput(JsonInput):
    frequency: Literal["monthly", "six_monthly", "twelve_monthly"] = "monthly"
    tracking_from: OptionalDate = None


class ExciseLodgementInput(JsonInput):
    period_start: date
    lodged_on: OptionalDate = None
    entry_reference: CleanText | None = Field(default=None, max_length=100)
    cca: UUID | None = None


class ExciseRateInput(JsonInput):
    tariff_item: CleanName = Field(max_length=100)
    rate_per_lal: Decimal = Field(ge=0, max_digits=12, decimal_places=4)
    effective_from: date
    description: CleanText | None = Field(default=None, max_length=255)


class ExciseProductInput(JsonInput):
    name: CleanName = Field(max_length=255)
    product_type: CleanText = Field(default="spirits", max_length=40)
    pack_volume_ml: OptionalDecimal = Field(default=None, gt=0, le=100000, decimal_places=2)
    abv_fallback: OptionalDecimal = Field(default=None, ge=0, le=100, decimal_places=4)
    tariff_item: CleanText | None = Field(default=None, max_length=100)
    excise_category: CleanText | None = Field(default=None, max_length=40)


class VerificationContextInput(JsonInput):
    registration_id: UUID | None = None


class CorrectiveActionInput(JsonInput):
    description: CleanName = Field(max_length=500)
    due_on: date
    owner_name: CleanText | None = Field(default=None, max_length=255)
    owner_user_id: UUID | None = None


# The form sends select values as strings. Older clients also send integers.
Step = Annotated[int, Field(ge=1, le=8)] | Literal["1", "2", "3", "4", "5", "6", "7", "8"]


class VerificationInput(VerificationContextInput):
    verified_on: date
    verifier_name: CleanName = Field(max_length=255)
    outcome: Literal["acceptable", "unacceptable"]
    verifier_agency: CleanText | None = Field(default=None, max_length=255)
    report_reference: CleanText | None = Field(default=None, max_length=255)
    initial: bool = False
    attitude: Literal["willing", "unwilling", "immediate_risk", ""] | None = None
    step: Step | None = None
    previous_step: Step | None = None
    next_due: OptionalDate = None
    notes: str | None = Field(default=None, max_length=4000, pattern=r"^[^\x00]*$")
    actions: list[CorrectiveActionInput] = Field(default_factory=list, max_length=100)

    @field_validator("step", "previous_step", mode="before")
    @classmethod
    def empty_optional(cls, value):
        return None if value == "" else value


class VerificationCompletionInput(VerificationContextInput):
    note: str | None = Field(default=None, max_length=500, pattern=r"^[^\x00]*$")


class VerificationRegistrationInput(VerificationContextInput):
    registered_on: date
    registered_as: Literal["new", "existing"]


def _integer(value):
    if type(value) is not int:
        raise ValueError("Enter a whole number.")
    return value


ReviewInterval = Annotated[Literal[1, 3, 6, 12], BeforeValidator(_integer)]


class ReviewIntervalInput(JsonInput):
    review_interval_months: ReviewInterval


class AlcoholProductInput(JsonInput):
    inventory_name: CleanName = Field(max_length=255)
    product_type: Literal["beer", "spirits", "wine", "cider", "mead", "rtd", "other"]
    abv_percent: Decimal = Field(gt=0, le=100, decimal_places=4)
    customs_product_code: CleanText | None = Field(default=None, max_length=100)


class ComplianceSettings(JsonInput):
    # Module-specific settings and persisted configuration are carried through this endpoint.
    model_config = ConfigDict(extra="allow")
    food_control_programme: Literal["np1", "np2", "np3", "none"] | None = None
    np3_review_interval_months: ReviewInterval | None = None
    np3_check_review_intervals: dict[CleanName, ReviewInterval] | None = None
    liquor_licence_types: list[Literal["on", "off", "club", "special"]] | None = Field(default=None, max_length=4)
    alcohol_product_types: list[Literal["beer", "spirits", "wine", "cider", "mead", "rtd", "other"]] | None = Field(
        default=None, max_length=7
    )
    np3_verification_date: OptionalDate = None
    np3_verifier_name: CleanText | None = Field(default=None, max_length=255)
    np3_verification_location: CleanText | None = Field(default=None, max_length=255)
    liquor_licence_reference: CleanText | None = Field(default=None, max_length=255)
    liquor_licence_due_date: OptionalDate = None
    require_core_source_refs: bool | None = None

    @model_validator(mode="before")
    @classmethod
    def jsonb_values(cls, value):
        return validate_json_storage(value)


class ComplianceProfileInput(JsonInput):
    enabled: bool = False
    industry_module: CleanName = Field(default="nz_alcohol", max_length=80)
    council_name: CleanText | None = Field(default=None, max_length=255)
    trade_waste_consent_reference: CleanText | None = Field(default=None, max_length=255)
    settings: ComplianceSettings = Field(default_factory=ComplianceSettings)


class ComplianceRecordInput(ReportInput):
    framework_slug: CleanName = Field(max_length=80)
    control_id: CleanName = Field(max_length=120)
    record_type: Literal["attestation", "reading", "lodgement", "competency", "incident"]
    status: Literal["complete", "failed", "open", "superseded"] = "complete"
    title: CleanName = Field(max_length=255)
    due_date: OptionalDate = None
    measured_value: OptionalDecimal = Field(default=None, max_digits=18, decimal_places=4)
    limit_value: OptionalDecimal = Field(default=None, max_digits=18, decimal_places=4)
    declared_litres_of_alcohol: OptionalDecimal = Field(default=None, ge=0, max_digits=18, decimal_places=4)
    evidence_reference: CleanText | None = Field(default=None, max_length=1024)
    source_refs: list[Annotated[CleanName, Field(max_length=36)]] = Field(default_factory=list, max_length=30)
    details: dict[CleanName, StoredJson] = Field(default_factory=dict)


EvidenceText = Annotated[str, Field(max_length=1024, pattern=r"^[^\x00]*$")]


class AttestationInput(JsonInput):
    control_id: CleanName = Field(max_length=120)
    confirmed: bool
    how_we_meet: str = Field(min_length=1, max_length=4000, pattern=r"^[^\x00]*$")
    review_interval_months: ReviewInterval = 6
    evidence_reference: CleanText | None = Field(default=None, max_length=1024)
    source_refs: list[Annotated[CleanName, Field(max_length=36)]] = Field(default_factory=list, max_length=30)
    evidence_fields: dict[CleanName, EvidenceText] = Field(default_factory=dict)


class NPLogInput(JsonInput):
    fields: dict[CleanName, Annotated[str, Field(max_length=4000, pattern=r"^[^\x00]*$")] | None]


class ABVRulesInput(JsonInput):
    rules: list[StoredJson]
