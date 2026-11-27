"""Operational Case command shapes. The service owns permissions and state transitions."""

from typing import Annotated

from pydantic import Field

from app.utils.request_validation import JsonInput

MAX_VERSION = 2**31 - 1

Identifier = Annotated[str, Field(max_length=38)]
CaseText = Annotated[str, Field(max_length=2000, pattern=r"^[^\x00]*$")]
StatusText = Annotated[str, Field(max_length=24, pattern=r"^[^\x00]*$")]


class CaseAssignmentInput(JsonInput):
    owner_id: Identifier | None = None
    due_at: str | None = Field(default=None, max_length=64)
    next_action: CaseText | None = None


class CreateCaseInput(CaseAssignmentInput):
    source_entity_id: Identifier | None = None
    previous_case_id: Identifier | None = None
    recurrence_reason: CaseText | None = None


class VersionedCaseInput(JsonInput):
    expected_version: int = Field(ge=1, le=MAX_VERSION)


class PatchCaseInput(VersionedCaseInput, CaseAssignmentInput):
    pass


class EvidenceRefInput(JsonInput):
    entity_type: StatusText
    entity_id: Identifier


class CaseTransitionInput(VersionedCaseInput):
    target_status: StatusText | None = None
    status: StatusText | None = None
    cause: StatusText | None = None
    cause_detail: CaseText | None = None
    action_taken: CaseText | None = None
    outcome: CaseText | None = None
    evidence_refs: list[EvidenceRefInput] | None = Field(default=None, max_length=10)
    verification_note: CaseText | None = None
    reason: CaseText | None = None
    reopen_reason: CaseText | None = None


class SourceStatusInput(JsonInput):
    source_entity_ids: list[Identifier] = Field(min_length=1, max_length=100)
