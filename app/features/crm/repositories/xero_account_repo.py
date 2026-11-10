"""Tenant-scoped upserts and reads of the cached Xero chart of accounts."""

from uuid import UUID

from sqlalchemy.orm import Session

from app.core.utils.time import utc_now
from app.features.crm.models.xero_account import XeroAccount

FIELDS = ("code", "name", "type", "account_class", "status", "default_treatment")


class XeroAccountRepository:
    def __init__(self, db: Session):
        self.db = db

    def list_for_org(self, org_id: UUID) -> list[XeroAccount]:
        return self.db.query(XeroAccount).filter(XeroAccount.org_id == org_id).order_by(XeroAccount.code).all()

    def upsert_chart(self, org_id: UUID, accounts: list[dict]) -> set[str]:
        """Store ``accounts`` (dicts with ``xero_account_id`` and ``FIELDS``) for the org.

        Returns the codes of accounts that already existed and whose default treatment changed,
        so the caller can reclassify the lines coded to them.
        """
        existing = {a.xero_account_id: a for a in self.list_for_org(org_id)}
        changed: set[str] = set()
        now = utc_now()
        for values in accounts:
            row = existing.get(values["xero_account_id"])
            if row is None:
                row = XeroAccount(org_id=org_id, **values)
                row.last_synced_at = now
                self.db.add(row)
                existing[row.xero_account_id] = row
                continue
            if row.default_treatment != values["default_treatment"] and values["code"]:
                changed.add(values["code"])
            for field in FIELDS:
                setattr(row, field, values[field])
            row.last_synced_at = now
            row.updated_at = now
        self.db.flush()
        return changed
