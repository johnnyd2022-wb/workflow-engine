"""CRMService — high-level CRM queries, notes, tasks, and product mapping."""

from uuid import UUID

from sqlalchemy.orm import Session

from app.features.crm.repositories.crm_task_repo import CRMNoteRepository, CRMTaskRepository
from app.features.crm.repositories.product_mapping_repo import ProductMappingRepository
from app.features.crm.repositories.xero_contact_repo import XeroContactRepository
from app.features.crm.repositories.xero_invoice_repo import XeroInvoiceRepository
from app.features.crm.repositories.xero_sync_job_repo import XeroSyncJobRepository
from app.features.crm.repositories.xero_tenant_repo import XeroTenantRepository
from app.features.crm.repositories.xero_token_repo import XeroTokenRepository


class CRMService:
    def __init__(self, db: Session):
        self.db = db
        self.contact_repo = XeroContactRepository(db)
        self.invoice_repo = XeroInvoiceRepository(db)
        self.note_repo = CRMNoteRepository(db)
        self.task_repo = CRMTaskRepository(db)
        self.mapping_repo = ProductMappingRepository(db)
        self.tenant_repo = XeroTenantRepository(db)
        self.token_repo = XeroTokenRepository(db)
        self.sync_job_repo = XeroSyncJobRepository(db)

    # ------------------------------------------------------------------
    # Connection status
    # ------------------------------------------------------------------

    def get_xero_status(self, org_id: UUID) -> dict:
        tenant = self.tenant_repo.get_connected(org_id)
        token = self.token_repo.get(org_id)
        latest_job = self.sync_job_repo.get_latest(org_id)

        if not tenant or not token:
            return {"connected": False}

        return {
            "connected": True,
            "tenant_name": tenant.xero_tenant_name,
            "tenant_id": tenant.xero_tenant_id,
            "last_successful_sync_at": tenant.last_successful_sync_at.isoformat()
            if tenant.last_successful_sync_at
            else None,
            "connected_at": tenant.connected_at.isoformat() if tenant.connected_at else None,
            "contacts_count": self.contact_repo.count_for_org(org_id),
            "invoices_count": self.invoice_repo.count_for_org(org_id),
            "latest_sync": _serialise_sync_job(latest_job) if latest_job else None,
        }

    # ------------------------------------------------------------------
    # Contacts
    # ------------------------------------------------------------------

    def list_customers(
        self,
        org_id: UUID,
        search: str | None = None,
        status: str | None = None,
        sort_by: str = "name",
        sort_dir: str = "asc",
        page: int = 1,
        page_size: int = 50,
    ) -> dict:
        contacts, total = self.contact_repo.list_paginated(
            org_id=org_id,
            search=search,
            status=status,
            sort_by=sort_by,
            sort_dir=sort_dir,
            page=page,
            page_size=page_size,
        )
        return {
            "customers": [_serialise_contact(c) for c in contacts],
            "total": total,
            "page": page,
            "page_size": page_size,
            "total_pages": max(1, (total + page_size - 1) // page_size),
        }

    def get_customer(self, contact_id: UUID, org_id: UUID) -> dict | None:
        contact = self.contact_repo.get_by_id(contact_id, org_id)
        if not contact:
            return None
        invoices, _ = self.invoice_repo.list_for_contact(contact_id, org_id, page_size=5)
        notes = self.note_repo.list_for_contact(contact_id, org_id)
        tasks = self.task_repo.list_for_org(org_id, contact_id=contact_id)
        mappings = self.mapping_repo.list_for_org(org_id)
        return {
            "customer": _serialise_contact(contact),
            "recent_invoices": [_serialise_invoice(i) for i in invoices],
            "notes": [_serialise_note(n) for n in notes],
            "tasks": [_serialise_task(t) for t in tasks],
            "product_mappings": [_serialise_mapping(m) for m in mappings],
        }

    # ------------------------------------------------------------------
    # Invoices
    # ------------------------------------------------------------------

    def get_customer_invoices(self, contact_id: UUID, org_id: UUID, page: int = 1, page_size: int = 25) -> dict:
        invoices, total = self.invoice_repo.list_for_contact(contact_id, org_id, page=page, page_size=page_size)
        return {
            "invoices": [_serialise_invoice(i, with_line_items=True, db=self.db) for i in invoices],
            "total": total,
            "page": page,
            "page_size": page_size,
        }

    # ------------------------------------------------------------------
    # Notes
    # ------------------------------------------------------------------

    def create_note(self, org_id: UUID, contact_id: UUID, content: str, user_id: UUID | None) -> dict:
        note = self.note_repo.create(org_id, contact_id, content, user_id)
        self.db.commit()
        return _serialise_note(note)

    def update_note(self, note_id: UUID, org_id: UUID, content: str) -> dict | None:
        note = self.note_repo.get_by_id(note_id, org_id)
        if not note:
            return None
        self.note_repo.update(note, content)
        self.db.commit()
        return _serialise_note(note)

    def delete_note(self, note_id: UUID, org_id: UUID) -> bool:
        note = self.note_repo.get_by_id(note_id, org_id)
        if not note:
            return False
        self.note_repo.delete(note)
        self.db.commit()
        return True

    # ------------------------------------------------------------------
    # Tasks
    # ------------------------------------------------------------------

    def list_tasks(
        self, org_id: UUID, contact_id: UUID | None = None, status: str | None = None, assigned_to: UUID | None = None
    ) -> list[dict]:
        tasks = self.task_repo.list_for_org(
            org_id, contact_id=contact_id, status=status, assigned_to_user_id=assigned_to
        )
        return [_serialise_task(t) for t in tasks]

    def create_task(self, org_id: UUID, data: dict, user_id: UUID | None) -> dict:
        from datetime import date

        due_date_raw = data.get("due_date")
        due_date = None
        if due_date_raw:
            due_date = date.fromisoformat(due_date_raw) if isinstance(due_date_raw, str) else due_date_raw

        contact_id = UUID(data["contact_id"]) if data.get("contact_id") else None
        task = self.task_repo.create(
            org_id=org_id,
            title=data["title"],
            contact_id=contact_id,
            description=data.get("description"),
            due_date=due_date,
            priority=data.get("priority", "medium"),
            assigned_to_user_id=UUID(data["assigned_to_user_id"]) if data.get("assigned_to_user_id") else None,
            created_by_user_id=user_id,
        )
        self.db.commit()
        return _serialise_task(task)

    def update_task(self, task_id: UUID, org_id: UUID, data: dict) -> dict | None:
        task = self.task_repo.get_by_id(task_id, org_id)
        if not task:
            return None

        allowed = {"title", "description", "due_date", "status", "priority", "assigned_to_user_id"}
        updates = {k: v for k, v in data.items() if k in allowed}

        if "due_date" in updates and isinstance(updates["due_date"], str):
            from datetime import date

            updates["due_date"] = date.fromisoformat(updates["due_date"])

        if "assigned_to_user_id" in updates and updates["assigned_to_user_id"]:
            updates["assigned_to_user_id"] = UUID(updates["assigned_to_user_id"])

        self.task_repo.update(task, **updates)
        self.db.commit()
        return _serialise_task(task)

    def delete_task(self, task_id: UUID, org_id: UUID) -> bool:
        task = self.task_repo.get_by_id(task_id, org_id)
        if not task:
            return False
        self.task_repo.delete(task)
        self.db.commit()
        return True

    # ------------------------------------------------------------------
    # Analytics
    # ------------------------------------------------------------------

    def monthly_sales(self, org_id: UUID, months: int = 12) -> list[dict]:
        return self.invoice_repo.monthly_sales_totals(org_id, months=months)

    def customer_breakdown(self, org_id: UUID, top_n: int = 20) -> list[dict]:
        return self.invoice_repo.customer_sales_breakdown(org_id, top_n=top_n)

    def churn_risk(self, org_id: UUID) -> list[dict]:
        return self.invoice_repo.churn_risk_data(org_id)

    # ------------------------------------------------------------------
    # Product mappings
    # ------------------------------------------------------------------

    def list_mappings(self, org_id: UUID) -> list[dict]:
        return [_serialise_mapping(m) for m in self.mapping_repo.list_for_org(org_id, active_only=False)]

    def create_mapping(self, org_id: UUID, data: dict, user_id: UUID | None) -> dict:
        m = self.mapping_repo.create(
            org_id=org_id,
            biz_e_product_name=data["biz_e_product_name"],
            xero_description_pattern=data["xero_description_pattern"],
            match_type=data.get("match_type", "exact"),
            notes=data.get("notes"),
            created_by_user_id=user_id,
        )
        self.db.commit()
        return _serialise_mapping(m)

    def update_mapping(self, mapping_id: UUID, org_id: UUID, data: dict) -> dict | None:
        m = self.mapping_repo.get_by_id(mapping_id, org_id)
        if not m:
            return None
        allowed = {"biz_e_product_name", "xero_description_pattern", "match_type", "notes", "is_active"}
        self.mapping_repo.update(m, **{k: v for k, v in data.items() if k in allowed})
        self.db.commit()
        return _serialise_mapping(m)

    def delete_mapping(self, mapping_id: UUID, org_id: UUID) -> bool:
        m = self.mapping_repo.get_by_id(mapping_id, org_id)
        if not m:
            return False
        self.mapping_repo.delete(m)
        self.db.commit()
        return True


# ------------------------------------------------------------------
# Serialisers
# ------------------------------------------------------------------


def _serialise_contact(c) -> dict:
    return {
        "id": str(c.id),
        "xero_contact_id": c.xero_contact_id,
        "name": c.name,
        "first_name": c.first_name,
        "last_name": c.last_name,
        "email_address": c.email_address,
        "phone_number": c.phone_number,
        "addresses": c.addresses,
        "tax_number": c.tax_number,
        "account_number": c.account_number,
        "contact_status": c.contact_status,
        "is_customer": c.is_customer,
        "is_supplier": c.is_supplier,
        "last_synced_at": c.last_synced_at.isoformat() if c.last_synced_at else None,
        "xero_updated_at": c.xero_updated_at.isoformat() if c.xero_updated_at else None,
    }


def _serialise_invoice(inv, with_line_items: bool = False, db=None) -> dict:
    result = {
        "id": str(inv.id),
        "xero_invoice_id": inv.xero_invoice_id,
        "invoice_number": inv.invoice_number,
        "reference": inv.reference,
        "status": inv.status,
        "invoice_type": inv.invoice_type,
        "total": float(inv.total) if inv.total is not None else None,
        "sub_total": float(inv.sub_total) if inv.sub_total is not None else None,
        "total_tax": float(inv.total_tax) if inv.total_tax is not None else None,
        "amount_due": float(inv.amount_due) if inv.amount_due is not None else None,
        "amount_paid": float(inv.amount_paid) if inv.amount_paid is not None else None,
        "currency_code": inv.currency_code,
        "date": inv.date.isoformat() if inv.date else None,
        "due_date": inv.due_date.isoformat() if inv.due_date else None,
        "fully_paid_on_date": inv.fully_paid_on_date.isoformat() if inv.fully_paid_on_date else None,
        "contact_id": str(inv.contact_id) if inv.contact_id else None,
        "last_synced_at": inv.last_synced_at.isoformat() if inv.last_synced_at else None,
    }
    if with_line_items and db:
        from app.features.crm.repositories.xero_invoice_repo import XeroInvoiceRepository

        line_items = XeroInvoiceRepository(db).get_line_items(inv.id)
        result["line_items"] = [_serialise_line_item(li) for li in line_items]
    return result


def _serialise_line_item(li) -> dict:
    return {
        "id": str(li.id),
        "description": li.description,
        "item_code": li.item_code,
        "quantity": float(li.quantity) if li.quantity is not None else None,
        "unit_amount": float(li.unit_amount) if li.unit_amount is not None else None,
        "line_amount": float(li.line_amount) if li.line_amount is not None else None,
        "account_code": li.account_code,
        "tax_type": li.tax_type,
        "discount_rate": float(li.discount_rate) if li.discount_rate is not None else None,
        "tracking": li.tracking,
    }


def _serialise_note(n) -> dict:
    return {
        "id": str(n.id),
        "contact_id": str(n.contact_id),
        "content": n.content,
        "created_by_user_id": str(n.created_by_user_id) if n.created_by_user_id else None,
        "created_at": n.created_at.isoformat() if n.created_at else None,
        "updated_at": n.updated_at.isoformat() if n.updated_at else None,
    }


def _serialise_task(t) -> dict:
    return {
        "id": str(t.id),
        "contact_id": str(t.contact_id) if t.contact_id else None,
        "title": t.title,
        "description": t.description,
        "due_date": t.due_date.isoformat() if t.due_date else None,
        "status": t.status,
        "priority": t.priority,
        "assigned_to_user_id": str(t.assigned_to_user_id) if t.assigned_to_user_id else None,
        "created_by_user_id": str(t.created_by_user_id) if t.created_by_user_id else None,
        "completed_at": t.completed_at.isoformat() if t.completed_at else None,
        "created_at": t.created_at.isoformat() if t.created_at else None,
        "updated_at": t.updated_at.isoformat() if t.updated_at else None,
    }


def _serialise_mapping(m) -> dict:
    return {
        "id": str(m.id),
        "biz_e_product_name": m.biz_e_product_name,
        "xero_description_pattern": m.xero_description_pattern,
        "match_type": m.match_type,
        "is_active": m.is_active,
        "notes": m.notes,
        "created_at": m.created_at.isoformat() if m.created_at else None,
    }


def _serialise_sync_job(j) -> dict:
    return {
        "id": str(j.id),
        "sync_type": j.sync_type,
        "status": j.status,
        "contacts_synced": j.contacts_synced,
        "invoices_synced": j.invoices_synced,
        "started_at": j.started_at.isoformat() if j.started_at else None,
        "completed_at": j.completed_at.isoformat() if j.completed_at else None,
        "error_message": j.error_message,
        "triggered_by": j.triggered_by,
    }
