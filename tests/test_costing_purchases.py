"""Live-cogs 8.1b: Xero purchases in (spec .agents/specs/live-cogs.md, "8.1b build contract").

Written before the implementation. Xero objects are real ``xero_python`` models, so attribute
names and enum shapes match what the SDK returns; the HTTP layer (``XeroAPIClient`` fetch
methods) is replaced per test.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from xero_python.accounting import (
    Account,
    AccountType,
    BankTransaction,
    Contact,
    CurrencyCode,
    LineAmountTypes,
    LineItem,
)

from tests.costing_helpers import D, new_org, purge, user_client
from tests.test_compliant_routes import flask_app  # noqa: F401 -- fixture re-export

API = "/api/core/costing"
FULL_SCOPES = (
    "openid profile email accounting.contacts accounting.invoices accounting.invoices.read "
    "accounting.banktransactions.read accounting.settings.read offline_access"
)

# --- Xero fixtures ---------------------------------------------------------------------------


def account(code, name, kind="DIRECTCOSTS", cls="EXPENSE", account_id=None):
    a = Account(code=code, name=name, account_id=account_id or str(uuid4()), type=AccountType(kind), status="ACTIVE")
    a._class = cls
    return a


ACCOUNTS = [
    account("310", "Purchases - Ingredients"),
    account("311", "Purchases - Packaging"),
    account("320", "Excise Duty"),
    account("330", "Direct Rent Costs"),
    account("331", "Freight, Postage & Courier"),
    account("429", "Office Expense", kind="EXPENSE"),
    account("090", "Business Bank Account", kind="BANK", cls="ASSET"),
]


def line(account_code, amount, *, tax="0", line_item_id=None, description="Supermarket shop", qty=None):
    return LineItem(
        line_item_id=line_item_id,
        description=description,
        quantity=float(qty) if qty is not None else None,
        account_code=account_code,
        line_amount=float(amount),
        tax_amount=float(tax),
    )


def txn(
    lines,
    *,
    kind="SPEND",
    status="AUTHORISED",
    txn_id=None,
    payee="Moore Wilson",
    on=date(2026, 11, 10),
    amounts="Inclusive",
    rate=None,
    currency="NZD",
):
    return BankTransaction(
        bank_transaction_id=txn_id or str(uuid4()),
        type=kind,
        status=status,
        contact=Contact(contact_id=str(uuid4()), name=payee),
        date=on,
        reference="card",
        currency_code=CurrencyCode(currency),
        currency_rate=rate,
        line_amount_types=LineAmountTypes(amounts),
        line_items=lines,
        is_reconciled=True,
        bank_account=Account(name="Business Bank Account"),
        updated_date_utc=datetime.now(UTC),
    )


class FakeXero:
    """Records what the sync asked for; returns what the test queued."""

    def __init__(self, accounts=ACCOUNTS):
        self.accounts = list(accounts)
        self.transactions = []
        self.calls = []
        self.fail_with = None

    def install(self, monkeypatch):
        from app.features.crm.services import xero_api_client as module

        fake = self

        def get_accounts(_self):
            fake.calls.append(("accounts", None))
            return fake.accounts

        def get_bank_transactions(_self, modified_after=None, from_date=None):
            fake.calls.append(("bank_transactions", {"modified_after": modified_after, "from_date": from_date}))
            if fake.fail_with:
                raise fake.fail_with
            return fake.transactions

        monkeypatch.setattr(module.XeroAPIClient, "get_all_contacts", lambda self, **kw: [])
        monkeypatch.setattr(module.XeroAPIClient, "get_all_invoices", lambda self, **kw: [])
        monkeypatch.setattr(module.XeroAPIClient, "fetch_all_credit_notes", lambda self, **kw: [])
        monkeypatch.setattr(module.XeroAPIClient, "get_accounts", get_accounts)
        monkeypatch.setattr(module.XeroAPIClient, "get_bank_transactions", get_bank_transactions)
        return self

    def bank_calls(self):
        return [c[1] for c in self.calls if c[0] == "bank_transactions"]


def connect(db, org_id, scopes=FULL_SCOPES):
    from app.features.crm.repositories.xero_token_repo import XeroTokenRepository
    from app.features.crm.services.xero_oauth_service import XeroOAuthService

    XeroOAuthService(db).store_tokens(
        org_id,
        {"access_token": "fake", "refresh_token": "fake", "expires_in": 1800, "scope": scopes},
        {"tenantId": f"tenant-{org_id}", "tenantName": "Fake", "tenantType": "ORGANISATION"},
    )
    token = XeroTokenRepository(db).get(org_id)
    token.expires_at = datetime.now(UTC) + timedelta(hours=1)
    db.commit()


def sync(db, org_id, full=True):
    from app.features.crm.services.xero_sync_service import XeroSyncService

    service = XeroSyncService(db)
    result = service.full_sync(org_id, triggered_by="test") if full else service.incremental_sync(org_id, "test")
    db.expire_all()
    return result


def last_job(db, org_id):
    from app.features.crm.models.xero_sync_job import XeroSyncJob

    db.expire_all()
    return db.query(XeroSyncJob).filter(XeroSyncJob.org_id == org_id).order_by(XeroSyncJob.started_at.desc()).first()


def documents(db, org_id):
    from app.features.costing.models import PurchaseDocument

    db.expire_all()
    return db.query(PurchaseDocument).filter(PurchaseDocument.org_id == org_id).all()


def live_lines(db, org_id, document_id=None):
    from app.features.costing.models import PurchaseLine

    db.expire_all()
    q = db.query(PurchaseLine).filter(PurchaseLine.org_id == org_id, PurchaseLine.superseded_at.is_(None))
    if document_id:
        q = q.filter(PurchaseLine.document_id == document_id)
    return q.order_by(PurchaseLine.position).all()


def all_lines(db, org_id):
    from app.features.costing.models import PurchaseLine

    db.expire_all()
    return db.query(PurchaseLine).filter(PurchaseLine.org_id == org_id).all()


@pytest.fixture
def world(db, monkeypatch):
    org = new_org(db)
    connect(db, org.id)
    fake = FakeXero().install(monkeypatch)
    yield org, fake
    purge(db, org)


# --- AC1–AC4 -----------------------------------------------------------------------------------


def test_ac1_spend_on_a_stock_account_is_stored_ex_gst(world, db):
    org, fake = world
    fake.transactions = [txn([line("310", "103.50", tax="13.50")])]
    result = sync(db, org.id)
    assert result.success, result.errors
    (doc,) = documents(db, org.id)
    (ln,) = live_lines(db, org.id)
    assert (doc.kind, doc.payee_name, doc.document_date, doc.status) == (
        "spend",
        "Moore Wilson",
        date(2026, 11, 10),
        "active",
    )
    assert D(str(ln.amount_ex_tax)) == D("90.0000") and D(str(ln.tax_amount)) == D("13.5000")
    assert (ln.treatment, ln.account_code, ln.account_name) == ("stock", "310", "Purchases - Ingredients")
    assert D(str(doc.total_ex_tax)) == D("90.0000")


def test_ac2_duty_overhead_and_expense_treatments(world, db):
    org, fake = world
    fake.transactions = [
        txn([line("320", "500")], payee="NZ Customs"),
        txn([line("330", "200")], payee="Landlord"),
        txn([line("429", "50")], payee="Warehouse Stationery"),
    ]
    sync(db, org.id)
    got = {ln.account_code: ln.treatment for ln in live_lines(db, org.id)}
    assert got == {"320": "duty", "330": "overhead", "429": "not_stock"}


def test_ac3_syncing_twice_leaves_one_document_and_one_line(world, db):
    org, fake = world
    t = txn([line("310", "103.50", tax="13.50")])
    fake.transactions = [t]
    sync(db, org.id)
    first = {ln.id for ln in live_lines(db, org.id)}
    sync(db, org.id)
    assert len(documents(db, org.id)) == 1
    assert {ln.id for ln in live_lines(db, org.id)} == first
    assert len(all_lines(db, org.id)) == 1


def test_ac4_receive_on_a_stock_account_is_a_negative_refund(world, db):
    org, fake = world
    fake.transactions = [txn([line("310", "23", tax="3")], kind="RECEIVE")]
    sync(db, org.id)
    (doc,) = documents(db, org.id)
    (ln,) = live_lines(db, org.id)
    assert doc.kind == "refund"
    assert D(str(ln.amount_ex_tax)) == D("-20.0000") and D(str(ln.tax_amount)) == D("-3.0000")
    assert D(str(doc.total_ex_tax)) == D("-20.0000")


# --- AC64: classification and what is stored ---------------------------------------------------


@pytest.mark.parametrize(
    ("acct", "expected"),
    [
        (account("500", "Excise Duty"), "duty"),
        (account("501", "Customs duty paid"), "duty"),
        (account("502", "Direct Wages & Salaries"), "overhead"),
        (account("503", "Direct Light Power & Heating Costs"), "overhead"),
        (account("504", "Freight/Courier Fee"), "overhead"),
        (account("505", "Direct Motor Vehicle Costs"), "overhead"),
        (account("506", "Purchases - Consumables"), "stock"),
        (account("507", "Raw materials"), "stock"),
        (account("508", "Advertising", kind="EXPENSE"), "not_stock"),
        (account("509", "Depreciation", kind="DEPRECIATN"), "not_stock"),
        (account("510", "Overheads", kind="OVERHEADS"), "not_stock"),
    ],
)
def test_ac64_account_defaults(db, monkeypatch, acct, expected):
    org = new_org(db)
    try:
        connect(db, org.id)
        fake = FakeXero(accounts=[acct]).install(monkeypatch)
        fake.transactions = [txn([line(acct.code, "10")])]
        sync(db, org.id)
        (ln,) = live_lines(db, org.id)
        assert ln.treatment == expected
    finally:
        purge(db, org)


def test_ac64_non_expense_unknown_accounts_and_other_types_are_not_stored(world, db):
    org, fake = world
    fake.transactions = [
        txn([line("090", "100")]),  # an asset account
        txn([line("999", "100")]),  # not in the chart of accounts
        txn([line("310", "100")], kind="SPEND-TRANSFER"),
        txn([line("310", "100")], kind="SPEND-OVERPAYMENT"),
        txn([line("310", "100")], kind="RECEIVE-PREPAYMENT"),
        txn([line("310", "100"), line("090", "5")]),  # mixed: only the expense line is kept
    ]
    result = sync(db, org.id)
    assert result.success, result.errors
    docs = documents(db, org.id)
    assert len(docs) == 1
    assert [ln.account_code for ln in live_lines(db, org.id)] == ["310"]


def test_accounts_cache_holds_class_type_and_default(world, db):
    from app.features.crm.models.xero_account import XeroAccount

    org, fake = world
    sync(db, org.id)
    rows = {a.code: a for a in db.query(XeroAccount).filter(XeroAccount.org_id == org.id)}
    assert rows["310"].account_class == "EXPENSE" and rows["310"].type == "DIRECTCOSTS"
    assert rows["310"].default_treatment == "stock" and rows["310"].treatment_override is None
    assert rows["090"].default_treatment is None, "non-expense accounts have no treatment"


# --- AC65–AC66: amounts ----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("amounts", "line_amount", "tax", "ex", "stored_tax"),
    [
        ("Inclusive", "103.50", "13.50", "90.0000", "13.5000"),
        ("Exclusive", "90", "13.50", "90.0000", "13.5000"),
        ("NoTax", "90", "0", "90.0000", "0.0000"),
    ],
)
def test_ac65_line_amount_types(world, db, amounts, line_amount, tax, ex, stored_tax):
    org, fake = world
    fake.transactions = [txn([line("310", line_amount, tax=tax)], amounts=amounts)]
    sync(db, org.id)
    (ln,) = live_lines(db, org.id)
    assert (D(str(ln.amount_ex_tax)), D(str(ln.tax_amount))) == (D(ex), D(stored_tax))


@pytest.mark.parametrize(
    ("rate", "expected", "fx_status"),
    [(0.75, "100.0000", "ok"), (None, "75.0000", "ok"), (1.0, "75.0000", "ok"), (0.0, None, "needs_rate")],
)
def test_ac66_currency_conversion(world, db, rate, expected, fx_status):
    org, fake = world
    fake.transactions = [txn([line("310", "75")], amounts="Exclusive", rate=rate, currency="AUD")]
    sync(db, org.id)
    (doc,) = documents(db, org.id)
    (ln,) = live_lines(db, org.id)
    assert doc.fx_status == fx_status
    assert (D(str(ln.amount_ex_tax)) if ln.amount_ex_tax is not None else None) == (D(expected) if expected else None)


def test_ac66_rounding_is_half_up_after_conversion(world, db):
    org, fake = world
    fake.transactions = [txn([line("310", "10.00")], amounts="Exclusive", rate=3.0, currency="AUD")]
    sync(db, org.id)
    (ln,) = live_lines(db, org.id)
    assert D(str(ln.amount_ex_tax)) == D("3.3333")


# --- AC67–AC69: identity and changes in Xero ----------------------------------------------------


def test_ac67_positional_lines_unchanged_resync_keeps_ids(world, db):
    org, fake = world
    tid = str(uuid4())
    fake.transactions = [txn([line("310", "10", description="A"), line("311", "20", description="B")], txn_id=tid)]
    sync(db, org.id)
    before = [(ln.id, ln.line_key) for ln in live_lines(db, org.id)]
    assert [k for _, k in before] == ["pos:1", "pos:2"]
    sync(db, org.id)
    assert [(ln.id, ln.line_key) for ln in live_lines(db, org.id)] == before


def test_ac67_reordered_positional_lines_supersede_instead_of_moving(world, db):
    org, fake = world
    tid = str(uuid4())
    fake.transactions = [txn([line("310", "10", description="A"), line("311", "20", description="B")], txn_id=tid)]
    sync(db, org.id)
    old = {ln.description: ln.id for ln in live_lines(db, org.id)}
    fake.transactions = [txn([line("311", "20", description="B"), line("310", "10", description="A")], txn_id=tid)]
    sync(db, org.id)
    new = live_lines(db, org.id)
    assert [(ln.line_key, ln.description) for ln in new] == [("pos:1", "B"), ("pos:2", "A")]
    assert not {ln.id for ln in new} & set(old.values()), "content never moves to another line's row"
    assert len(all_lines(db, org.id)) == 4


def test_ac67_inserted_positional_line(world, db):
    org, fake = world
    tid = str(uuid4())
    fake.transactions = [txn([line("310", "10", description="A"), line("311", "20", description="B")], txn_id=tid)]
    sync(db, org.id)
    a_id = live_lines(db, org.id)[0].id
    fake.transactions = [
        txn(
            [line("310", "10", description="A"), line("310", "5", description="X"), line("311", "20", description="B")],
            txn_id=tid,
        )
    ]
    sync(db, org.id)
    got = [(ln.line_key, ln.description) for ln in live_lines(db, org.id)]
    assert got == [("pos:1", "A"), ("pos:2", "X"), ("pos:3", "B")]
    assert live_lines(db, org.id)[0].id == a_id, "pos:1 unchanged keeps its row"


def test_ac68_line_item_id_updates_in_place(world, db):
    org, fake = world
    tid, lid = str(uuid4()), str(uuid4())
    fake.transactions = [txn([line("310", "103.50", tax="13.50", line_item_id=lid)], txn_id=tid)]
    sync(db, org.id)
    (first,) = live_lines(db, org.id)
    assert first.line_key == lid
    fake.transactions = [txn([line("310", "115", tax="15", line_item_id=lid)], txn_id=tid)]
    sync(db, org.id)
    (again,) = live_lines(db, org.id)
    assert again.id == first.id and D(str(again.amount_ex_tax)) == D("100.0000")
    assert len(all_lines(db, org.id)) == 1


def test_ac68_line_item_id_dropped_is_superseded(world, db):
    org, fake = world
    tid, keep, drop = str(uuid4()), str(uuid4()), str(uuid4())
    fake.transactions = [txn([line("310", "10", line_item_id=keep), line("311", "20", line_item_id=drop)], txn_id=tid)]
    sync(db, org.id)
    fake.transactions = [txn([line("310", "10", line_item_id=keep)], txn_id=tid)]
    sync(db, org.id)
    assert [ln.line_key for ln in live_lines(db, org.id)] == [keep]
    superseded = [ln for ln in all_lines(db, org.id) if ln.superseded_at is not None]
    assert [ln.line_key for ln in superseded] == [drop]


def test_ac69_deleted_in_xero_voids_the_document_and_keeps_lines(world, db):
    org, fake = world
    tid = str(uuid4())
    fake.transactions = [txn([line("310", "10")], txn_id=tid)]
    sync(db, org.id)
    fake.transactions = [txn([line("310", "10")], txn_id=tid, status="DELETED")]
    sync(db, org.id)
    (doc,) = documents(db, org.id)
    assert doc.status == "voided"
    assert len(live_lines(db, org.id)) == 1


def test_recoded_out_of_expense_supersedes_and_keeps_document(world, db):
    org, fake = world
    tid = str(uuid4())
    fake.transactions = [txn([line("310", "10")], txn_id=tid)]
    sync(db, org.id)
    fake.transactions = [txn([line("090", "10")], txn_id=tid)]
    sync(db, org.id)
    assert len(documents(db, org.id)) == 1
    assert live_lines(db, org.id) == []


# --- AC70: account overrides ---------------------------------------------------------------------


def test_ac70_account_override_persists_and_reclassifies(world, db, flask_app):  # noqa: F811
    org, fake = world
    admin = user_client(db, flask_app, org)
    fake.transactions = [txn([line("429", "50")])]
    sync(db, org.id)
    office = next(a for a in admin.get(f"{API}/accounts").get_json()["accounts"] if a["code"] == "429")
    assert (office["default_treatment"], office["treatment_override"], office["treatment"]) == (
        "not_stock",
        None,
        "not_stock",
    )
    assert office["live_lines"] == 1

    put = admin.put(f"{API}/accounts/{office['xero_account_id']}", json={"treatment": "stock"})
    assert put.status_code == 200, put.get_json()
    assert [ln.treatment for ln in live_lines(db, org.id)] == ["stock"], "re-classified at once"

    sync(db, org.id)  # the next accounts sync must not wipe it
    again = next(a for a in admin.get(f"{API}/accounts").get_json()["accounts"] if a["code"] == "429")
    assert again["treatment_override"] == "stock" and again["treatment"] == "stock"
    assert [ln.treatment for ln in live_lines(db, org.id)] == ["stock"]

    admin.put(f"{API}/accounts/{office['xero_account_id']}", json={"treatment": None})
    assert [ln.treatment for ln in live_lines(db, org.id)] == ["not_stock"]


def test_ac70_account_api_validation_permissions_and_isolation(world, db, flask_app):  # noqa: F811
    org, fake = world
    admin = user_client(db, flask_app, org)
    sync(db, org.id)
    office = next(a for a in admin.get(f"{API}/accounts").get_json()["accounts"] if a["code"] == "429")
    path = f"{API}/accounts/{office['xero_account_id']}"
    assert admin.put(path, json={"treatment": "gold"}).status_code == 400
    assert admin.put(path, json={}).status_code == 400
    viewer = user_client(db, flask_app, org, permissions=["costs.view"])
    assert viewer.get(f"{API}/accounts").status_code == 200
    assert viewer.put(path, json={"treatment": "stock"}).status_code == 403
    other = new_org(db)
    try:
        intruder = user_client(db, flask_app, other)
        assert intruder.put(path, json={"treatment": "stock"}).status_code == 404
        assert intruder.get(f"{API}/accounts").get_json()["accounts"] == []
    finally:
        purge(db, other)
    assert not any(a["code"] == "090" for a in admin.get(f"{API}/accounts").get_json()["accounts"]), (
        "only expense accounts are listed"
    )


# --- AC71: gating and failure ---------------------------------------------------------------------


def test_ac71_without_the_feature_no_purchases_call(db, monkeypatch):
    org = new_org(db, grant=False)
    try:
        connect(db, org.id)
        fake = FakeXero().install(monkeypatch)
        fake.transactions = [txn([line("310", "10")])]
        result = sync(db, org.id)
        assert result.success
        assert fake.bank_calls() == []
        job = last_job(db, org.id)
        assert job.purchases_status == "not_enabled" and job.purchases_synced == 0
        assert documents(db, org.id) == []
    finally:
        purge(db, org)


def test_ac71_missing_scopes_need_reconnect_without_breaking_sales(db, monkeypatch):
    org = new_org(db)
    try:
        connect(db, org.id, scopes="openid accounting.contacts accounting.invoices offline_access")
        fake = FakeXero().install(monkeypatch)
        result = sync(db, org.id)
        assert result.success, "a missing purchases scope is not a sync error"
        assert fake.bank_calls() == []
        job = last_job(db, org.id)
        assert job.status == "completed" and job.purchases_status == "needs_reconnect"
    finally:
        purge(db, org)


def test_ac71_insufficient_scope_from_xero_is_needs_reconnect(world, db):
    org, fake = world

    class InsufficientScopeError(Exception):
        status = 403
        body = '{"Type":"InsufficientScopeError"}'

    fake.fail_with = InsufficientScopeError("insufficient_scope")
    from app.features.crm.services import xero_api_client as module

    original = module._is_insufficient_scope
    try:
        module._is_insufficient_scope = lambda error: isinstance(error, InsufficientScopeError) or original(error)
        result = sync(db, org.id)
    finally:
        module._is_insufficient_scope = original
    assert result.success
    assert last_job(db, org.id).purchases_status == "needs_reconnect"


def test_ac71_purchases_failure_is_partial_and_keeps_the_cursor(world, db, monkeypatch):
    from app.features.costing.models import CostingSettings
    from app.features.crm.services import xero_api_client as module

    org, fake = world
    contact_calls = []

    def contacts(self, **kw):
        contact_calls.append(1)
        return []

    monkeypatch.setattr(module.XeroAPIClient, "get_all_contacts", contacts)
    fake.transactions = [txn([line("310", "10")])]
    sync(db, org.id)
    cursor = db.query(CostingSettings).filter(CostingSettings.org_id == org.id).one().purchases_cursor
    assert cursor is not None

    fake.fail_with = RuntimeError("Xero exploded")
    result = sync(db, org.id)
    assert not result.success and any("exploded" in e for e in result.errors)
    job = last_job(db, org.id)
    assert job.purchases_status == "failed"
    settings = db.query(CostingSettings).filter(CostingSettings.org_id == org.id).one()
    assert settings.purchases_cursor == cursor
    assert len(contact_calls) == 2, "sales phases still ran"


# --- AC72: start date and cursor -------------------------------------------------------------------


def test_ac72_first_sync_sets_start_date_and_later_syncs_use_the_cursor(world, db):
    from app.features.costing.models import CostingSettings
    from app.features.costing.purchase_sources import nz_today

    org, fake = world
    fake.transactions = [txn([line("310", "10")]), txn([line("311", "20")])]
    sync(db, org.id)
    settings = db.query(CostingSettings).filter(CostingSettings.org_id == org.id).one()
    assert settings.start_date == nz_today()
    (first,) = fake.bank_calls()
    assert first == {"modified_after": None, "from_date": settings.start_date}
    assert last_job(db, org.id).purchases_synced == 2

    sync(db, org.id, full=False)
    second = fake.bank_calls()[1]
    db.expire_all()
    cursor = db.query(CostingSettings).filter(CostingSettings.org_id == org.id).one().purchases_cursor
    assert second["from_date"] == settings.start_date
    assert second["modified_after"] is not None and second["modified_after"] <= cursor + timedelta(minutes=10)


def test_ac72_existing_start_date_is_kept(world, db):
    from app.features.costing.models import CostingSettings

    org, fake = world
    db.add(CostingSettings(org_id=org.id, use_last_known_price=True, start_date=date(2026, 4, 1)))
    db.commit()
    sync(db, org.id)
    assert fake.bank_calls()[0]["from_date"] == date(2026, 4, 1)


# --- AC73: tenancy -------------------------------------------------------------------------------------


def test_ac73_same_xero_ids_in_two_orgs_stay_separate(db, monkeypatch):
    a, b = new_org(db), new_org(db)
    try:
        for org in (a, b):
            connect(db, org.id)
        fake = FakeXero().install(monkeypatch)
        tid = str(uuid4())
        fake.transactions = [txn([line("310", "10")], txn_id=tid)]
        sync(db, a.id)
        fake.transactions = [txn([line("310", "99")], txn_id=tid)]
        sync(db, b.id)
        (doc_a,) = documents(db, a.id)
        (doc_b,) = documents(db, b.id)
        assert doc_a.id != doc_b.id
        assert D(str(live_lines(db, a.id)[0].amount_ex_tax)) != D(str(live_lines(db, b.id)[0].amount_ex_tax))
    finally:
        purge(db, a, b)


def test_scopes_include_purchases():
    from app.features.crm.services.xero_oauth_service import XERO_SCOPES

    assert "accounting.banktransactions.read" in XERO_SCOPES.split()
    assert "accounting.settings.read" in XERO_SCOPES.split()


def test_api_client_bank_transactions_filters_type_date_and_pages(monkeypatch):
    """The real fetch: SPEND/RECEIVE only, dated from the start date, every page."""
    from types import SimpleNamespace

    from app.features.crm.services.xero_api_client import XeroAPIClient

    pages = {1: [object()] * 100, 2: [object()] * 3}
    seen = []

    class FakeApi:
        def get_bank_transactions(self, tenant_id, **kwargs):
            seen.append(kwargs)
            return SimpleNamespace(bank_transactions=pages.get(kwargs["page"], []))

    client = XeroAPIClient.__new__(XeroAPIClient)
    client._xero_tenant_id = "t"
    monkeypatch.setattr(client, "_get_api_client", lambda: None, raising=False)
    monkeypatch.setattr(client, "_call_with_retry", lambda fn, *a, **k: fn(*a, **k), raising=False)
    monkeypatch.setattr("xero_python.accounting.AccountingApi", lambda _c: FakeApi())
    got = client.get_bank_transactions(modified_after=datetime(2026, 11, 1, tzinfo=UTC), from_date=date(2026, 11, 1))
    assert len(got) == 103 and [k["page"] for k in seen] == [1, 2]
    where = seen[0]["where"]
    assert 'Type=="SPEND"' in where and 'Type=="RECEIVE"' in where and "DateTime(2026,11,01)" in where.replace(" ", "")
    assert seen[0]["if_modified_since"] == datetime(2026, 11, 1, tzinfo=UTC)


def test_money_is_decimal_not_float_rounded(world, db):
    """0.1 + 0.2 style float noise must not leak into stored amounts."""
    org, fake = world
    fake.transactions = [txn([line("310", "0.30", tax="0.10"), line("311", "0.20", tax="0")])]
    sync(db, org.id)
    amounts = sorted(D(str(ln.amount_ex_tax)) for ln in live_lines(db, org.id))
    assert amounts == [Decimal("0.2000"), Decimal("0.2000")]
