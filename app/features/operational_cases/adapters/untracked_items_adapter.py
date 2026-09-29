"""Source adapter: canonical ``untracked_items`` check, scoped to one selected inventory
item, reused (not reinvoked as the full DAG check suite) for operational_cases commands.

See .agents/specs/operational_cases.md "Lifecycle and source policy" for the state
contract (active/cleared/unknown/deleted) and the source snapshot schema v1.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session, joinedload

from app.core.db.models.execution import Execution
from app.core.db.models.execution_step import ExecutionStep
from app.core.db.models.step import Step
from app.core.db.repositories.inventory_repo import InventoryRepository
from app.core.db.repositories.process_repo import ProcessRepository
from app.core.utils.inventory_quantity import parse_stored_quantity_to_decimal
from app.features.compliance_checks.checks.untracked_items import find_producing_step, needs_reconciliation
from app.observability import get_logger

logger = get_logger(__name__)

CHECK_ID = "untracked_items"
SOURCE_ENTITY_TYPE = "inventory_item"
ADAPTER_VERSION = "untracked_items_v1"
SNAPSHOT_SCHEMA_VERSION = 1
CRITICAL_REASON = "positive_untracked_stock"

STATE_ACTIVE = "active"
STATE_CLEARED = "cleared"
STATE_UNKNOWN = "unknown"
STATE_DELETED = "deleted"

_MAX_SNAPSHOT_BYTES = 16 * 1024
_MAX_ITEM_NAME_CHARS = 200
_MAX_UNIT_CHARS = 64
_MAX_DECIMAL_STR_CHARS = 64


class InvalidSourceDataError(ValueError):
    """Required source fields are missing/invalid; creation must reject with 400."""


@dataclass
class SourceObservation:
    state: str  # active | cleared | unknown | deleted
    observed_at: datetime
    eligible_for_creation: bool
    snapshot: dict[str, Any] | None
    item: Any = None


def _is_untracked(item) -> bool:
    return bool((item.extra_data or {}).get("untracked") is True)


def _decimal_str(value: Decimal) -> str:
    """Canonical Decimal string: fixed-point, trailing zeros/point trimmed (matches
    app.core.utils.inventory_quantity.quantity_to_api_str's convention, e.g. "5.0000"
    from a NUMERIC(18,4) column becomes "5") so the same on-hand value always snapshots
    to the same string regardless of how many zeros Postgres padded it with."""
    if not value.is_finite():
        raise InvalidSourceDataError("non-finite numeric value")
    s = format(value, "f")
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    if not s or s == "-":
        s = "0"
    if len(s) > _MAX_DECIMAL_STR_CHARS:
        raise InvalidSourceDataError("numeric value exceeds maximum encoded length")
    return s


def _resolve_producing_step_id(session: Session, org_id: UUID, item) -> UUID | None:
    """Best-effort presentation field. Any failure yields None -- never blocks a
    creation/verification command, and never substitutes for a required numeric field."""
    try:
        process_id: UUID | None = None
        if item.source_execution_step_id:
            step = (
                session.query(ExecutionStep)
                .join(Execution, ExecutionStep.execution_id == Execution.id)
                .filter(ExecutionStep.id == item.source_execution_step_id, Execution.org_id == org_id)
                .options(joinedload(ExecutionStep.execution))
                .first()
            )
            if step and step.execution:
                process_id = step.execution.process_id
        if process_id is None and item.source_execution_id:
            execution = (
                session.query(Execution)
                .filter(Execution.id == item.source_execution_id, Execution.org_id == org_id)
                .first()
            )
            if execution:
                process_id = execution.process_id
        if process_id is None:
            return None
        process = ProcessRepository(session).get_process_with_steps(process_id, org_id)
        step_id, _step_name = find_producing_step(process, item.name, item.unit)
        return step_id
    except Exception:
        logger.debug("operational_cases: producing_step_id resolution failed, leaving null", exc_info=True)
        return None


def _build_snapshot(session: Session, org_id: UUID, item, observed_at: datetime) -> dict[str, Any]:
    """Build the A1 source snapshot (schema v1): exactly the allowlisted fields, no raw
    extra_data/notes/prompts. Raises InvalidSourceDataError for missing/invalid required
    fields -- caller turns that into 400 invalid_source_data and creates nothing."""
    quantity = parse_stored_quantity_to_decimal(item.quantity)
    if item.quantity is None:
        raise InvalidSourceDataError("quantity is required")

    unit = (item.unit or "").strip()
    if not unit:
        raise InvalidSourceDataError("unit is required")
    if len(unit) > _MAX_UNIT_CHARS:
        raise InvalidSourceDataError("unit exceeds maximum length")

    item_name = (item.name or "").strip()
    truncated_fields: list[str] = []
    if len(item_name) > _MAX_ITEM_NAME_CHARS:
        item_name = item_name[:_MAX_ITEM_NAME_CHARS]
        truncated_fields.append("item_name")

    extra = item.extra_data or {}
    remaining_raw = extra.get("remaining_balance_to_reconcile")
    remaining_balance: str | None = None
    if remaining_raw is not None:
        try:
            remaining_balance = _decimal_str(Decimal(str(remaining_raw)))
        except Exception as exc:
            raise InvalidSourceDataError("remaining_balance_to_reconcile is not a finite number") from exc

    def validated_reference(value, model):
        if value is None:
            return None
        try:
            uid = UUID(str(value))
        except (ValueError, TypeError, AttributeError) as exc:
            raise InvalidSourceDataError("invalid source reference") from exc
        if session.query(model.id).filter(model.org_id == org_id, model.id == uid).first() is None:
            raise InvalidSourceDataError("source reference is unavailable")
        return str(uid)

    snapshot = {
        "schema_version": SNAPSHOT_SCHEMA_VERSION,
        "check_id": CHECK_ID,
        "source_entity_type": SOURCE_ENTITY_TYPE,
        "source_entity_id": str(item.id),
        "item_name": item_name,
        "unit": unit,
        "quantity": _decimal_str(quantity),
        "remaining_balance_to_reconcile": remaining_balance,
        "source_execution_id": validated_reference(item.source_execution_id, Execution),
        "source_execution_step_id": validated_reference(item.source_execution_step_id, ExecutionStep),
        "producing_step_id": validated_reference(_resolve_producing_step_id(session, org_id, item), Step),
        "observed_at": observed_at.isoformat(),
        "adapter_version": ADAPTER_VERSION,
        "critical_reason": CRITICAL_REASON,
        "truncated_fields": truncated_fields,
    }

    encoded = json.dumps(snapshot, separators=(",", ":")).encode("utf-8")
    if len(encoded) > _MAX_SNAPSHOT_BYTES:
        raise InvalidSourceDataError("source snapshot exceeds 16 KiB")
    return snapshot


def evaluate(session: Session, org_id: UUID, source_entity_id: UUID) -> SourceObservation:
    """Evaluate the canonical check for one specific inventory item under a row lock.

    Callers issuing a creation/verification command must hold the per-source advisory
    lock (see operational_case_service._source_advisory_lock) before calling this --
    the FOR UPDATE row lock here only protects this read from a concurrent write to the
    *same row*, it does not by itself serialize the *command* against a sibling command
    for a source with no row yet.
    """
    observed_at = datetime.now(UTC)
    try:
        item = InventoryRepository(session).get_inventory_item_by_id_for_update(source_entity_id, org_id)
    except Exception:
        logger.warning("operational_cases: untracked_items source evaluation failed", exc_info=True)
        return SourceObservation(
            state=STATE_UNKNOWN, observed_at=observed_at, eligible_for_creation=False, snapshot=None
        )

    if item is None:
        return SourceObservation(
            state=STATE_DELETED, observed_at=observed_at, eligible_for_creation=False, snapshot=None
        )

    if not _is_untracked(item):
        # No longer flagged untracked at all -- the canonical check would not surface it.
        # Cleared, but never eligible for a *new* case (creation eligibility is
        # specifically "appears in the untracked check with positive on-hand quantity").
        snapshot = _build_snapshot(session, org_id, item, observed_at)
        return SourceObservation(
            state=STATE_CLEARED, observed_at=observed_at, eligible_for_creation=False, snapshot=snapshot, item=item
        )

    quantity = parse_stored_quantity_to_decimal(item.quantity)
    snapshot = _build_snapshot(session, org_id, item, observed_at)

    if needs_reconciliation(item):
        return SourceObservation(
            state=STATE_ACTIVE,
            observed_at=observed_at,
            eligible_for_creation=quantity > 0,
            snapshot=snapshot,
            item=item,
        )

    # Absence from the canonical check (no qty, no remaining balance): cleared.
    return SourceObservation(
        state=STATE_CLEARED, observed_at=observed_at, eligible_for_creation=False, snapshot=snapshot, item=item
    )
