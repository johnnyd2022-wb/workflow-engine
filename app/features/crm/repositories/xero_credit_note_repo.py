"""Tenant-scoped Xero credit note upserts and return-decision queries."""

import uuid
from datetime import date
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.utils.time import utc_now
from app.features.crm.models.product_mapping import ProductMapping
from app.features.crm.models.xero_credit_note import XeroCreditNote
from app.features.crm.models.xero_credit_note_line import XeroCreditNoteLine


class XeroCreditNoteRepository:
    def __init__(self, db: Session):
        self.db = db

    def upsert(
        self,
        org_id: UUID,
        xero_tenant_id: str,
        xero_credit_note_id: str,
        **fields,
    ) -> XeroCreditNote:
        note = (
            self.db.query(XeroCreditNote)
            .filter(
                XeroCreditNote.org_id == org_id,
                XeroCreditNote.xero_credit_note_id == xero_credit_note_id,
            )
            .first()
        )
        if note is None:
            note = XeroCreditNote(
                id=uuid.uuid4(),
                org_id=org_id,
                xero_credit_note_id=xero_credit_note_id,
                xero_tenant_id=xero_tenant_id,
                **fields,
            )
            self.db.add(note)
        else:
            note.xero_tenant_id = xero_tenant_id
            for key, value in fields.items():
                setattr(note, key, value)
            note.last_synced_at = utc_now()
            note.updated_at = utc_now()
        return note

    def upsert_lines(self, org_id: UUID, credit_note_id: UUID, line_values: list[dict]) -> None:
        existing = (
            self.db.query(XeroCreditNoteLine)
            .filter(XeroCreditNoteLine.org_id == org_id, XeroCreditNoteLine.credit_note_id == credit_note_id)
            .all()
        )
        by_key = {line.line_key: line for line in existing}
        seen: set[str] = set()
        for values in line_values:
            key = str(values["line_key"])
            seen.add(key)
            line = by_key.get(key)
            if line is None:
                line = XeroCreditNoteLine(
                    org_id=org_id,
                    credit_note_id=credit_note_id,
                    line_key=key,
                    **{k: v for k, v in values.items() if k != "line_key"},
                )
                self.db.add(line)
            else:
                for field, value in values.items():
                    if field != "line_key":
                        setattr(line, field, value)
                line.is_current = True
                line.updated_at = utc_now()
        # Keep a removed line and any user's no-return decision as durable history.
        for line in existing:
            if line.line_key not in seen:
                line.is_current = False
                line.updated_at = utc_now()

    def mark_missing_as_deleted(self, org_id: UUID, xero_tenant_id: str, seen_ids: set[str]) -> int:
        query = self.db.query(XeroCreditNote).filter(
            XeroCreditNote.org_id == org_id,
            XeroCreditNote.xero_tenant_id == xero_tenant_id,
            XeroCreditNote.status.in_(["DRAFT", "SUBMITTED", "AUTHORISED", "PAID"]),
        )
        if seen_ids:
            query = query.filter(~XeroCreditNote.xero_credit_note_id.in_(list(seen_ids)))
        now = utc_now()
        return int(
            query.update(
                {
                    XeroCreditNote.status: "DELETED",
                    XeroCreditNote.last_synced_at: now,
                    XeroCreditNote.updated_at: now,
                },
                synchronize_session=False,
            )
            or 0
        )

    def pending_returns(self, org_id: UUID, *, page: int = 1, page_size: int = 25) -> tuple[list[tuple], int]:
        from app.features.crm.models.sales_return import SalesReturn

        returned = (
            select(func.sum(SalesReturn.quantity))
            .where(SalesReturn.org_id == org_id, SalesReturn.credit_note_line_id == XeroCreditNoteLine.id)
            .correlate(XeroCreditNoteLine)
            .scalar_subquery()
        )
        query = (
            self.db.query(XeroCreditNoteLine, XeroCreditNote, ProductMapping)
            .join(
                XeroCreditNote,
                (XeroCreditNote.org_id == XeroCreditNoteLine.org_id)
                & (XeroCreditNote.id == XeroCreditNoteLine.credit_note_id),
            )
            .join(
                ProductMapping,
                (ProductMapping.org_id == XeroCreditNoteLine.org_id)
                & (ProductMapping.id == XeroCreditNoteLine.product_mapping_id),
            )
            .filter(
                XeroCreditNoteLine.org_id == org_id,
                XeroCreditNoteLine.is_current.is_(True),
                XeroCreditNoteLine.product_mapping_id.isnot(None),
                XeroCreditNoteLine.no_return_at.is_(None),
                XeroCreditNote.status.in_(["AUTHORISED", "PAID"]),
                # GL-P01b: a line stays pending until what came back covers what was credited.
                func.coalesce(returned, 0) < func.coalesce(func.abs(XeroCreditNoteLine.quantity), 1),
            )
        )
        total = query.with_entities(func.count(XeroCreditNoteLine.id)).scalar() or 0
        rows = (
            query.order_by(
                XeroCreditNote.date.asc().nulls_last(), XeroCreditNote.number.asc(), XeroCreditNoteLine.line_key
            )
            .offset((page - 1) * page_size)
            .limit(page_size)
            .all()
        )
        return rows, int(total)

    def credit_total_for_period(self, org_id: UUID, start: date, end: date):
        return (
            self.db.query(func.coalesce(func.sum(XeroCreditNote.total), 0))
            .filter(
                XeroCreditNote.org_id == org_id,
                XeroCreditNote.status.in_(["AUTHORISED", "PAID"]),
                XeroCreditNote.date >= start,
                XeroCreditNote.date < end,
            )
            .scalar()
        )
