"""Legacy credit notes receive per-line tax snapshots on the next Xero sync."""

from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.features.crm.models.xero_credit_note import XeroCreditNote
from app.features.crm.models.xero_credit_note_line import XeroCreditNoteLine
from app.features.crm.services import xero_api_client as xero_api_client_module
from app.features.crm.services.xero_sync_service import XeroSyncService
from tests.test_compliant_routes import flask_app  # noqa: F401 -- fixture required by costing world
from tests.test_costing_margins import _row
from tests.test_costing_margins import world as _costing_world
from tests.test_crm_contact_sync import _connect


@pytest.fixture
def costing_world(db, request):
    app = request.getfixturevalue("flask_app")
    yield from _costing_world.__wrapped__(db, app)


def _note(db, org_id, *, raw_fields=None, xero_id=None):
    from app.features.crm.models.product_mapping import ProductMapping

    mapping = (
        db.query(ProductMapping)
        .filter(
            ProductMapping.org_id == org_id,
            ProductMapping.biz_e_product_name == "Wildflower",
            ProductMapping.xero_description_pattern == "Wildflower Gin 700ml",
        )
        .first()
    )
    if mapping is None:
        mapping = ProductMapping(
            org_id=org_id,
            biz_e_product_name="Wildflower",
            xero_description_pattern="Wildflower Gin 700ml",
        )
        db.add(mapping)
        db.flush()
    note = XeroCreditNote(
        org_id=org_id,
        xero_credit_note_id=xero_id or f"cn-{uuid4()}",
        xero_tenant_id="fake-tenant-id",
        number="CN-LEGACY",
        date=datetime(2026, 10, 20, tzinfo=UTC).date(),
        status="AUTHORISED",
        total=Decimal("215"),
        currency="NZD",
        raw_fields=raw_fields or {"sub_total": "200", "total_tax": "15", "line_amounts": {"gst": "115", "zero": "100"}},
    )
    db.add(note)
    db.flush()
    for key, amount in (("gst", "115"), ("zero", "100")):
        db.add(
            XeroCreditNoteLine(
                org_id=org_id,
                credit_note_id=note.id,
                line_key=key,
                description="Wildflower Gin 700ml",
                quantity=Decimal("1"),
                line_amount=Decimal(amount),
                product_mapping_id=mapping.id,
            )
        )
    db.commit()
    return note


def _install_empty_incremental(monkeypatch):
    monkeypatch.setattr(xero_api_client_module.XeroAPIClient, "get_all_contacts", lambda self, **kw: [])
    monkeypatch.setattr(xero_api_client_module.XeroAPIClient, "get_all_invoices", lambda self, **kw: [])
    monkeypatch.setattr(
        xero_api_client_module.XeroAPIClient,
        "fetch_all_credit_notes",
        lambda self, **kw: [],
    )
    monkeypatch.setattr(XeroSyncService, "_run_purchases", lambda *args, **kwargs: None)


def _remote_note(note_id):
    return SimpleNamespace(
        credit_note_id=note_id,
        type="ACCRECCREDIT",
        status="AUTHORISED",
        sub_total=Decimal("200"),
        total_tax=Decimal("15"),
        updated_date_utc=datetime.now(UTC),
        line_items=[
            SimpleNamespace(line_item_id="gst", line_amount=Decimal("115"), tax_amount=Decimal("15")),
            SimpleNamespace(line_item_id="zero", line_amount=Decimal("100"), tax_amount=Decimal("0")),
        ],
    )


