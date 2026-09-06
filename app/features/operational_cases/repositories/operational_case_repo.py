"""Data access for operational_cases. Every method takes org_id explicitly and filters
inline (.agents/conventions.md §2) -- no shared scoped-query helper.
"""

from __future__ import annotations

import base64
import json
from datetime import datetime
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy import and_, or_
from sqlalchemy.orm import Session, joinedload

from app.features.operational_cases.models.operational_case import CaseStatus, OperationalCase

_SOURCE_TUPLE_COLUMNS = ("source_type", "check_id", "source_entity_type", "source_entity_id")


class OperationalCaseRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_by_id(self, case_id: UUID, org_id: UUID) -> OperationalCase | None:
        return (
            self.db.query(OperationalCase)
            .options(joinedload(OperationalCase.owner))
            .filter(OperationalCase.id == case_id, OperationalCase.org_id == org_id)
            .first()
        )

    def get_by_id_for_update(self, case_id: UUID, org_id: UUID) -> OperationalCase | None:
        return (
            self.db.query(OperationalCase)
            .filter(OperationalCase.id == case_id, OperationalCase.org_id == org_id)
            .populate_existing()
            .with_for_update()
            .one_or_none()
        )

    def get_active_by_source_for_update(
        self,
        org_id: UUID,
        source_type: str,
        check_id: str,
        source_entity_type: str,
        source_entity_id: UUID,
    ) -> OperationalCase | None:
        """Row-locked lookup of the active case (if any) for a source identity tuple.

        Caller must already hold the per-source advisory lock (see
        operational_case_service._source_advisory_lock) before calling this -- the FOR
        UPDATE here only prevents a concurrent transaction from reading a torn write of
        the same row, it does not itself serialize *creation* of a first row for a source
        that has none yet (that's what the advisory lock + the partial unique index are
        for).
        """
        return (
            self.db.query(OperationalCase)
            .filter(
                OperationalCase.org_id == org_id,
                OperationalCase.source_type == source_type,
                OperationalCase.check_id == check_id,
                OperationalCase.source_entity_type == source_entity_type,
                OperationalCase.source_entity_id == source_entity_id,
                OperationalCase.status.in_(CaseStatus.ACTIVE),
            )
            .populate_existing()
            .with_for_update()
            .one_or_none()
        )

    def get_latest_terminal_by_source(
        self,
        org_id: UUID,
        source_type: str,
        check_id: str,
        source_entity_type: str,
        source_entity_id: UUID,
    ) -> OperationalCase | None:
        """Most recent terminal (verified/dismissed) case for a source identity, used to
        validate a recurrence command's ``previous_case_id``."""
        return (
            self.db.query(OperationalCase)
            .filter(
                OperationalCase.org_id == org_id,
                OperationalCase.source_type == source_type,
                OperationalCase.check_id == check_id,
                OperationalCase.source_entity_type == source_entity_type,
                OperationalCase.source_entity_id == source_entity_id,
                OperationalCase.status.in_(CaseStatus.TERMINAL),
            )
            .order_by(OperationalCase.updated_at.desc(), OperationalCase.id.desc())
            .first()
        )

    def create(self, case: OperationalCase) -> OperationalCase:
        self.db.add(case)
        self.db.flush()
        return case

    def create_case(
        self,
        org_id: UUID,
        title: str,
        source_entity_id: UUID,
        source_snapshot: dict,
        owner_id: UUID,
        due_at: datetime,
        next_action: str,
        created_by: UUID,
        severity: str = "critical",
        source_type: str = "core_finding",
        check_id: str = "untracked_items",
        source_entity_type: str = "inventory_item",
        status: str = CaseStatus.OPEN,
        version: int = 1,
        previous_case_id: UUID | None = None,
    ) -> OperationalCase:
        """Direct row creation for test/seed use (bypasses the service's eligibility
        pipeline on purpose -- that pipeline is business logic under test, not fixture
        setup; see tests/factories.py's OperationalCaseFactory)."""
        case = OperationalCase(
            org_id=org_id,
            title=title,
            severity=severity,
            source_type=source_type,
            check_id=check_id,
            source_entity_type=source_entity_type,
            source_entity_id=source_entity_id,
            source_snapshot=source_snapshot,
            status=status,
            owner_id=owner_id,
            due_at=due_at,
            next_action=next_action,
            version=version,
            previous_case_id=previous_case_id,
            created_by=created_by,
        )
        self.db.add(case)
        self.db.commit()
        return case

    def list_for_org(
        self,
        org_id: UUID,
        *,
        owner: str | None = None,
        severity: str | None = None,
        statuses: tuple[str, ...] | None = None,
        source_entity_id: UUID | None = None,
        overdue_only: bool = False,
        now: datetime | None = None,
        cursor: tuple[datetime, UUID] | None = None,
        limit: int = 25,
    ) -> tuple[list[OperationalCase], bool]:
        """Deterministic queue order: updated_at DESC, id DESC. Returns (rows, has_more)."""
        query = self.db.query(OperationalCase).filter(OperationalCase.org_id == org_id)

        if statuses:
            query = query.filter(OperationalCase.status.in_(statuses))
        else:
            query = query.filter(OperationalCase.status.in_(CaseStatus.ACTIVE))

        if severity:
            query = query.filter(OperationalCase.severity == severity)

        if source_entity_id is not None:
            query = query.filter(OperationalCase.source_entity_id == source_entity_id)

        if owner == "needs_owner":
            # Owner inactive counts as needing an owner too (spec: "needs-owner includes
            # inactive owner"). Joining Users here would need an explicit org filter on
            # the join target too; simplest correct form is an EXISTS-free correlated
            # filter via a subquery scoped to the same org.
            from app.core.db.models.user import User

            inactive_owner_ids = self.db.query(User.id).filter(User.org_id == org_id, User.is_active.is_(False))
            query = query.filter(
                sa.or_(OperationalCase.owner_id.is_(None), OperationalCase.owner_id.in_(inactive_owner_ids))
            )
        elif owner == "me":
            raise ValueError("owner='me' must be resolved to a concrete user id by the caller")
        elif owner:
            query = query.filter(OperationalCase.owner_id == UUID(str(owner)))

        if overdue_only:
            now = now or datetime.now(tz=None)
            query = query.filter(
                OperationalCase.due_at < now,
                OperationalCase.status.in_(CaseStatus.ACTIVE),
            )

        if cursor is not None:
            cursor_updated_at, cursor_id = cursor
            query = query.filter(
                or_(
                    OperationalCase.updated_at < cursor_updated_at,
                    and_(OperationalCase.updated_at == cursor_updated_at, OperationalCase.id < cursor_id),
                )
            )

        rows = (
            query.options(joinedload(OperationalCase.owner))
            .order_by(OperationalCase.updated_at.desc(), OperationalCase.id.desc())
            .limit(limit + 1)
            .all()
        )
        has_more = len(rows) > limit
        return rows[:limit], has_more

    def count_aggregates(self, org_id: UUID, now: datetime) -> dict[str, int]:
        """One query for every Dashboard aggregate (spec budget: <=1 aggregate query)."""
        from sqlalchemy import case as sa_case
        from sqlalchemy import func

        from app.core.db.models.user import User

        row = (
            self.db.query(
                func.count().label("active_count"),
                func.sum(sa_case((OperationalCase.severity == "critical", 1), else_=0)).label("critical_count"),
                func.sum(
                    sa_case(
                        (and_(OperationalCase.due_at < now, OperationalCase.status.in_(CaseStatus.ACTIVE)), 1),
                        else_=0,
                    )
                ).label("overdue_count"),
                func.sum(sa_case((OperationalCase.status == CaseStatus.RESOLVED, 1), else_=0)).label(
                    "awaiting_verification_count"
                ),
                # needs-owner includes an inactive owner (spec) -- a NULL from the outer
                # join (owner row missing/tombstoned) also counts as needing an owner.
                func.sum(sa_case((sa.or_(User.is_active.is_(False), User.id.is_(None)), 1), else_=0)).label(
                    "needs_owner_count"
                ),
            )
            .outerjoin(User, and_(User.id == OperationalCase.owner_id, User.org_id == org_id))
            .filter(OperationalCase.org_id == org_id, OperationalCase.status.in_(CaseStatus.ACTIVE))
            .one()
        )
        return {
            "active_count": int(row.active_count or 0),
            "critical_count": int(row.critical_count or 0),
            "overdue_count": int(row.overdue_count or 0),
            "awaiting_verification_count": int(row.awaiting_verification_count or 0),
            "needs_owner_count": int(row.needs_owner_count or 0),
        }

    def source_status_batch(self, org_id: UUID, source_entity_ids: list[UUID]) -> dict[UUID, OperationalCase]:
        """Latest relevant case (active, else latest terminal) per source_entity_id, for
        the Notifications batch endpoint. One query, in-Python reduction (bounded to
        <=100 ids per the API contract, so this never needs a window function)."""
        if not source_entity_ids:
            return {}
        rows = (
            self.db.query(OperationalCase)
            .filter(
                OperationalCase.org_id == org_id,
                OperationalCase.source_type == "core_finding",
                OperationalCase.check_id == "untracked_items",
                OperationalCase.source_entity_id.in_(source_entity_ids),
            )
            .distinct(OperationalCase.source_entity_id)
            .order_by(
                OperationalCase.source_entity_id,
                OperationalCase.status.in_(CaseStatus.ACTIVE).desc(),
                OperationalCase.updated_at.desc(),
                OperationalCase.id.desc(),
            )
            .limit(100)
            .all()
        )
        return {row.source_entity_id: row for row in rows}


