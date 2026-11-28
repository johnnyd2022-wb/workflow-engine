"""Validation at the Sales request boundary."""

from datetime import date
from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from pydantic import ConfigDict, Field, JsonValue, StringConstraints

from app.utils.request_validation import CleanName, JsonInput

NoteText = Annotated[str, StringConstraints(strip_whitespace=True, max_length=20_000, pattern=r"^[^\x00]*$")]
MappingText = Annotated[CleanName, StringConstraints(max_length=500)]
ExternalId = Annotated[CleanName, StringConstraints(max_length=255)]
OptionalId = UUID | Literal["", "null", "none"] | None
TaskType = Literal["general", "call", "email"]


class ServicePayload(JsonInput):
    """JSON object for services that already validate their domain fields."""

    model_config = ConfigDict(extra="allow")
    __pydantic_extra__: dict[str, JsonValue] = Field(init=False)


class ContactImportInput(JsonInput):
    text: Annotated[str, StringConstraints(min_length=1, max_length=1_000_000, pattern=r"^[^\x00]*$")]
    format: Annotated[CleanName, StringConstraints(max_length=16)] = "csv"
    commit: bool = False


class ContactSyncInput(JsonInput):
    sync_to_xero: bool | None


class ContactSyncSettingsInput(JsonInput):
    sync_contacts_to_xero: bool


class NoteInput(JsonInput):
    content: Annotated[NoteText, StringConstraints(min_length=1)]


class UpdateTaskInput(JsonInput):
    title: MappingText | None = None
    description: NoteText | None = None
    task_type: TaskType = "general"
    status: Literal["pending", "in_progress", "completed", "cancelled"] = "pending"
    priority: Literal["low", "medium", "high"] = "medium"
    contact_id: OptionalId = None
    assigned_to_user_id: OptionalId = None
    due_date: date | None = None


class CreateTaskInput(UpdateTaskInput):
    task_type: TaskType | Literal["tasting"] = "general"
    tasting: dict[str, JsonValue] | None = None


class UpdateMappingInput(JsonInput):
    biz_e_product_name: MappingText | None = None
    xero_description_pattern: MappingText | None = None
    biz_e_source_output_id: OptionalId = None
    match_type: Literal["exact", "contains", "alias"] = "exact"
    notes: NoteText | None = None
    units_per_line: Annotated[Decimal, Field(gt=0)] = Decimal(1)
    is_active: bool = True


class CreateMappingInput(UpdateMappingInput):
    biz_e_product_name: MappingText
    xero_description_pattern: MappingText


class BulkMappingsInput(JsonInput):
    mappings: Annotated[list[CreateMappingInput], Field(min_length=1, max_length=50)]


class LineRefInput(JsonInput):
    invoice_id: ExternalId
    line_key: ExternalId


class AssignMatchingLineInput(LineRefInput):
    picks: Annotated[list[dict[str, JsonValue]], Field(max_length=500)] = Field(default_factory=list)
    site_id: OptionalId = None


class TraceabilitySettingsInput(JsonInput):
    matching_strategy: Literal["fifo", "manual", "hybrid"] = "fifo"
    matching_key: Literal["batch_id"] = "batch_id"
    manual_review_days: Annotated[int, Field(ge=1, le=90)] = 7
    task_done_archive_days: Annotated[int, Field(ge=1, le=90)] = 7
    strict_mapping: bool = True
    obfuscate_sales_figures: bool = False
    revenue_baseline_target_mtd: (
        Annotated[Decimal, Field(ge=0, max_digits=12, decimal_places=2)] | Literal[""] | None
    ) = None


class NoReturnNoteInput(JsonInput):
    note: Annotated[NoteText, StringConstraints(min_length=1, max_length=500)]


class ReorderLanesInput(JsonInput):
    lane_ids: Annotated[list[UUID], Field(max_length=100)]


class AssignLaneInput(JsonInput):
    lane_id: OptionalId
