"""Inputs for liquor licensing, food registrations and Customs coverage and transfers."""

from datetime import date, datetime, time, timedelta
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BeforeValidator, Field, field_validator

from app.features.compliant.routes.validation_payloads import OptionalDate, _optional_date
from app.utils.request_validation import CleanName, CleanText, JsonInput

Name = Annotated[CleanName, Field(max_length=150)]
EvidenceReference = Annotated[CleanName, Field(max_length=500)]
Reference = Annotated[CleanName, Field(max_length=100)]
ShortText = Annotated[CleanText, Field(max_length=255)]
LongText = Annotated[str, Field(max_length=4000, pattern=r"^[^\x00]*$")]


def _optional_uuid(value):
    if value == "":
        return None
    return UUID(value) if isinstance(value, str) else value


OptionalUUID = Annotated[UUID | None, BeforeValidator(_optional_uuid)]


class CustomsValidityInput(JsonInput):
    valid_from: date
    valid_until: OptionalDate = None
    evidence_reference: EvidenceReference


class CustomsLicenceInput(CustomsValidityInput):
    number: Reference
    name: Name
    kind: Literal["lma", "oss", "duty_free", "export"]
    legal_entity_reference: Reference

    @field_validator("number")
    @classmethod
    def uppercase_number(cls, value):
        number = value.upper()
        if len(number) > 100:
            raise ValueError("Enter a licence number of up to 100 characters.")
        return number


class CustomsCoverageInput(CustomsValidityInput):
    licence_id: UUID
    site_id: UUID
    location_id: OptionalUUID = None


class FoodRegistrationInput(JsonInput):
    reference: Reference
    name: Name
    programme: Literal["np1", "np2", "np3", "fcp"]
    registered_on: date
    registered_as: Literal["new", "existing"]
    valid_until: OptionalDate = None
    evidence_reference: EvidenceReference

    @field_validator("reference")
    @classmethod
    def uppercase_reference(cls, value):
        reference = value.upper()
        if len(reference) > 100:
            raise ValueError("Enter a registration reference of up to 100 characters.")
        return reference


class FoodScopeInput(JsonInput):
    registration_id: UUID
    site_id: UUID
    activity: Literal["manufacturing", "storage", "selling"]
    evidence_reference: EvidenceReference


class CCADestinationInput(JsonInput):
    name: CleanName = Field(max_length=200)
    cca_code: Reference
    address: CleanName = Field(max_length=500)
    kind: Literal["duty_free", "export_warehouse", "manufacturer", "storage", "other"]
    contact_id: OptionalUUID = None


class CCADepartureInput(JsonInput):
    xero_invoice_id: Reference
    destination_id: UUID
    moved_at: datetime
    carrier: CleanName = Field(max_length=200)
    consignment_note: CleanText | None = Field(default=None, max_length=200)
    notes: str | None = Field(default=None, max_length=2000, pattern=r"^[^\x00]*$")


class CCAReceiptInput(JsonInput):
    received_on: date
    receipt_reference: EvidenceReference | None = None


# Date arithmetic calculates notice windows and rolls annual fee dates forward.
_EARLIEST_LICENCE_DATE = date.min + timedelta(days=366)
_LATEST_LICENCE_DATE = date.max - timedelta(days=366)
BoundedLicenceDate = Annotated[date, Field(ge=_EARLIEST_LICENCE_DATE, le=_LATEST_LICENCE_DATE)]
LicenceDate = Annotated[BoundedLicenceDate | None, BeforeValidator(_optional_date)]


class LiquorLicenceInput(JsonInput):
    kind: Literal["on", "off", "club", "special"] = "on"
    endorsements: list[Literal["s40_remote_sales"]] = Field(default_factory=list)
    site_id: OptionalUUID = None
    licence_number: CleanText | None = Field(default=None, max_length=100)
    issuing_dlc: ShortText | None = None
    premises: CleanText | None = Field(default=None, max_length=500)
    sale_hours: ShortText | None = None
    conditions: LongText | None = None
    issued_on: LicenceDate = None
    expires_on: LicenceDate = None
    annual_fee_due_on: LicenceDate = None
    event_starts_on: LicenceDate = None
    event_ends_on: LicenceDate = None
    delivery_hours_start: time | None = None
    delivery_hours_end: time | None = None
    event_name: ShortText | None = None
    manager_on_duty: ShortText | None = None

    @field_validator("delivery_hours_start", "delivery_hours_end", mode="before")
    @classmethod
    def optional_local_time(cls, value):
        if value == "":
            return None
        result = time.fromisoformat(value) if isinstance(value, str) else value
        if isinstance(result, time) and result.tzinfo is not None:
            raise ValueError("Enter a local time.")
        return result


class ManagerCertificateInput(JsonInput):
    user_id: OptionalUUID = None
    holder_name: ShortText | None = None
    certificate_number: CleanText | None = Field(default=None, max_length=100)
    issuing_dlc: ShortText | None = None
    issued_on: LicenceDate = None
    expires_on: LicenceDate = None


class RenewalLodgedInput(JsonInput):
    lodged_on: LicenceDate = None


class RenewalGrantedInput(JsonInput):
    expires_on: BoundedLicenceDate


class LicensingLogInput(JsonInput):
    kind: Literal["id_refusal", "intoxication_refusal", "incident", "controlled_purchase"]
    occurred_at: datetime | None = None
    description: LongText
    action_taken: LongText | None = None
    location: ShortText | None = None
    staff_name: ShortText | None = None
    reference: ShortText | None = None