def encode_cursor(org_id: UUID, filters_signature: str, updated_at: datetime, case_id: UUID) -> str:
    """Opaque, org/filter-bound cursor (spec: "opaque org/filter-bound cursor"). Binding
    org_id and a signature of the active filters means a cursor minted under one filter
    set (or org) is simply rejected, not silently reinterpreted, if replayed elsewhere.
    """
    raw = json.dumps(
        {"o": str(org_id), "f": filters_signature, "u": updated_at.isoformat(), "i": str(case_id)}
    ).encode()
    return base64.urlsafe_b64encode(raw).decode()


def decode_cursor(token: str, org_id: UUID, filters_signature: str) -> tuple[datetime, UUID] | None:
    """Returns None for a missing, malformed, foreign-org or filter-mismatched cursor --
    callers should treat that as "reset to page one", not an error."""
    try:
        raw = base64.urlsafe_b64decode(token.encode())
        data = json.loads(raw)
        if data.get("o") != str(org_id) or data.get("f") != filters_signature:
            return None
        return datetime.fromisoformat(data["u"]), UUID(data["i"])
    except Exception:
        return None


def filters_signature(**filters) -> str:
    """Stable signature of the active filter set, for cursor binding."""
    return json.dumps(filters, sort_keys=True, default=str)
