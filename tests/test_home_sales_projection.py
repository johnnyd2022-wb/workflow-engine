"""Home must remain a live, tenant-scoped projection rather than the full Sales analysis."""

from datetime import date, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import event

from app.features.crm.models.crm_task import CRMTask
from app.features.crm.models.xero_contact import XeroContact
from app.features.crm.models.xero_invoice import XeroInvoice
from app.features.crm.services.crm_service import CRMService
from tests.factories import OrganisationFactory


@pytest.mark.parametrize("today", [date(2026, 1, 15), date(2026, 10, 15)])
def test_home_sales_totals_and_tasks_are_live_isolated_and_constant_query_count(db, monkeypatch, today):
    from app.features.crm.services import crm_service

    class Clock(date):
        @classmethod
        def today(cls):
            return today

    monkeypatch.setattr(crm_service, "date", Clock)
    own, other = OrganisationFactory(), OrganisationFactory()
    own_id, other_id = own.id, other.id
    month_start = today.replace(day=1)
    previous_day = month_start - timedelta(days=1)
    next_month = (month_start + timedelta(days=32)).replace(day=1)
    contacts = [
        XeroContact(org_id=org_id, source="bize", name=name)
        for org_id, name in ((own_id, "Our customer"), (other_id, "Private neighbour"))
    ]
    db.add_all(contacts)
    db.flush()
    for org_id, status, kind, day, amount, due in (
        (own_id, "AUTHORISED", "ACCREC", today, 300, 100),
        (own_id, "PAID", "ACCREC", today, 200, 0),
        (own_id, "PAID", "ACCREC", previous_day, 250, 0),
        (own_id, "DRAFT", "ACCREC", today, 9000, 9000),
        (own_id, "VOIDED", "ACCREC", today, 9000, 9000),
        (own_id, "AUTHORISED", "ACCPAY", today, 9000, 9000),
        (own_id, "PAID", "ACCREC", next_month, 9000, 0),
        (other_id, "AUTHORISED", "ACCREC", today, 9000, 9000),
    ):
        db.add(
            XeroInvoice(
                org_id=org_id,
                xero_invoice_id=str(uuid4()),
                xero_tenant_id="home-test",
                status=status,
                invoice_type=kind,
                date=day,
                total=amount,
                amount_due=due,
            )
        )
    db.add_all(
        [
            CRMTask(
                org_id=own_id,
                title=f"Open {i}",
                status="pending",
                contact_id=contacts[0].id,
                due_date=today,
                priority="high",
            )
            for i in range(40)
        ]
    )
    db.add_all(
        [
            CRMTask(org_id=own_id, title="No contact", status="in_progress"),
            # Even a bad historic cross-org FK must not disclose a neighbour's contact name.
            CRMTask(org_id=own_id, title="Foreign contact", status="pending", contact_id=contacts[1].id),
            CRMTask(org_id=other_id, title="Other org", status="pending"),
            *[CRMTask(org_id=own_id, title=f"Archived {i}", status="completed") for i in range(100)],
            CRMTask(org_id=own_id, title="Cancelled", status="cancelled"),
        ]
    )
    db.flush()

    def forbidden(*args, **kwargs):
        pytest.fail("Home must not build Sales analysis or serialise archived task history")

    service = CRMService(db)
    monkeypatch.setattr(service, "get_overview", forbidden)
    monkeypatch.setattr(service.task_repo, "list_for_org", forbidden)
    monkeypatch.setattr(service.invoice_repo, "customer_sales_breakdown", forbidden)
    monkeypatch.setattr(service.invoice_repo, "top_customers_by_product", forbidden)
    statements = []

    def capture(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    event.listen(db.bind, "before_cursor_execute", capture)
    try:
        summary = service.get_dashboard_overview(own_id)
        assert len(statements) == 4, "Customer names must be joined, not loaded once per task"
        assert summary["current_month_revenue"] == 500
        assert summary["outstanding_receivables"] == 100
        assert summary["revenue_vs_last_month_pct"] == 100
        tasks = summary["open_tasks"]
        assert len(tasks) == 42
        assert {t["contact_name"] for t in tasks} == {None, "Our customer"}
        assert all(t["status"] in {"pending", "in_progress"} for t in tasks)
        assert {t["due_date"] for t in tasks} == {None, today.isoformat()}
        # A later request must see committed/current data without a response cache.
        invoice = db.query(XeroInvoice).filter(XeroInvoice.org_id == own_id, XeroInvoice.total == 300).one()
        invoice.total = 400
        db.flush()
        assert service.get_dashboard_overview(own_id)["current_month_revenue"] == 600
    finally:
        event.remove(db.bind, "before_cursor_execute", capture)
        db.rollback()
