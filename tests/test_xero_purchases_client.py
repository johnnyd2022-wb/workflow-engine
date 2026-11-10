"""Live-cogs 8.1b: the Xero client's chart-of-accounts and bank-transaction fetches, and the scopes.

Spec .agents/specs/live-cogs.md, "Xero sync changes" (AC69-AC70). Scripted ``AccountingApi``
fakes, as in ``tests/test_xero_api_client.py``; nothing touches the network or the database.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from types import SimpleNamespace

import pytest

from app.features.crm.services.xero_api_client import XeroInsufficientScopeError
from app.features.crm.services.xero_oauth_service import XERO_SCOPES
from tests.test_xero_api_client import TENANT_ID, XeroHTTPError, fake_api, sleeps, xero  # noqa: F401 -- fixtures


def txn(txn_id, type_="SPEND", status="AUTHORISED"):
    return SimpleNamespace(bank_transaction_id=txn_id, type=type_, status=status)


def page(*rows):
    return SimpleNamespace(bank_transactions=list(rows))


# --- AC69: scopes -----------------------------------------------------------------------------


def test_ac69_the_connection_asks_for_the_bank_transaction_and_settings_scopes():
    scopes = XERO_SCOPES.split()
    assert "accounting.banktransactions.read" in scopes and "accounting.settings.read" in scopes
    assert {"openid", "accounting.contacts", "accounting.invoices", "offline_access"} <= set(scopes)
    assert len(scopes) == len(set(scopes))


# --- AC70: accounts ---------------------------------------------------------------------------


def test_ac70_get_accounts_returns_the_whole_chart(xero, fake_api):  # noqa: F811
    install, calls = fake_api
    rows = [SimpleNamespace(code="310"), SimpleNamespace(code="320")]
    install(get_accounts=SimpleNamespace(accounts=rows))

    assert xero.get_accounts() == rows
    assert calls[0][0] == "get_accounts" and calls[0][1][0] == TENANT_ID


def test_ac70_get_accounts_with_no_accounts_is_an_empty_list(xero, fake_api):  # noqa: F811
    install, _ = fake_api
    install(get_accounts=SimpleNamespace(accounts=None))
    assert xero.get_accounts() == []


# --- AC70: bank transactions --------------------------------------------------------------------


def test_ac70_spend_and_receive_are_fetched_as_two_filtered_queries(xero, fake_api):  # noqa: F811
    install, calls = fake_api
    install(
        get_bank_transactions=lambda tenant, **kw: page(
            txn("s1", "SPEND") if kw["where"] == 'Type=="SPEND"' else txn("r1", "RECEIVE")
        )
    )

    got = xero.get_bank_transactions()

    assert [t.bank_transaction_id for t in got] == ["s1", "r1"]
    assert [c[2]["where"] for c in calls] == ['Type=="SPEND"', 'Type=="RECEIVE"']
    assert all("if_modified_since" not in c[2] for c in calls)


def test_ac70_pages_are_followed_until_a_short_page(xero, fake_api):  # noqa: F811
    install, calls = fake_api
    pages = {
        ('Type=="SPEND"', 1): page(*[txn(f"s{n}") for n in range(100)]),
        ('Type=="SPEND"', 2): page(txn("s-last")),
        ('Type=="RECEIVE"', 1): page(),
    }
    install(get_bank_transactions=lambda tenant, **kw: pages[(kw["where"], kw["page"])])

    got = xero.get_bank_transactions()

    assert len(got) == 101 and got[-1].bank_transaction_id == "s-last"
    assert [(c[2]["where"], c[2]["page"]) for c in calls] == [
        ('Type=="SPEND"', 1),
        ('Type=="SPEND"', 2),
        ('Type=="RECEIVE"', 1),
    ]


def test_ac70_modified_since_is_sent_as_an_aware_datetime(xero, fake_api):  # noqa: F811
    install, calls = fake_api
    install(get_bank_transactions=page())

    xero.get_bank_transactions(modified_after=datetime(2026, 11, 1, 8, 30))

    assert {c[2]["if_modified_since"] for c in calls} == {datetime(2026, 11, 1, 8, 30, tzinfo=UTC)}


def test_ac70_a_date_range_filters_by_transaction_date_not_modified_date(xero, fake_api):  # noqa: F811
    install, calls = fake_api
    install(get_bank_transactions=page())

    xero.get_bank_transactions(date_from=date(2026, 10, 1), date_to=date(2026, 10, 31))

    wheres = [c[2]["where"] for c in calls]
    assert wheres == [
        'Type=="SPEND" AND Date>=DateTime(2026, 10, 1) AND Date<=DateTime(2026, 10, 31)',
        'Type=="RECEIVE" AND Date>=DateTime(2026, 10, 1) AND Date<=DateTime(2026, 10, 31)',
    ]
    assert all("if_modified_since" not in c[2] for c in calls)


def test_ac70_one_end_of_a_range_is_enough(xero, fake_api):  # noqa: F811
    install, calls = fake_api
    install(get_bank_transactions=page())

    xero.get_bank_transactions(date_from=date(2026, 10, 1))

    assert calls[0][2]["where"] == 'Type=="SPEND" AND Date>=DateTime(2026, 10, 1)'


def test_ac70_deleted_transactions_are_returned_and_other_types_are_not(xero, fake_api):  # noqa: F811
    install, _ = fake_api
    install(
        get_bank_transactions=page(
            txn("ok"), txn("gone", status="DELETED"), txn("xfer", "SPEND-TRANSFER"), txn("pre", "RECEIVE-PREPAYMENT")
        )
    )

    got = xero.get_bank_transactions()

    assert sorted({t.bank_transaction_id for t in got}) == ["gone", "ok"]
    assert any(t.status == "DELETED" for t in got)


def test_ac70_a_missing_scope_is_reported_as_one(xero, fake_api):  # noqa: F811
    install, _ = fake_api
    install(get_bank_transactions=XeroHTTPError(403, "insufficient_scope"))
    with pytest.raises(XeroInsufficientScopeError):
        xero.get_bank_transactions()


def test_ac70_a_rate_limit_is_retried_like_the_other_calls(xero, fake_api, sleeps):  # noqa: F811
    install, calls = fake_api
    install(get_bank_transactions=[XeroHTTPError(429), page(txn("ok")), page()])

    assert [t.bank_transaction_id for t in xero.get_bank_transactions()] == ["ok"]
    assert sleeps  # backed off once
