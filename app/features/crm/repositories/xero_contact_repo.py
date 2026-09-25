"""Repository for XeroContact records."""

from uuid import UUID

from sqlalchemy import case, func, or_
from sqlalchemy.orm import Session

from app.core.utils.time import utc_now
from app.features.crm.models.xero_contact import XeroContact


class XeroContactRepository:
    def __init__(self, db: Session):
        self.db = db

    def upsert(
        self,
        org_id: UUID,
        xero_contact_id: str,
        xero_tenant_id: str,
        name: str,
        **fields,
    ) -> XeroContact:
        contact = (
            self.db.query(XeroContact)
            .filter(
                XeroContact.org_id == org_id,
                XeroContact.xero_contact_id == xero_contact_id,
            )
            .first()
        )

        if contact:
            contact.xero_tenant_id = xero_tenant_id
            contact.name = name
            for k, v in fields.items():
                setattr(contact, k, v)
            contact.last_synced_at = utc_now()
            contact.updated_at = utc_now()
        else:
            contact = XeroContact(
                org_id=org_id,
                xero_contact_id=xero_contact_id,
                xero_tenant_id=xero_tenant_id,
                name=name,
                last_synced_at=utc_now(),
                **fields,
            )
            self.db.add(contact)

        return contact

    def get_by_id(self, contact_id: UUID, org_id: UUID) -> XeroContact | None:
        return (
            self.db.query(XeroContact)
            .filter(
                XeroContact.id == contact_id,
                XeroContact.org_id == org_id,
            )
            .first()
        )

    def get_by_xero_id(self, xero_contact_id: str, org_id: UUID) -> XeroContact | None:
        return (
            self.db.query(XeroContact)
            .filter(
                XeroContact.xero_contact_id == xero_contact_id,
                XeroContact.org_id == org_id,
            )
            .first()
        )

    def list_paginated(
        self,
        org_id: UUID,
        search: str | None = None,
        status: str | None = None,
        sort_by: str = "name",
        sort_dir: str = "asc",
        page: int = 1,
        page_size: int = 50,
        missing_contact: bool = False,
    ) -> tuple[list[XeroContact], int]:
        q = self.db.query(XeroContact).filter(XeroContact.org_id == org_id)

        if search:
            term = f"%{search}%"
            q = q.filter(
                or_(
                    func.lower(XeroContact.name).contains(search.lower()),
                    func.lower(XeroContact.email_address).contains(search.lower()),
                )
            )
            _ = term  # noqa: F841

        if status:
            q = q.filter(XeroContact.contact_status == status.upper())

        if missing_contact:
            has_email = func.nullif(func.trim(XeroContact.email_address), "").isnot(None)
            has_phone = func.nullif(func.trim(XeroContact.phone_number), "").isnot(None)
            q = q.filter(~has_email | ~has_phone)

        sort_col = {
            "name": XeroContact.name,
            "email": XeroContact.email_address,
            "updated": XeroContact.updated_at,
            "synced": XeroContact.last_synced_at,
        }.get(sort_by, XeroContact.name)

        q = q.order_by(sort_col.desc() if sort_dir == "desc" else sort_col.asc())

        total = q.count()
        contacts = q.offset((page - 1) * page_size).limit(page_size).all()
        return contacts, total

    def count_for_org(self, org_id: UUID) -> int:
        return self.db.query(XeroContact).filter(XeroContact.org_id == org_id).count()

    def contact_completeness_for_org(self, org_id: UUID) -> dict[str, int]:
        has_email = func.nullif(func.trim(XeroContact.email_address), "").isnot(None)
        has_phone = func.nullif(func.trim(XeroContact.phone_number), "").isnot(None)
        total, with_email, with_phone, with_both = (
            self.db.query(
                func.count(XeroContact.id),
                func.count(case((has_email, 1))),
                func.count(case((has_phone, 1))),
                func.count(case((has_email & has_phone, 1))),
            )
            .filter(XeroContact.org_id == org_id)
            .one()
        )
        return {
            "total": total,
            "with_email": with_email,
            "with_phone": with_phone,
            "with_both": with_both,
            "missing_any": total - with_both,
        }
