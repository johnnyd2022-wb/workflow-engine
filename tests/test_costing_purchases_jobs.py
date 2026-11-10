"""Live-cogs 8.1b: the purchases half of the Xero sync jobs (AC71).

Spec .agents/specs/live-cogs.md, "Xero sync changes": the purchases sync runs inside the existing
synchronous job, counts go to ``purchases_synced``, a failure there marks the job ``partial`` and
leaves the sales results intact. ``sync_type`` gains ``purchases`` and ``purchases_history``.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from types import SimpleNamespace

import pytest

from app.features.crm.models.xero_sync_job import XeroSyncJob
from app.features.crm.models.xero_tenant import XeroTenant
from app.features.crm.services.xero_api_client import XeroInsufficientScopeError
from app.features.crm.services.xero_sync_service import XeroSyncService
from tests.costing_helpers import new_org, purge
from tests.costing_purchase_helpers import (
    FakeXero,
    _connect,
    line,
    purchase_documents,
    purchase_lines,
    silence_sales_sync,
    transaction,
)
from tests.test_crm import _latest_event
from tests.test_xero_sync_service import _xero_invoice


@pytest.fixture
def world(db, monkeypatch):
    org = new_org(db)
    _connect(db, org.id)
    silence_sales_sync(monkeypatch)
    yield SimpleNamespace(org=org, fake=FakeXero(monkeypatch))
    purge(db, org)


def jobs(db, org_id):
    db.expire_all()
    return db.query(XeroSyncJob).filter(XeroSyncJob.org_id == org_id).order_by(XeroSyncJob.created_at).all()


def watermark(db, org_id):
    db.expire_all()
    return (
        db.query(XeroTenant)
        .filter(XeroTenant.org_id == org_id, XeroTenant.is_connected.is_(True))
        .one()
        .last_successful_sync_at
    )


def test_ac71_a_full_sync_pulls_purchases_and_counts_them_on_the_job(world, db):
    world.fake.transactions = [transaction("t1", [line(line_id="A")]), transaction("t2", [line(line_id="B")])]

    result = XeroSyncService(db).full_sync(world.org.id, triggered_by="test")

    assert result.success and result.purchases_synced == 2
    (job,) = jobs(db, world.org.id)
    assert job.sync_type == "full" and job.status == "completed" and job.purchases_synced == 2
    assert {l.line_key for l in purchase_lines(db, world.org.id)} == {"A", "B"}  # noqa: E741
    (call,) = world.fake.transaction_calls()
    assert call["modified_after"] is None  # a full sync asks for everything
    event = _latest_event(db, world.org.id, "crm_xero.sync_completed")
    assert event.payload["purchases_synced"] == 2


def test_ac71_an_incremental_sync_asks_xero_for_purchases_changed_since_the_resume_point(world, db):
    XeroSyncService(db).full_sync(world.org.id, triggered_by="test")
    resume_from = watermark(db, world.org.id)
    assert resume_from is not None
    world.fake.transactions = [transaction("t1", [line(line_id="A")])]

    result = XeroSyncService(db).incremental_sync(world.org.id, triggered_by="test")

    assert result.success and result.purchases_synced == 1
    assert world.fake.transaction_calls()[-1]["modified_after"] == resume_from
    assert jobs(db, world.org.id)[-1].purchases_synced == 1


def test_ac71_an_organisation_without_costing_is_never_asked_about_purchases(db, monkeypatch):
    org = new_org(db, grant=False)
    try:
        _connect(db, org.id)
        silence_sales_sync(monkeypatch)
        fake = FakeXero(monkeypatch, transactions=[transaction("t1", [line()])])

        result = XeroSyncService(db).full_sync(org.id, triggered_by="test")

        assert result.success and result.purchases_synced == 0
        assert fake.calls == []
        assert purchase_documents(db, org.id) == []
        assert jobs(db, org.id)[0].purchases_synced == 0
    finally:
        purge(db, org)


def test_ac71_a_purchases_failure_marks_the_job_partial_and_keeps_the_sales_results(world, db, monkeypatch):
    from app.features.crm.services.xero_api_client import XeroAPIClient

    monkeypatch.setattr(XeroAPIClient, "get_all_invoices", lambda self, **kw: [_xero_invoice("inv-1", "INV-1")])
    world.fake.fail_transactions = RuntimeError("Xero fell over")

    result = XeroSyncService(db).full_sync(world.org.id, triggered_by="test")

    assert not result.success and result.invoices_synced == 1
    (job,) = jobs(db, world.org.id)
    assert job.status == "partial" and job.invoices_synced == 1 and job.purchases_synced == 0
    assert "Xero fell over" in str(job.error_details)
    assert watermark(db, world.org.id) is None  # records that failed are retried next time


def test_ac71_a_purchases_failure_is_partial_even_when_there_were_no_sales_to_sync(world, db):
    world.fake.fail_transactions = RuntimeError("Xero fell over")

    XeroSyncService(db).incremental_sync(world.org.id, triggered_by="test")

    assert jobs(db, world.org.id)[0].status == "partial"


def test_ac71_missing_scopes_say_to_reconnect(world, db):
    world.fake.fail_accounts = XeroInsufficientScopeError("Reconnect Xero to update its permissions.")

    result = XeroSyncService(db).purchases_sync(world.org.id, triggered_by="test")

    assert not result.success and "reconnect" in result.errors[0].lower()
    assert jobs(db, world.org.id)[0].status == "failed"  # nothing at all synced
    assert world.fake.transaction_calls() == []  # no chart of accounts, so nothing can be classified


def test_ac71_a_purchases_job_syncs_only_purchases_and_leaves_the_sales_resume_point_alone(world, db):
    XeroSyncService(db).full_sync(world.org.id, triggered_by="test")
    resume_from = watermark(db, world.org.id)
    world.fake.transactions = [transaction("t1", [line(line_id="A")])]
    world.fake.calls.clear()

    result = world.fake.sync(db, world.org)

    assert result.success and result.purchases_synced == 1
    job = jobs(db, world.org.id)[-1]
    assert job.sync_type == "purchases" and job.status == "completed" and job.purchases_synced == 1
    assert job.contacts_synced == job.invoices_synced == job.credit_notes_synced == 0
    assert watermark(db, world.org.id) == resume_from
    assert world.fake.transaction_calls()[0]["modified_after"] == resume_from  # incremental by default


def test_ac71_a_purchases_job_can_ask_for_everything(world, db):
    XeroSyncService(db).full_sync(world.org.id, triggered_by="test")
    world.fake.calls.clear()

    world.fake.sync(db, world.org, full=True)

    assert world.fake.transaction_calls()[0]["modified_after"] is None


def test_ac71_a_never_synced_organisation_gets_everything_from_a_purchases_job(world, db):
    world.fake.sync(db, world.org)
    assert world.fake.transaction_calls()[0]["modified_after"] is None


def test_ac71_a_history_job_fetches_a_date_range_and_can_be_repeated(world, db):
    world.fake.transactions = [transaction("t1", [line(line_id="A")], day=date(2026, 10, 15))]

    first = XeroSyncService(db).purchases_history_sync(
        world.org.id, date(2026, 10, 1), date(2026, 10, 31), triggered_by="test"
    )
    second = XeroSyncService(db).purchases_history_sync(
        world.org.id, date(2026, 10, 1), date(2026, 10, 31), triggered_by="test"
    )

    assert first.success and first.purchases_synced == 1 and second.purchases_synced == 1
    calls = world.fake.transaction_calls()
    assert len(calls) == 2  # asks Xero again every time
    assert all(c["date_from"] == date(2026, 10, 1) and c["date_to"] == date(2026, 10, 31) for c in calls)
    assert all(c["modified_after"] is None for c in calls)  # by transaction date, not modified date
    assert len(purchase_documents(db, world.org.id)) == 1 and len(purchase_lines(db, world.org.id)) == 1
    assert [j.sync_type for j in jobs(db, world.org.id)] == ["purchases_history", "purchases_history"]
    assert watermark(db, world.org.id) is None


def test_ac71_a_history_job_needs_a_sane_range(world, db):
    with pytest.raises(ValueError):
        XeroSyncService(db).purchases_history_sync(world.org.id, date(2026, 11, 1), date(2026, 10, 1))


def test_ac71_purchases_jobs_are_refused_for_an_organisation_without_costing(db, monkeypatch):
    org = new_org(db, grant=False)
    try:
        _connect(db, org.id)
        fake = FakeXero(monkeypatch)
        with pytest.raises(ValueError, match="costing"):
            XeroSyncService(db).purchases_sync(org.id, triggered_by="test")
        with pytest.raises(ValueError, match="costing"):
            XeroSyncService(db).purchases_history_sync(org.id, date(2026, 10, 1), date(2026, 10, 31))
        assert fake.calls == []
    finally:
        purge(db, org)


def test_ac71_the_job_records_the_new_column_default(db, world):
    XeroSyncService(db).full_sync(world.org.id, triggered_by="test")
    job = jobs(db, world.org.id)[0]
    assert job.purchases_synced == 0 and job.started_at <= datetime.now(UTC)
