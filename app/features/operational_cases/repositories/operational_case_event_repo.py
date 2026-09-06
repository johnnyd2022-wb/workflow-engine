from __future__ import annotations

import json
from uuid import UUID

from sqlalchemy.orm import Session

from app.features.operational_cases.models.operational_case_event import OperationalCaseEvent


class OperationalCaseEventRepository:
    def __init__(self, db: Session):
        self.db = db

    def add(
        self,
        org_id: UUID,
        case_id: UUID,
        case_version: int,
        event_type: str,
        actor_id: UUID | None,
        actor_label: str | None,
        payload: dict,
        entity_event_id: UUID | None,
    ) -> OperationalCaseEvent:
        """One row per accepted command. The unique (org_id, case_id, case_version)
        constraint is the DB-level guard against a double-write for the same version --
        a flush-time IntegrityError here means a concurrent writer won the version, and
        the caller should treat that as a 409, never retry-overwrite."""
        if len(json.dumps(payload, ensure_ascii=False).encode("utf-8")) > 8 * 1024:
            from app.features.operational_cases.services.operational_case_service import CaseError

            raise CaseError(400, "event_too_large", "case event exceeds 8 KiB")
        event = OperationalCaseEvent(
            org_id=org_id,
            case_id=case_id,
            case_version=case_version,
            event_type=event_type,
            actor_id=actor_id,
            actor_label=actor_label,
            payload=payload,
            entity_event_id=entity_event_id,
        )
        self.db.add(event)
        self.db.flush()
        return event

    def list_for_case(
        self,
        org_id: UUID,
        case_id: UUID,
        before_version: int | None = None,
        limit: int = 25,
    ) -> tuple[list[OperationalCaseEvent], bool]:
        """Cursor by case_version descending -- newest first, paged backwards."""
        query = self.db.query(OperationalCaseEvent).filter(
            OperationalCaseEvent.org_id == org_id, OperationalCaseEvent.case_id == case_id
        )
        if before_version is not None:
            query = query.filter(OperationalCaseEvent.case_version < before_version)
        rows = query.order_by(OperationalCaseEvent.case_version.desc()).limit(limit + 1).all()
        has_more = len(rows) > limit
        return rows[:limit], has_more
