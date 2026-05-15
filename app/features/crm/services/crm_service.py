"""CRMService — high-level CRM queries, notes, tasks, and product mapping."""

from datetime import date, datetime
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.db.models.inventory_item import InventoryItem, InventoryType
from app.features.crm.repositories.crm_task_repo import CRMNoteRepository, CRMTaskRepository
from app.features.crm.repositories.product_mapping_repo import ProductMappingRepository
from app.features.crm.repositories.sales_traceability_repo import SalesTraceabilityConfigRepository
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
        self.traceability_repo = SalesTraceabilityConfigRepository(db)
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
            return {"connected": False, "is_connected": False}

        return {
            "connected": True,
            "is_connected": True,
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
            "recent_invoices": [_serialise_invoice(i, with_line_items=True, db=self.db) for i in invoices],
            "notes": [_serialise_note(n) for n in notes],
            "tasks": [_serialise_task(t, db=self.db) for t in tasks],
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

    def get_org_invoices(
        self,
        org_id: UUID,
        *,
        kind: str = "all",
        page: int = 1,
        page_size: int = 50,
    ) -> dict:
        from datetime import date

        start_date = None
        end_date = None
        outstanding_only = False
        if kind == "this_month":
            today = date.today()
            start_date = today.replace(day=1)
            if start_date.month == 12:
                end_date = start_date.replace(year=start_date.year + 1, month=1)
            else:
                end_date = start_date.replace(month=start_date.month + 1)
        elif kind == "outstanding":
            outstanding_only = True

        invoices, total = self.invoice_repo.list_for_org(
            org_id,
            start_date=start_date,
            end_date=end_date,
            outstanding_only=outstanding_only,
            page=page,
            page_size=page_size,
        )
        from app.features.crm.models.xero_contact import XeroContact

        contact_ids = [inv.contact_id for inv in invoices if inv.contact_id]
        contact_name_map: dict[str, str] = {}
        if contact_ids:
            contact_rows = (
                self.db.query(XeroContact.id, XeroContact.name)
                .filter(XeroContact.org_id == org_id, XeroContact.id.in_(contact_ids))
                .all()
            )
            contact_name_map = {str(row.id): row.name for row in contact_rows}

        serialised = [_serialise_invoice(i, with_line_items=True, db=self.db) for i in invoices]
        for row in serialised:
            cid = row.get("contact_id")
            row["contact_name"] = contact_name_map.get(cid) if cid else None

        return {
            "invoices": serialised,
            "total": total,
            "page": page,
            "page_size": page_size,
            "kind": kind,
        }

    def get_customer_analytics(
        self,
        contact_id: UUID,
        org_id: UUID,
        *,
        start_date=None,
        end_date=None,
    ) -> dict:
        monthly = self.invoice_repo.monthly_sales_totals_for_contact(
            contact_id=contact_id,
            org_id=org_id,
            start_date=start_date,
            end_date=end_date,
        )
        top_products = self.invoice_repo.top_products_for_contact(
            contact_id=contact_id,
            org_id=org_id,
            limit=8,
            start_date=start_date,
            end_date=end_date,
        )
        total_revenue = sum(float(row.get("total") or 0) for row in monthly)
        total_invoices = sum(int(row.get("invoice_count") or 0) for row in monthly)
        return {
            "monthly_sales": monthly,
            "top_products": top_products,
            "total_revenue": total_revenue,
            "total_invoices": total_invoices,
        }

    def get_customer_line_item_options(self, contact_id: UUID, org_id: UUID) -> list[dict]:
        return self.invoice_repo.line_item_options_for_contact(contact_id, org_id)

    def get_org_line_item_options(self, org_id: UUID) -> list[dict]:
        return self.invoice_repo.line_item_options_for_org(org_id)

    def get_customer_line_item_pricing(
        self,
        contact_id: UUID,
        org_id: UUID,
        *,
        description: str | None = None,
        item_code: str | None = None,
    ) -> dict | None:
        return self.invoice_repo.line_item_pricing_for_contact(
            contact_id,
            org_id,
            description=description,
            item_code=item_code,
        )

    def suggest_invoice_due_date(self, contact_id: UUID, org_id: UUID, invoice_date) -> date | None:
        contact = self.contact_repo.get_by_id(contact_id, org_id)
        if not contact:
            raise ValueError("Customer not found")
        terms = contact.payment_terms
        if not terms and contact.xero_contact_id:
            try:
                from app.features.crm.services.xero_api_client import XeroAPIClient

                terms = XeroAPIClient(self.db, org_id).get_contact_payment_terms(contact.xero_contact_id)
                if terms:
                    contact.payment_terms = terms
                    self.db.commit()
            except Exception:
                terms = None
        if terms and isinstance(terms, dict):
            sales = terms.get("sales") if isinstance(terms.get("sales"), dict) else None
            if sales:
                type_raw = str(sales.get("type") or "").upper()
                day_raw = sales.get("day")
                if ("MONTH" in type_raw or "FOLLOWINGMONTH" in type_raw) and not day_raw:
                    inferred_day = self.invoice_repo.inferred_due_day_for_contact(contact_id, org_id)
                    if inferred_day:
                        patched = dict(terms)
                        patched_sales = dict(sales)
                        patched_sales["day"] = inferred_day
                        patched["sales"] = patched_sales
                        terms = patched
        return _suggest_due_date_from_terms(invoice_date, terms)

    def get_traceability_config(self, org_id: UUID) -> dict:
        row = self.traceability_repo.get_for_org(org_id)
        if not row:
            return {
                "matching_strategy": "fifo",
                "matching_key": "batch_id",
                "manual_review_days": 7,
                "strict_mapping": True,
            }
        return {
            "matching_strategy": row.matching_strategy,
            "matching_key": row.matching_key,
            "manual_review_days": row.manual_review_days,
            "strict_mapping": bool(row.strict_mapping),
        }

    def update_traceability_config(self, org_id: UUID, data: dict) -> dict:
        strategy = (data.get("matching_strategy") or "fifo").strip().lower()
        if strategy not in {"fifo", "manual", "hybrid"}:
            raise ValueError("matching_strategy must be fifo, manual, or hybrid")
        manual_review_days = int(data.get("manual_review_days") or 7)
        manual_review_days = min(90, max(1, manual_review_days))
        strict_mapping = bool(data.get("strict_mapping", True))
        row = self.traceability_repo.upsert(
            org_id=org_id,
            matching_strategy=strategy,
            matching_key="batch_id",
            manual_review_days=manual_review_days,
            strict_mapping=strict_mapping,
        )
        self.db.commit()
        return {
            "matching_strategy": row.matching_strategy,
            "matching_key": row.matching_key,
            "manual_review_days": row.manual_review_days,
            "strict_mapping": bool(row.strict_mapping),
        }

    def create_customer_invoice(self, contact_id: UUID, org_id: UUID, data: dict) -> dict:
        from datetime import date

        contact = self.contact_repo.get_by_id(contact_id, org_id)
        if not contact:
            raise ValueError("Customer not found")
        if not contact.xero_contact_id:
            raise ValueError("Customer is missing Xero contact id")

        invoice_date_raw = data.get("invoice_date")
        if not invoice_date_raw:
            raise ValueError("invoice_date is required")
        invoice_date = date.fromisoformat(invoice_date_raw) if isinstance(invoice_date_raw, str) else invoice_date_raw

        due_date = None
        if data.get("due_date"):
            due_date = date.fromisoformat(data["due_date"]) if isinstance(data["due_date"], str) else data["due_date"]
        if due_date is None:
            due_date = _suggest_due_date_from_terms(invoice_date, contact.payment_terms)

        invoice_status = (data.get("invoice_status") or "DRAFT").strip().upper()
        if invoice_status not in {"DRAFT", "AUTHORISED"}:
            raise ValueError("invoice_status must be DRAFT or AUTHORISED")

        rows = data.get("line_items") or []
        if not rows:
            raise ValueError("At least one line item is required")

        line_items = []
        for idx, row in enumerate(rows):
            description = (row.get("description") or "").strip()
            item_code = (row.get("item_code") or "").strip() or None
            quantity = row.get("quantity")
            unit_amount = row.get("unit_amount")
            if not description:
                raise ValueError(f"line_items[{idx}].description is required")
            if quantity is None or float(quantity) <= 0:
                raise ValueError(f"line_items[{idx}].quantity must be > 0")
            if unit_amount is None:
                raise ValueError(f"line_items[{idx}].unit_amount is required")
            line_items.append(
                {
                    "description": description,
                    "item_code": item_code,
                    "quantity": float(quantity),
                    "unit_amount": float(unit_amount),
                    "tax_type": (row.get("tax_type") or "").strip() or None,
                    "account_code": (row.get("account_code") or "").strip() or None,
                }
            )

        from app.features.crm.services.xero_api_client import XeroAPIClient
        from app.features.crm.services.xero_sync_service import XeroSyncService

        created = XeroAPIClient(self.db, org_id).create_invoice(
            contact_xero_id=contact.xero_contact_id,
            invoice_date=invoice_date,
            due_date=due_date,
            line_items=line_items,
            status=invoice_status,
        )
        # Refresh local records so the new invoice appears in CRM without waiting for manual sync.
        try:
            XeroSyncService(self.db).incremental_sync(org_id, triggered_by="crm_invoice_create")
        except Exception:
            # Keep created invoice response even if sync fails.
            pass

        return {
            "xero_invoice_id": str(getattr(created, "invoice_id", "") or ""),
            "invoice_number": getattr(created, "invoice_number", None),
            "status": getattr(created, "status", None),
            "date": created.date.isoformat() if getattr(created, "date", None) else None,
            "due_date": created.due_date.isoformat() if getattr(created, "due_date", None) else None,
            "total": float(getattr(created, "total", 0) or 0),
        }

    def authorise_invoice(self, invoice_id: UUID, org_id: UUID) -> dict:
        from app.features.crm.services.xero_api_client import XeroAPIClient
        from app.features.crm.services.xero_sync_service import XeroSyncService

        inv = self.invoice_repo.get_by_id(invoice_id, org_id)
        if not inv:
            raise ValueError("Invoice not found")
        if not inv.xero_invoice_id:
            raise ValueError("Invoice is missing Xero invoice id")

        current = (inv.status or "").strip().upper()
        if current in {"AUTHORISED", "PAID"}:
            return _serialise_invoice(inv, with_line_items=True, db=self.db)
        if current and current != "DRAFT":
            raise ValueError(f"Only draft invoices can be authorised (current status: {current}).")

        updated = XeroAPIClient(self.db, org_id).authorise_invoice(xero_invoice_id=inv.xero_invoice_id)

        # Update local copy immediately, then refresh from Xero in background for full fidelity.
        updated_status = getattr(updated, "status", None)
        if updated_status:
            inv.status = str(updated_status)
            inv.updated_at = datetime.utcnow()
            self.db.commit()

        try:
            XeroSyncService(self.db).incremental_sync(org_id, triggered_by="crm_invoice_authorise")
            refreshed = self.invoice_repo.get_by_id(invoice_id, org_id)
            if refreshed:
                return _serialise_invoice(refreshed, with_line_items=True, db=self.db)
        except Exception:
            pass

        return _serialise_invoice(inv, with_line_items=True, db=self.db)

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
    ) -> list[dict] | dict[str, list[dict]]:
        # Backward compatibility for older callsites/tests that pass filters as a dict:
        # list_tasks(org_id, {"status": "...", "contact_id": "...", "assigned_to": "..."})
        legacy_wrap = False
        if isinstance(contact_id, dict) and status is None and assigned_to is None:
            filters = contact_id
            legacy_wrap = True
            raw_contact = filters.get("contact_id")
            raw_status = filters.get("status")
            raw_assigned = filters.get("assigned_to")
            contact_id = UUID(raw_contact) if raw_contact else None
            status = raw_status or None
            assigned_to = UUID(raw_assigned) if raw_assigned else None

        tasks = self.task_repo.list_for_org(
            org_id, contact_id=contact_id, status=status, assigned_to_user_id=assigned_to
        )
        serialised = [_serialise_task(t, db=self.db) for t in tasks]
        if legacy_wrap:
            return {"tasks": serialised}
        return serialised

    def create_task(self, org_id: UUID, data: dict, user_id: UUID | None) -> dict:
        from datetime import date

        due_date_raw = data.get("due_date")
        due_date = None
        if due_date_raw:
            due_date = date.fromisoformat(due_date_raw) if isinstance(due_date_raw, str) else due_date_raw

        contact_raw = data.get("contact_id")
        if isinstance(contact_raw, str) and contact_raw.strip().lower() in {"", "null", "none"}:
            contact_raw = None
        contact_id = UUID(contact_raw) if contact_raw else None
        if contact_id and not self.contact_repo.get_by_id(contact_id, org_id):
            raise ValueError("Customer not found")
        assigned_raw = data.get("assigned_to_user_id")
        if isinstance(assigned_raw, str) and assigned_raw.strip().lower() in {"", "null", "none"}:
            assigned_raw = None
        task = self.task_repo.create(
            org_id=org_id,
            title=data["title"],
            contact_id=contact_id,
            description=data.get("description"),
            due_date=due_date,
            priority=data.get("priority", "medium"),
            assigned_to_user_id=UUID(assigned_raw) if assigned_raw else None,
            created_by_user_id=user_id,
        )
        self.db.commit()
        return _serialise_task(task, db=self.db)

    def update_task(self, task_id: UUID, org_id: UUID, data: dict) -> dict | None:
        task = self.task_repo.get_by_id(task_id, org_id)
        if not task:
            return None

        allowed = {"title", "description", "due_date", "status", "priority", "assigned_to_user_id", "contact_id"}
        updates = {k: v for k, v in data.items() if k in allowed}

        if "due_date" in updates and isinstance(updates["due_date"], str):
            from datetime import date

            updates["due_date"] = date.fromisoformat(updates["due_date"])

        if "assigned_to_user_id" in updates:
            raw_assigned = updates["assigned_to_user_id"]
            if isinstance(raw_assigned, str) and raw_assigned.strip().lower() in {"", "null", "none"}:
                raw_assigned = None
            if raw_assigned:
                updates["assigned_to_user_id"] = UUID(raw_assigned)
            else:
                updates["assigned_to_user_id"] = None
        if "contact_id" in updates:
            raw_contact = updates["contact_id"]
            if isinstance(raw_contact, str) and raw_contact.strip().lower() in {"", "null", "none"}:
                raw_contact = None
            if raw_contact:
                updates["contact_id"] = UUID(raw_contact)
                if not self.contact_repo.get_by_id(updates["contact_id"], org_id):
                    raise ValueError("Customer not found")
            else:
                updates["contact_id"] = None

        self.task_repo.update(task, **updates)
        self.db.commit()
        return _serialise_task(task, db=self.db)

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

    def rankings(
        self,
        org_id: UUID,
        *,
        entity: str,
        direction: str,
        limit: int,
        start_date=None,
        end_date=None,
    ) -> list[dict]:
        descending = direction != "bottom"
        if entity == "customers_by_product":
            return self.invoice_repo.customer_product_breakdown(
                org_id,
                limit=limit,
                start_date=start_date,
                end_date=end_date,
                descending=descending,
            )
        if entity == "products":
            return self.invoice_repo.top_products(
                org_id,
                limit=limit,
                start_date=start_date,
                end_date=end_date,
                descending=descending,
            )
        return self.invoice_repo.customer_sales_breakdown(
            org_id,
            top_n=limit,
            start_date=start_date,
            end_date=end_date,
            descending=descending,
        )

    def churn_risk(self, org_id: UUID) -> list[dict]:
        return self.invoice_repo.churn_risk_data(org_id)

    def get_overview(self, org_id: UUID) -> dict:
        from datetime import date, timedelta

        today = date.today()
        current_month_start = today.replace(day=1)
        if current_month_start.month == 1:
            previous_month_start = current_month_start.replace(year=current_month_start.year - 1, month=12)
        else:
            previous_month_start = current_month_start.replace(month=current_month_start.month - 1)
        next_month_start = (
            current_month_start.replace(year=current_month_start.year + 1, month=1)
            if current_month_start.month == 12
            else current_month_start.replace(month=current_month_start.month + 1)
        )

        current_month = self.invoice_repo.sales_totals_for_period(org_id, current_month_start, next_month_start)
        previous_month = self.invoice_repo.sales_totals_for_period(org_id, previous_month_start, current_month_start)
        outstanding = self.invoice_repo.outstanding_receivables(org_id)
        monthly_trend = sorted(self.invoice_repo.monthly_sales_totals(org_id, months=6), key=lambda row: row["month"] or "")
        top_products = self.invoice_repo.top_products(org_id, limit=200)
        top_customers = self.invoice_repo.customer_sales_breakdown(org_id, top_n=200)
        top_customers_by_product = self.invoice_repo.top_customers_by_product(org_id, limit_products=50)

        tasks = self.task_repo.list_for_org(org_id)
        completed_cutoff = today - timedelta(days=7)
        open_tasks = [task for task in tasks if task.status in ("pending", "in_progress")]
        overview_tasks = [
            task
            for task in tasks
            if task.status in ("pending", "in_progress")
            or (task.status == "completed" and task.completed_at and task.completed_at.date() >= completed_cutoff)
            or task.status == "cancelled"
        ]
        tasks_by_status = {
            "pending": sum(1 for task in tasks if task.status == "pending"),
            "in_progress": sum(1 for task in tasks if task.status == "in_progress"),
            "completed": sum(1 for task in tasks if task.status == "completed"),
            "cancelled": sum(1 for task in tasks if task.status == "cancelled"),
        }

        previous_total = previous_month["total"]
        revenue_vs_last_month_pct = None
        if previous_total:
            revenue_vs_last_month_pct = round(((current_month["total"] - previous_total) / previous_total) * 100, 1)

        return {
            "current_month_revenue": current_month["total"],
            "current_month_invoice_count": current_month["invoice_count"],
            "outstanding_receivables": outstanding["total"],
            "outstanding_invoice_count": outstanding["invoice_count"],
            "revenue_vs_last_month_pct": revenue_vs_last_month_pct,
            "top_products": top_products,
            "top_customers": top_customers,
            "top_customers_by_product": top_customers_by_product,
            "monthly_trend": monthly_trend,
            "open_tasks": [_serialise_task(task, db=self.db) for task in open_tasks],
            "overview_tasks": [_serialise_task(task, db=self.db) for task in overview_tasks],
            "tasks_by_status": tasks_by_status,
        }

    # ------------------------------------------------------------------
    # Product mappings
    # ------------------------------------------------------------------

    def list_mappings(self, org_id: UUID) -> list[dict]:
        products = self.list_final_products(org_id)
        valid_source_output_ids = {row["source_output_id"] for row in products if row.get("source_output_id")}
        valid_names = {(row["name"] or "").strip().lower() for row in products if row.get("name")}
        return [
            _serialise_mapping(m, valid_source_output_ids=valid_source_output_ids, valid_product_names=valid_names)
            for m in self.mapping_repo.list_for_org(org_id, active_only=False)
        ]

    def list_final_products(self, org_id: UUID) -> list[dict]:
        rows = (
            self.db.query(InventoryItem)
            .filter(
                InventoryItem.org_id == org_id,
                InventoryItem.inventory_type == InventoryType.FINAL_PRODUCT.value,
            )
            .order_by(InventoryItem.updated_at.desc().nulls_last(), InventoryItem.created_at.desc().nulls_last())
            .all()
        )
        options: list[dict] = []
        seen: set[tuple[str, str]] = set()
        for item in rows:
            source_output_id = str(item.source_output_id) if item.source_output_id else ""
            name = (item.name or "").strip()
            if not name:
                continue
            key = (source_output_id, name.lower())
            if key in seen:
                continue
            seen.add(key)
            options.append(
                {
                    "inventory_item_id": str(item.id),
                    "name": name,
                    "source_output_id": source_output_id or None,
                    "source_step_name": item.source_step_name,
                }
            )
        return options

    def create_mapping(self, org_id: UUID, data: dict, user_id: UUID | None) -> dict:
        from app.features.crm.models.product_mapping import ProductMapping

        biz_name = (data.get("biz_e_product_name") or "").strip()
        xero_pattern = (data.get("xero_description_pattern") or "").strip()
        if not biz_name or not xero_pattern:
            raise ValueError("biz_e_product_name and xero_description_pattern are required")

        existing = (
            self.db.query(ProductMapping)
            .filter(
                ProductMapping.org_id == org_id,
                ProductMapping.biz_e_product_name == biz_name,
                ProductMapping.xero_description_pattern == xero_pattern,
            )
            .first()
        )
        if existing is not None:
            raise ValueError("This mapping already exists")

        m = self.mapping_repo.create(
            org_id=org_id,
            biz_e_source_output_id=UUID(data["biz_e_source_output_id"]) if data.get("biz_e_source_output_id") else None,
            biz_e_product_name=biz_name,
            xero_description_pattern=xero_pattern,
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
        allowed = {
            "biz_e_source_output_id",
            "biz_e_product_name",
            "xero_description_pattern",
            "match_type",
            "notes",
            "is_active",
        }
        updates = {k: v for k, v in data.items() if k in allowed}
        if "biz_e_source_output_id" in updates:
            updates["biz_e_source_output_id"] = UUID(updates["biz_e_source_output_id"]) if updates["biz_e_source_output_id"] else None
        self.mapping_repo.update(m, **updates)
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
        "payment_terms": c.payment_terms,
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


def _serialise_task(t, db=None) -> dict:
    customer = None
    if db is not None and getattr(t, "contact_id", None):
        from app.features.crm.models.xero_contact import XeroContact

        customer = db.query(XeroContact).filter(XeroContact.id == t.contact_id).first()
    return {
        "id": str(t.id),
        "contact_id": str(t.contact_id) if t.contact_id else None,
        "contact_name": customer.name if customer else None,
        "contact_email": customer.email_address if customer else None,
        "contact_phone": customer.phone_number if customer else None,
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


def _serialise_mapping(m, *, valid_source_output_ids: set[str] | None = None, valid_product_names: set[str] | None = None) -> dict:
    source_output_id = str(m.biz_e_source_output_id) if m.biz_e_source_output_id else None
    status = "active"
    if source_output_id and valid_source_output_ids is not None and source_output_id not in valid_source_output_ids:
        status = "stale"
    elif (
        not source_output_id
        and valid_product_names is not None
        and (m.biz_e_product_name or "").strip().lower() not in valid_product_names
    ):
        status = "stale"
    return {
        "id": str(m.id),
        "biz_e_source_output_id": source_output_id,
        "biz_e_product_name": m.biz_e_product_name,
        "xero_description_pattern": m.xero_description_pattern,
        "match_type": m.match_type,
        "mapping_status": status,
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


def _suggest_due_date_from_terms(invoice_date, payment_terms):
    from datetime import timedelta

    if not payment_terms or not isinstance(payment_terms, dict):
        return None
    sales = payment_terms.get("sales") or {}
    if not isinstance(sales, dict):
        return None

    day = int(sales.get("day") or 0) if sales.get("day") is not None else 0
    month_hint = int(sales.get("month") or 0) if sales.get("month") is not None else 0
    type_raw = str(sales.get("type") or "").upper()

    if "DAYSAFTER" in type_raw and day >= 0:
        return invoice_date + timedelta(days=day)

    month_offset = 0
    if "FOLLOWINGMONTH" in type_raw:
        month_offset = 1
    if "MONTHSAFTER" in type_raw:
        month_offset = month_hint if month_hint > 0 else 1

    if "MONTH" in type_raw or month_offset > 0:
        y = invoice_date.year
        m = invoice_date.month + month_offset
        while m > 12:
            y += 1
            m -= 12
        due_day = day if day > 0 else invoice_date.day
        from calendar import monthrange

        return invoice_date.replace(year=y, month=m, day=min(due_day, monthrange(y, m)[1]))

    if day > 0:
        from calendar import monthrange

        due = invoice_date.replace(day=min(day, monthrange(invoice_date.year, invoice_date.month)[1]))
        if due < invoice_date:
            y = due.year
            m = due.month + 1
            if m > 12:
                y += 1
                m = 1
            due = due.replace(year=y, month=m, day=min(day, monthrange(y, m)[1]))
        return due

    return None