def test_incremental_sync_backfills_legacy_lines_and_margins_count_each_tax_rate(costing_world, db, monkeypatch):
    org = costing_world["org"]
    _connect(db, org.id)
    sale = costing_world["sell"]([("Wildflower Gin 700ml", 3, "300", "0")])
    batch = costing_world["lot"]("tax-backfill", unit_cost="5")
    costing_world["allocate"](sale, "l1", batch, 3)
    note = _note(db, org.id)
    assert _row(costing_world)["revenue"] is None
    _install_empty_incremental(monkeypatch)
    fetched = []
    monkeypatch.setattr(
        xero_api_client_module.XeroAPIClient,
        "fetch_credit_notes_by_ids",
        lambda self, ids: (fetched.append(list(ids)) or [_remote_note(note.xero_credit_note_id)]),
        raising=False,
    )

    result = XeroSyncService(db).incremental_sync(org.id, triggered_by="test")

    assert result.success
    assert fetched == [[note.xero_credit_note_id]]
    db.expire_all()
    stored = db.query(XeroCreditNote).filter(XeroCreditNote.org_id == org.id, XeroCreditNote.id == note.id).one()
    assert stored.raw_fields["line_tax_amounts"] == {"gst": "15", "zero": "0"}
    assert Decimal(_row(costing_world)["revenue"]) == Decimal("100")


@pytest.mark.parametrize("has_line_tax", [False, True])
def test_incremental_sync_only_fetches_notes_missing_line_tax(db, costing_world, monkeypatch, has_line_tax):
    org = costing_world["org"]
    _connect(db, org.id)
    note = _note(
        db,
        org.id,
        xero_id=f"cn-selective-{uuid4()}",
        raw_fields={"line_tax_amounts": {}} if has_line_tax else {"line_amounts": {"gst": "115"}},
    )
    _install_empty_incremental(monkeypatch)
    fetched = []
    monkeypatch.setattr(
        xero_api_client_module.XeroAPIClient,
        "fetch_credit_notes_by_ids",
        lambda self, ids: (fetched.append(list(ids)) or [_remote_note(note.xero_credit_note_id)]),
        raising=False,
    )

    assert XeroSyncService(db).incremental_sync(org.id, triggered_by="test").success

    assert fetched == ([] if has_line_tax else [[note.xero_credit_note_id]])


def test_second_incremental_sync_does_not_fetch_backfilled_note(db, costing_world, monkeypatch):
    org = costing_world["org"]
    _connect(db, org.id)
    note = _note(db, org.id)
    _install_empty_incremental(monkeypatch)
    fetch_count = 0

    def by_ids(self, ids):
        nonlocal fetch_count
        fetch_count += 1
        return [_remote_note(note.xero_credit_note_id)]

    monkeypatch.setattr(xero_api_client_module.XeroAPIClient, "fetch_credit_notes_by_ids", by_ids, raising=False)
    service = XeroSyncService(db)
    assert service.incremental_sync(org.id, triggered_by="test").success
    assert service.incremental_sync(org.id, triggered_by="test").success

    assert fetch_count == 1


def test_backfill_xero_error_keeps_sync_successful_and_raw_fields_unchanged(db, costing_world, monkeypatch):
    org = costing_world["org"]
    _connect(db, org.id)
    note = _note(db, org.id)
    original = dict(note.raw_fields)
    _install_empty_incremental(monkeypatch)

    def fail(self, ids):
        raise RuntimeError("Xero unavailable")

    monkeypatch.setattr(xero_api_client_module.XeroAPIClient, "fetch_credit_notes_by_ids", fail, raising=False)

    result = XeroSyncService(db).incremental_sync(org.id, triggered_by="test")

    assert result.success
    db.expire_all()
    stored = db.query(XeroCreditNote).filter(XeroCreditNote.org_id == org.id, XeroCreditNote.id == note.id).one()
    assert stored.raw_fields == original


