"""Shared setup for the live-cogs 8.1b (Xero purchases in) tests.

Spec: .agents/specs/live-cogs.md. A ``FakeXero`` stands in for ``XeroAPIClient.get_accounts`` /
``get_bank_transactions`` and records how it was called; the builders produce the same attribute
shape the xero-python SDK models have (``_class`` for an account's class, ``line_item_id`` ...).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from types import SimpleNamespace

from app.features.crm.services.xero_api_client import XeroAPIClient
from app.features.crm.services.xero_sync_service import XeroSyncService
from tests.test_crm_contact_sync import _connect  # noqa: F401 -- re-export for the tests

D = Decimal

STOCK_ACCOUNT = ("310", "Purchases - Ingredients", "DIRECTCOSTS", "EXPENSE")
DUTY_ACCOUNT = ("320", "Excise Duty", "DIRECTCOSTS", "EXPENSE")
OVERHEAD_ACCOUNT = ("330", "Direct Rent Costs", "DIRECTCOSTS", "EXPENSE")
OFFICE_ACCOUNT = ("400", "Office Expense", "EXPENSE", "EXPENSE")
ASSET_ACCOUNT = ("610", "Prepayments", "CURRENT", "ASSET")


def account(code, name, type_="DIRECTCOSTS", cls="EXPENSE", status="ACTIVE"):
    return SimpleNamespace(
        account_id=f"acct-{code}", code=code, name=name, type=type_, _class=cls, status=status, tax_type="INPUT2"
    )


def default_accounts():
    return [account(*row) for row in (STOCK_ACCOUNT, DUTY_ACCOUNT, OVERHEAD_ACCOUNT, OFFICE_ACCOUNT, ASSET_ACCOUNT)]


def line(
    account_code="310",
    amount="103.50",
    tax="13.50",
    *,
    line_id="L1",
    description="Juniper berries",
    item_code=None,
    quantity=None,
    unit_amount=None,
):
    return SimpleNamespace(
        line_item_id=line_id,
        description=description,
        item_code=item_code,
        quantity=None if quantity is None else D(str(quantity)),
        unit_amount=None if unit_amount is None else D(str(unit_amount)),
        line_amount=D(str(amount)),
        account_code=account_code,
        tax_amount=None if tax is None else D(str(tax)),
        tax_type="INPUT2",
    )


def transaction(
    txn_id,
    lines=None,
    *,
    type_="SPEND",
    status="AUTHORISED",
    payee="Botanical Supplies Ltd",
    contact_id="contact-1",
    day=date(2026, 11, 3),
    amount_types="Inclusive",
    currency=None,
    rate=None,
    reference="INV-77",
):
    lines = [line()] if lines is None else lines
    inclusive = str(amount_types).lower() == "inclusive"
    sub_total = sum((x.line_amount - (x.tax_amount or 0)) if inclusive else x.line_amount for x in lines)
    total_tax = sum((x.tax_amount or 0) for x in lines)
    return SimpleNamespace(
        bank_transaction_id=txn_id,
        type=type_,
        status=status,
        contact=None if payee is None else SimpleNamespace(contact_id=contact_id, name=payee),
        date=day,
        reference=reference,
        currency_code=currency,
        currency_rate=rate,
        line_amount_types=amount_types,
        line_items=lines,
        sub_total=D(str(sub_total)),
        total_tax=D(str(total_tax)),
        total=D(str(sub_total + total_tax)),
        updated_date_utc=None,
    )


class FakeXero:
    """Scripted ``XeroAPIClient`` purchases surface. ``calls`` records every fetch."""

    def __init__(self, monkeypatch, accounts=None, transactions=None):
        self.accounts = default_accounts() if accounts is None else accounts
        self.transactions = [] if transactions is None else transactions
        self.calls: list[dict] = []
        self.fail_transactions: Exception | None = None
        self.fail_accounts: Exception | None = None
        fake = self

        def get_accounts(client):
            fake.calls.append({"what": "accounts"})
            if fake.fail_accounts:
                raise fake.fail_accounts
            return list(fake.accounts)

        def get_bank_transactions(client, modified_after=None, date_from=None, date_to=None):
            fake.calls.append(
                {"what": "transactions", "modified_after": modified_after, "date_from": date_from, "date_to": date_to}
            )
            if fake.fail_transactions:
                raise fake.fail_transactions
            return list(fake.transactions)

        monkeypatch.setattr(XeroAPIClient, "get_accounts", get_accounts)
        monkeypatch.setattr(XeroAPIClient, "get_bank_transactions", get_bank_transactions)

    def transaction_calls(self):
        return [c for c in self.calls if c["what"] == "transactions"]

    def sync(self, db, org, **kwargs):
        """A standalone purchases sync job (accounts, then bank transactions)."""
        return XeroSyncService(db).purchases_sync(org.id, triggered_by="test", **kwargs)


def silence_sales_sync(monkeypatch):
    """The sales half of full / incremental syncs returns nothing."""
    monkeypatch.setattr(XeroAPIClient, "get_all_contacts", lambda self, **kw: [])
    monkeypatch.setattr(XeroAPIClient, "get_all_invoices", lambda self, **kw: [])
    monkeypatch.setattr(XeroAPIClient, "fetch_all_credit_notes", lambda self, **kw: [])


def purchase_lines(db, org_id):
    from app.features.costing.purchase_models import PurchaseLine

    db.expire_all()
    return (
        db.query(PurchaseLine)
        .filter(PurchaseLine.org_id == org_id)
        .order_by(PurchaseLine.created_at, PurchaseLine.line_key)
        .all()
    )


def purchase_documents(db, org_id):
    from app.features.costing.purchase_models import PurchaseDocument

    db.expire_all()
    return db.query(PurchaseDocument).filter(PurchaseDocument.org_id == org_id).all()


def line_by_key(db, org_id, line_key):
    rows = [row for row in purchase_lines(db, org_id) if row.line_key == line_key]
    assert len(rows) == 1, (line_key, [row.line_key for row in purchase_lines(db, org_id)])
    return rows[0]


def set_line(db, org_id, line_key, **values):
    """Put a line in a state only the 8.1c actions can reach, directly in the database."""
    row = line_by_key(db, org_id, line_key)
    for key, value in values.items():
        setattr(row, key, value)
    db.commit()
    return row


class HookSpy:
    """Records the 8.1c hook calls the sync makes when Xero changes a line later."""

    def __init__(self, monkeypatch):
        from app.features.costing import purchase_sources

        self.calls: list[tuple] = []
        for name in ("amount_changed", "recoded", "deleted", "reinstated"):
            monkeypatch.setattr(
                purchase_sources.hooks, name, lambda *a, _name=name, **k: self.calls.append((_name, a[2], a[3:]))
            )

    def names(self):
        return [c[0] for c in self.calls]
