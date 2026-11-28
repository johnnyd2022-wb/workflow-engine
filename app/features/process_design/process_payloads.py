"""Request schemas for the process-design API."""

from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from pydantic import AfterValidator, AliasChoices, ConfigDict, Field, JsonValue, StringConstraints

from app.core.db.models.process import ProcessCategory
from app.utils.request_validation import CleanName, JsonInput

Name = Annotated[CleanName, StringConstraints(max_length=255)]
Description = Annotated[str, StringConstraints(max_length=1000, pattern=r"^[^\x00]*$")]


def _grid_position(value: Decimal) -> Decimal:
    if value % 1000:
        raise ValueError("Expected a multiple of 1000.")
    return value


POSITION_LIMIT = Decimal("1e30")
Position = Annotated[Decimal, Field(gt=0, lt=POSITION_LIMIT), AfterValidator(_grid_position)]
StepNumber = Annotated[int, Field(ge=1, le=2**31 - 1)]
StepTiming = Annotated[int, Field(ge=0, le=525_600)]
JsonEntries = Annotated[list[dict[str, JsonValue]], Field(max_length=1000)]


class UpdateProcessInput(JsonInput):
    name: Name | None = None
    description: Description | None = None
    category: ProcessCategory | Literal[""] | None = None
    is_draft: bool | None = None
    settings: dict[str, JsonValue] | None = None


class CreateProcessInput(UpdateProcessInput):
    name: Name
    is_draft: bool = False


class ExtendedInput(JsonInput):
    # These objects carry workflow-specific metadata. Validate the fields read by
    # this endpoint while preserving metadata consumed elsewhere in the app.
    model_config = ConfigDict(extra="allow")


class DateOption(ExtendedInput):
    enabled: bool = False
    mode: Literal["none", "fixed_duration", "set_at_execution"] | None = None
    duration_value: Annotated[int, Field(ge=0, le=10_000)] | None = None
    duration_unit: Literal["days", "weeks", "months", "years", "hours"] | None = None


class OutputMetadata(ExtendedInput):
    custom_expiry: DateOption | None = None
    ready_date: DateOption | None = None


class StepOutput(ExtendedInput):
    name: Name | None = None
    extra_data: OutputMetadata | None = None


class UpdateStepInput(JsonInput):
    step_number: StepNumber | None = None
    name: Name | None = None
    position: Position | None = None
    description: Description | None = None
    inputs: JsonEntries | None = None
    outputs: Annotated[list[StepOutput], Field(max_length=1000)] | None = None
    execution_prompts: JsonEntries | None = None
    duration_minutes: StepTiming | None = None
    wait_minutes: StepTiming | None = None


class CreateStepInput(UpdateStepInput):
    step_number: StepNumber
    name: Name


class StepOrderInput(JsonInput):
    id: UUID = Field(validation_alias=AliasChoices("id", "step_id"))
    position: Position


class ReorderStepsInput(JsonInput):
    orders: Annotated[list[StepOrderInput], Field(min_length=1, max_length=1000)] = Field(
        validation_alias=AliasChoices("orders", "steps")
    )