def test_backfill_query_does_not_touch_another_org(db, costing_world, two_org_two_user, monkeypatch):
    org_a, org_b = costing_world["org"], two_org_two_user["org_b"]
    _connect(db, org_a.id)
    foreign = _note(db, org_b.id, xero_id=f"cn-foreign-{uuid4()}")
    _install_empty_incremental(monkeypatch)
    fetched = []
    monkeypatch.setattr(
        xero_api_client_module.XeroAPIClient,
        "fetch_credit_notes_by_ids",
        lambda self, ids: (fetched.append(list(ids)) or []),
        raising=False,
    )

    assert XeroSyncService(db).incremental_sync(org_a.id, triggered_by="test").success

    try:
        assert fetched == []
        db.expire_all()
        stored = (
            db.query(XeroCreditNote).filter(XeroCreditNote.org_id == org_b.id, XeroCreditNote.id == foreign.id).one()
        )
        assert "line_tax_amounts" not in stored.raw_fields
    finally:
        db.query(XeroCreditNoteLine).filter(XeroCreditNoteLine.org_id == org_b.id).delete(synchronize_session=False)
        db.query(XeroCreditNote).filter(XeroCreditNote.org_id == org_b.id).delete(synchronize_session=False)
        from app.features.crm.models.product_mapping import ProductMapping

        db.query(ProductMapping).filter(ProductMapping.org_id == org_b.id).delete(synchronize_session=False)
        db.commit()


def test_a_note_xero_no_longer_returns_is_not_fetched_on_every_sync(db):
    """Review: a legacy note Xero doesn't return gets an empty per-line snapshot, so the next
    sync's backfill skips it rather than asking Xero for it forever."""
    from app.features.crm.models.xero_credit_note import XeroCreditNote
    from app.features.crm.repositories.xero_credit_note_repo import XeroCreditNoteRepository
    from tests.costing_helpers import new_org, purge

    org = new_org(db, grant=False)
    try:
        note = XeroCreditNote(
            org_id=org.id,
            xero_credit_note_id="gone-1",
            xero_tenant_id="t1",
            number="CN-1",
            status="AUTHORISED",
            raw_fields={"sub_total": "100", "total_tax": "15"},
        )
        other_tenant = XeroCreditNote(
            org_id=org.id,
            xero_credit_note_id="old-1",
            xero_tenant_id="t0",
            number="CN-0",
            status="AUTHORISED",
            raw_fields={},
        )
        db.add_all([note, other_tenant])
        db.commit()
        repo = XeroCreditNoteRepository(db)
        assert [x for _, x in repo.missing_line_tax_snapshots(org.id, "t1")] == ["gone-1"], "this tenant only"
        assert repo.mark_line_tax_unavailable(org.id, [note.id]) == 1
        db.commit()
        assert repo.missing_line_tax_snapshots(org.id, "t1") == []
        db.refresh(note)
        assert note.raw_fields["line_tax_amounts"] == {} and note.raw_fields["total_tax"] == "15"
    finally:
        purge(db, org)


def test_the_backfill_request_uses_xeros_filter_grammar(monkeypatch):
    """Review r13: the real request, not a fake of the whole method: Guid() IDs, upper-case OR/AND,
    batches of 40, sales credit notes only."""
    from types import SimpleNamespace

    import xero_python.accounting as accounting

    from app.features.crm.services.xero_api_client import XeroAPIClient

    calls = []

    class FakeAccounting:
        def __init__(self, _client):
            pass

        def get_credit_notes(self, tenant_id, **kwargs):
            calls.append((tenant_id, kwargs))
            return SimpleNamespace(credit_notes=[])

    monkeypatch.setattr(accounting, "AccountingApi", FakeAccounting)
    client = XeroAPIClient.__new__(XeroAPIClient)
    client._xero_tenant_id = "tenant-1"
    client._get_api_client = lambda: object()
    client._call_with_retry = lambda fn, *a, **kw: fn(*a, **kw)
    ids = [f"00000000-0000-0000-0000-{i:012d}" for i in range(45)]
    client.fetch_credit_notes_by_ids(ids)

    assert [len(kw["where"].split(" OR ")) for _, kw in calls] == [40, 5]
    where = calls[0][1]["where"]
    assert where.startswith('Type=="ACCRECCREDIT" AND (CreditNoteID==Guid("00000000-0000-0000-0000-000000000000")')
    assert " or " not in where and " and " not in where and "guid(" not in where
    assert all(tenant == "tenant-1" and kw["page"] == 1 for tenant, kw in calls)
