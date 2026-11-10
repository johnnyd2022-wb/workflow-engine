"""Live-cogs 8.1b: Xero spending synced into purchase documents and lines.

Spec .agents/specs/live-cogs.md: "Deciding what is a stock purchase" (Layer 1), "When Xero
changes later" (line side), "Xero sync changes", AC1-AC4 and AC64-AC68, AC72-AC73. Written
before the implementation; the allocation side of "changes later" is 8.1c's, so those cases
assert the hooks 8.1c fills.
"""

from __future__ import annotations

import re
from datetime import date

import pytest

from tests.costing_helpers import new_org, purge, user_client
from tests.costing_purchase_helpers import (
    D,
    FakeXero,
    HookSpy,
    _connect,
    account,
    line,
    line_by_key,
    purchase_documents,
    purchase_lines,
    set_line,
    transaction,
)
from tests.test_compliant_routes import flask_app  # noqa: F401 -- fixture re-export

API = "/api/core/costing"


@pytest.fixture
def world(db, flask_app, monkeypatch):  # noqa: F811
    from types import SimpleNamespace

    org = new_org(db)
    _connect(db, org.id)
    yield SimpleNamespace(org=org, admin=user_client(db, flask_app, org), fake=FakeXero(monkeypatch))
    purge(db, org)


def tab(w, name, **params):
    query = "&".join(f"{k}={v}" for k, v in {"tab": name, **params}.items())
    response = w.admin.get(f"{API}/purchases?{query}")
    assert response.status_code == 200, response.get_json()
    return response.get_json()


def sync(w, db, *txns):
    w.fake.transactions = list(txns)
    result = w.fake.sync(db, w.org)
    assert result.success, result.errors
    return result


def keys(payload):
    return [item["line_key"] for item in payload["items"]]


# --- AC1-AC4: the basics --------------------------------------------------------------------


def test_ac1_stock_spend_appears_in_to_record_ex_gst(world, db):
    sync(world, db, transaction("txn-1", [line(amount="103.50", tax="13.50")], amount_types="Inclusive"))

    payload = tab(world, "to_record")

    assert len(payload["items"]) == 1
    item = payload["items"][0]
    assert item["payee_name"] == "Botanical Supplies Ltd"
    assert item["document_date"] == "2026-11-03"
    assert item["amount_ex_tax"] == "90.0000"
    assert item["tax_amount"] == "13.5000"
    assert item["state"] == "open"
    assert item["treatment"] == "stock"
    assert item["kind"] == "spend"
    assert item["account_code"] == "310" and item["account_name"] == "Purchases - Ingredients"
    assert item["description"] == "Juniper berries"


def test_ac2_duty_overhead_and_office_spend_is_stored_but_never_shown(world, db):
    sync(
        world,
        db,
        transaction("txn-duty", [line("320", "50.00", "0", line_id="D1")], amount_types="NoTax"),
        transaction("txn-rent", [line("330", "800.00", "0", line_id="R1")], amount_types="NoTax"),
        transaction("txn-office", [line("400", "23.00", "0", line_id="O1")], amount_types="NoTax"),
    )

    stored = {l.line_key: l for l in purchase_lines(db, world.org.id)}  # noqa: E741
    assert {k: v.treatment for k, v in stored.items()} == {"D1": "duty", "R1": "overhead", "O1": "not_stock"}
    for name in ("to_record", "recorded", "skipped", "not_stock"):
        assert tab(world, name)["items"] == [], name
    assert tab(world, "to_record")["counts"] == {"to_record": 0, "recorded": 0, "skipped": 0, "not_stock": 0}


def test_ac3_syncing_the_same_transaction_twice_leaves_one_document_and_one_line(world, db):
    txn = transaction("txn-1", [line(line_id="L1")])
    sync(world, db, txn)
    first = (purchase_documents(db, world.org.id)[0].id, purchase_lines(db, world.org.id)[0].id)

    sync(world, db, txn)

    docs, lines_ = purchase_documents(db, world.org.id), purchase_lines(db, world.org.id)
    assert len(docs) == 1 and len(lines_) == 1
    assert (docs[0].id, lines_[0].id) == first
    assert docs[0].source == "xero_bank" and docs[0].external_id == "txn-1"
    assert lines_[0].line_key == "L1" and lines_[0].review_reason is None


def test_ac4_receive_on_a_stock_account_is_a_negative_refund_card(world, db):
    sync(world, db, transaction("txn-r", [line(amount="20.00", tax="3.00")], type_="RECEIVE", amount_types="Exclusive"))

    item = tab(world, "to_record")["items"][0]

    assert item["kind"] == "refund"
    assert item["amount_ex_tax"] == "-20.0000"
    assert item["tax_amount"] == "-3.0000"
    doc = purchase_documents(db, world.org.id)[0]
    assert doc.kind == "refund" and doc.total_ex_tax == D("-20")


def test_a_receive_on_a_revenue_account_is_not_stored(world, db):
    world.fake.accounts.append(account("200", "Sales", "REVENUE", "REVENUE"))
    sync(world, db, transaction("txn-rev", [line("200", "50.00", "0")], type_="RECEIVE", amount_types="NoTax"))
    assert purchase_lines(db, world.org.id) == []


# --- line amount types (spec: LineAmountTypes) ---------------------------------------------


@pytest.mark.parametrize(
    ("amount_types", "amount", "tax", "expected_ex", "expected_tax"),
    [
        ("Exclusive", "90.00", "13.50", "90.0000", "13.5000"),
        ("Inclusive", "103.50", "13.50", "90.0000", "13.5000"),
        ("NoTax", "90.00", None, "90.0000", "0.0000"),
        ("Inclusive", "50.00", None, "50.0000", "0.0000"),  # no tax figure -> nothing to strip
    ],
)
def test_ac66_line_amount_types_give_ex_gst_amounts(world, db, amount_types, amount, tax, expected_ex, expected_tax):
    sync(world, db, transaction("txn-1", [line(amount=amount, tax=tax)], amount_types=amount_types))
    item = tab(world, "to_record")["items"][0]
    assert (item["amount_ex_tax"], item["tax_amount"]) == (expected_ex, expected_tax)


# --- AC67: which Xero entries are kept -----------------------------------------------------


def test_ac67_only_spend_and_receive_are_kept_and_deleted_ones_are_voided(world, db):
    sync(
        world,
        db,
        transaction("txn-ok", [line(line_id="A")]),
        transaction("txn-transfer", [line(line_id="B")], type_="SPEND-TRANSFER"),
        transaction("txn-overpay", [line(line_id="C")], type_="RECEIVE-OVERPAYMENT"),
        transaction("txn-del", [line(line_id="E")], status="DELETED"),
        transaction("txn-void", [line(line_id="F")], status="VOIDED"),
    )

    docs = {d.external_id: d for d in purchase_documents(db, world.org.id)}
    assert set(docs) == {"txn-ok", "txn-del", "txn-void"}
    assert docs["txn-ok"].status == "active"
    assert docs["txn-del"].status == "voided" and docs["txn-void"].status == "voided"
    assert keys(tab(world, "to_record")) == ["A"]


def test_ac67_lines_on_balance_sheet_or_unknown_accounts_are_not_stored(world, db):
    sync(
        world,
        db,
        transaction(
            "txn-mixed",
            [
                line("310", "10.00", "0", line_id="K"),
                line("610", "5.00", "0", line_id="P"),
                line("999", "7", "0", line_id="U"),
            ],
            amount_types="NoTax",
        ),
        transaction("txn-asset-only", [line("610", "5.00", "0", line_id="P2")], amount_types="NoTax"),
    )

    assert [l.line_key for l in purchase_lines(db, world.org.id)] == ["K"]  # noqa: E741
    assert [d.external_id for d in purchase_documents(db, world.org.id)] == ["txn-mixed"]


def test_the_payee_reference_and_dates_are_kept_on_the_document(world, db):
    sync(
        world,
        db,
        transaction("txn-1", [line()], payee="Kererū Botanicals", reference="Card 4411", day=date(2026, 10, 15)),
    )
    doc = purchase_documents(db, world.org.id)[0]
    assert (doc.payee_name, doc.xero_contact_id, doc.reference) == ("Kererū Botanicals", "contact-1", "Card 4411")
    assert doc.document_date == date(2026, 10, 15)
    assert (doc.currency_code, doc.currency_rate) == ("NZD", D("1"))
    assert doc.last_synced_at is not None


def test_a_spend_with_no_contact_is_stored_without_a_payee(world, db):
    sync(world, db, transaction("txn-1", [line()], payee=None))
    assert tab(world, "to_record")["items"][0]["payee_name"] is None


# --- AC65: foreign currency -----------------------------------------------------------------


def test_ac65_foreign_documents_convert_at_the_xero_rate_foreign_per_base(world, db):
    """Xero's CurrencyRate is units of the document's currency per one NZD: base = foreign / rate."""
    sync(
        world,
        db,
        transaction(
            "txn-usd",
            [line(amount="100.00", tax="15.00", unit_amount="10.00", quantity="10")],
            amount_types="Exclusive",
            currency="USD",
            rate="0.6",
        ),
    )

    item = tab(world, "to_record")["items"][0]
    assert item["amount_ex_tax"] == "166.6667"  # 100 / 0.6, half-up to 4 dp
    assert item["tax_amount"] == "25.0000"
    assert item["currency_code"] == "USD"
    doc = purchase_documents(db, world.org.id)[0]
    assert (doc.currency_code, doc.currency_rate) == ("USD", D("0.6"))
    assert doc.total_ex_tax == D("166.6667") and doc.total_tax == D("25")
    assert purchase_lines(db, world.org.id)[0].unit_amount == D("16.666667")


def test_ac65_foreign_refunds_stay_negative_and_base_currency_documents_are_untouched(world, db):
    sync(
        world,
        db,
        transaction(
            "txn-eur",
            [line(amount="50.00", tax="0", line_id="E")],
            type_="RECEIVE",
            amount_types="NoTax",
            currency="EUR",
            rate="0.5",
        ),
        transaction(
            "txn-nzd", [line(amount="42.00", tax="0", line_id="N")], amount_types="NoTax", currency="NZD", rate="1"
        ),
    )
    amounts = {i["line_key"]: i["amount_ex_tax"] for i in tab(world, "to_record")["items"]}
    assert amounts == {"E": "-100.0000", "N": "42.0000"}


def test_ac65_a_foreign_document_without_a_usable_rate_is_an_error_not_a_guess(world, db):
    world.fake.transactions = [
        transaction("txn-bad", [line(line_id="B")], currency="USD", rate=None),
        transaction("txn-zero", [line(line_id="Z")], currency="USD", rate=0),
        transaction("txn-good", [line(line_id="G")]),
    ]
    result = world.fake.sync(db, world.org)

    assert not result.success and len(result.errors) == 2
    assert all("exchange rate" in e.lower() for e in result.errors)
    assert [d.external_id for d in purchase_documents(db, world.org.id)] == ["txn-good"]
    assert result.purchases_synced == 1


# --- AC64: lines without a LineItemID -------------------------------------------------------


_POS_KEY = re.compile(r"^pos:(\d+):([0-9a-f]{8})$")


def test_ac64_a_line_without_an_id_is_keyed_by_position_and_content(world, db):
    sync(world, db, transaction("t", [line(line_id=None, description="Juniper  berries")]))
    key = purchase_lines(db, world.org.id)[0].line_key
    match = _POS_KEY.match(key)
    assert match and match.group(1) == "1"

    # whitespace and case in the description do not change the fingerprint
    sync(world, db, transaction("t", [line(line_id=None, description="  juniper berries ")]))
    assert [l.line_key for l in purchase_lines(db, world.org.id)] == [key]  # noqa: E741


def test_ac64_an_amount_edit_keeps_the_positional_key_and_updates_the_amount(world, db):
    sync(world, db, transaction("t", [line(line_id=None, amount="103.50", tax="13.50")]))
    key = purchase_lines(db, world.org.id)[0].line_key

    sync(world, db, transaction("t", [line(line_id=None, amount="115.00", tax="15.00")]))

    row = line_by_key(db, world.org.id, key)
    assert row.amount_ex_tax == D("100") and row.superseded_at is None


def test_ac64_an_inserted_or_reordered_line_supersedes_instead_of_moving(world, db):
    first = line(line_id=None, description="Juniper berries", amount="10", tax="0")
    second = line(line_id=None, description="Coriander seed", amount="20", tax="0")
    sync(world, db, transaction("t", [first, second], amount_types="NoTax"))
    old = {l.line_key: l.description for l in purchase_lines(db, world.org.id)}  # noqa: E741
    assert len(old) == 2

    # Xero now returns them swapped
    sync(world, db, transaction("t", [second, first], amount_types="NoTax"))

    rows = purchase_lines(db, world.org.id)
    assert len(rows) == 4
    live = [r for r in rows if r.superseded_at is None]
    gone = [r for r in rows if r.superseded_at is not None]
    assert {r.line_key for r in gone} == set(old)
    assert {r.description for r in live} == {"Juniper berries", "Coriander seed"}
    assert not {r.line_key for r in live} & set(old)
    assert sorted(i["line_key"] for i in tab(world, "to_record")["items"]) == sorted(r.line_key for r in live)


def test_ac64_a_changed_description_supersedes_and_a_returning_key_is_reinstated(world, db):
    sync(world, db, transaction("t", [line(line_id=None, description="Juniper berries")]))
    original = purchase_lines(db, world.org.id)[0].line_key
    sync(world, db, transaction("t", [line(line_id=None, description="Juniper (organic)")]))
    assert line_by_key(db, world.org.id, original).superseded_at is not None

    sync(world, db, transaction("t", [line(line_id=None, description="Juniper berries")]))

    assert line_by_key(db, world.org.id, original).superseded_at is None
    assert len(purchase_lines(db, world.org.id)) == 2  # the organic key stays, now superseded


def test_ac64_identical_lines_at_different_positions_are_distinct_cards(world, db):
    same = [line(line_id=None, description="Bottles", amount="5", tax="0") for _ in range(2)]
    sync(world, db, transaction("t", same, amount_types="NoTax"))
    rows = purchase_lines(db, world.org.id)
    assert len({r.line_key for r in rows}) == 2


def test_a_line_id_that_stops_coming_back_is_superseded(world, db):
    sync(world, db, transaction("t", [line(line_id="A"), line(line_id="B", description="Other")]))
    sync(world, db, transaction("t", [line(line_id="A")]))
    assert line_by_key(db, world.org.id, "B").superseded_at is not None
    assert line_by_key(db, world.org.id, "A").superseded_at is None
    assert keys(tab(world, "to_record")) == ["A"]


# --- AC68: account defaults -----------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "type_", "cls", "expected"),
    [
        ("Purchases - Ingredients", "DIRECTCOSTS", "EXPENSE", "stock"),
        ("Packaging", "DIRECTCOSTS", "EXPENSE", "stock"),
        ("Consumables", "DIRECTCOSTS", "EXPENSE", "stock"),
        ("Excise Duty", "DIRECTCOSTS", "EXPENSE", "duty"),
        ("Customs duties paid", "DIRECTCOSTS", "EXPENSE", "duty"),
        ("Direct Rent Costs", "DIRECTCOSTS", "EXPENSE", "overhead"),
        ("Direct Wages", "DIRECTCOSTS", "EXPENSE", "overhead"),
        ("Salaries", "DIRECTCOSTS", "EXPENSE", "overhead"),
        ("Power & Lighting", "DIRECTCOSTS", "EXPENSE", "overhead"),
        ("Heating", "DIRECTCOSTS", "EXPENSE", "overhead"),
        ("Fuel", "DIRECTCOSTS", "EXPENSE", "overhead"),
        ("Vehicle Running", "DIRECTCOSTS", "EXPENSE", "overhead"),
        ("Freight & Courier", "DIRECTCOSTS", "EXPENSE", "overhead"),
        ("Postage", "DIRECTCOSTS", "EXPENSE", "overhead"),
        ("Parent Company Purchases", "DIRECTCOSTS", "EXPENSE", "stock"),  # "rent" inside "Parent"
        ("Highlight Botanicals", "DIRECTCOSTS", "EXPENSE", "stock"),  # "light" inside "Highlight"
        ("Office Expense", "EXPENSE", "EXPENSE", "not_stock"),
        ("Marketing", "OVERHEADS", "EXPENSE", "not_stock"),
        ("Depreciation", "DEPRECIATN", "EXPENSE", "not_stock"),
        ("Excise Duty (admin)", "EXPENSE", "EXPENSE", "not_stock"),  # only DIRECTCOSTS accounts are special
        ("Prepayments", "CURRENT", "ASSET", None),
        ("Sales", "REVENUE", "REVENUE", None),
        ("GST", "CURRLIAB", "LIABILITY", None),
    ],
)
def test_ac68_account_defaults(name, type_, cls, expected):
    from app.features.costing.treatments import default_treatment

    assert default_treatment(type_, cls, name) == expected


def test_ac68_the_chart_of_accounts_is_cached_with_its_default_treatments(world, db):
    from app.features.crm.models.xero_account import XeroAccount

    sync(world, db)

    db.expire_all()
    rows = {a.code: a for a in db.query(XeroAccount).filter(XeroAccount.org_id == world.org.id)}
    assert set(rows) == {"310", "320", "330", "400", "610"}
    assert rows["310"].default_treatment == "stock" and rows["310"].account_class == "EXPENSE"
    assert rows["310"].type == "DIRECTCOSTS" and rows["310"].status == "ACTIVE"
    assert rows["310"].xero_account_id == "acct-310" and rows["310"].last_synced_at is not None
    assert rows["320"].default_treatment == "duty" and rows["610"].default_treatment is None

    world.fake.accounts = [account("310", "Purchases - Botanicals"), *world.fake.accounts[1:]]
    sync(world, db)
    db.expire_all()
    assert db.query(XeroAccount).filter(XeroAccount.org_id == world.org.id).count() == 5
    assert db.query(XeroAccount).filter(XeroAccount.org_id == world.org.id, XeroAccount.code == "310").one().name == (
        "Purchases - Botanicals"
    )


def test_ac68_a_changed_account_default_reclassifies_only_unrecorded_lines(world, db):
    sync(
        world,
        db,
        transaction("t1", [line(line_id="OPEN")]),
        transaction("t2", [line(line_id="DONE", description="Done")]),
        transaction("t3", [line(line_id="HAND", description="By hand")]),
    )
    set_line(db, world.org.id, "DONE", state="recorded")
    set_line(db, world.org.id, "HAND", treatment_override=True)

    # The owner renames the account in Xero, so it is now an overhead. No transaction changed,
    # so the next sync fetches none: the accounts sync alone has to reclassify.
    world.fake.accounts = [account("310", "Direct Freight"), *world.fake.accounts[1:]]
    sync(world, db)

    assert line_by_key(db, world.org.id, "OPEN").treatment == "overhead"
    assert line_by_key(db, world.org.id, "DONE").treatment == "stock"
    assert line_by_key(db, world.org.id, "HAND").treatment == "stock"


def test_a_line_whose_account_vanishes_from_the_chart_keeps_its_treatment(world, db):
    sync(world, db, transaction("t", [line(line_id="X")]))
    world.fake.accounts = [a for a in world.fake.accounts if a.code != "310"]

    sync(world, db, transaction("t", [line(line_id="X", amount="115.00", tax="15.00")]))
    sync(world, db)  # and a sync that only refreshes the chart changes nothing either

    row = line_by_key(db, world.org.id, "X")
    assert row.treatment == "stock" and row.amount_ex_tax == D("100")
    assert keys(tab(world, "to_record")) == ["X"]


def test_a_line_never_synced_before_uses_the_account_default(world, db):
    sync(world, db, transaction("t", [line(line_id="X")]))
    row = line_by_key(db, world.org.id, "X")
    assert row.treatment == "stock" and row.treatment_rule_id is None and row.treatment_override is False
    assert row.state == "open" and row.not_stock_amount == D("0")


# --- AC72: when Xero changes later (line side; allocations are 8.1c's hooks) ----------------


def edit_amount(amount, tax, *, line_id="L1", account_code="310"):
    return transaction("t", [line(account_code, amount, tax, line_id=line_id)])


def test_ac72_an_amount_change_on_an_unrecorded_line_just_updates_it(world, db, monkeypatch):
    spy = HookSpy(monkeypatch)
    sync(world, db, edit_amount("103.50", "13.50"))
    sync(world, db, edit_amount("113.85", "14.85"))

    row = line_by_key(db, world.org.id, "L1")
    assert row.amount_ex_tax == D("99") and row.tax_amount == D("14.85")
    assert row.review_reason is None and spy.calls == []
    assert purchase_documents(db, world.org.id)[0].total_ex_tax == D("99")


def test_ac72_an_amount_change_on_a_recorded_line_flags_a_review_and_calls_the_hook(world, db, monkeypatch):
    spy = HookSpy(monkeypatch)
    sync(world, db, edit_amount("103.50", "13.50"))
    set_line(db, world.org.id, "L1", state="recorded")

    sync(world, db, edit_amount("113.85", "14.85"))

    row = line_by_key(db, world.org.id, "L1")
    assert row.amount_ex_tax == D("99") and row.review_reason == "amount_changed"
    assert spy.names() == ["amount_changed"]
    assert spy.calls[0][2] == (D("90"),)  # the old amount, so 8.1c can rescale by new / old
    assert [i["line_key"] for i in tab(world, "to_record")["items"]] == ["L1"]
    assert tab(world, "recorded")["items"] == []


def test_ac72_the_not_stock_part_is_rescaled_with_the_line(world, db, monkeypatch):
    HookSpy(monkeypatch)
    sync(world, db, edit_amount("103.50", "13.50"))
    set_line(db, world.org.id, "L1", state="partly_recorded", not_stock_amount=D("30"))

    sync(world, db, edit_amount("113.85", "14.85"))

    assert line_by_key(db, world.org.id, "L1").not_stock_amount == D("33.0000")


def test_ac72_a_line_the_owner_said_is_all_not_stock_stays_all_not_stock(world, db, monkeypatch):
    HookSpy(monkeypatch)
    sync(world, db, edit_amount("103.50", "13.50"))
    set_line(
        db,
        world.org.id,
        "L1",
        state="not_stock",
        not_stock_amount=D("90"),
        treatment="not_stock",
        treatment_override=True,
    )

    sync(world, db, edit_amount("113.85", "14.85"))

    row = line_by_key(db, world.org.id, "L1")
    assert row.not_stock_amount == row.amount_ex_tax == D("99")
    assert row.review_reason == "amount_changed" and row.treatment == "not_stock"


def test_ac72_resyncing_the_same_change_does_not_flag_it_again(world, db, monkeypatch):
    spy = HookSpy(monkeypatch)
    sync(world, db, edit_amount("103.50", "13.50"))
    set_line(db, world.org.id, "L1", state="recorded")
    sync(world, db, edit_amount("113.85", "14.85"))
    set_line(db, world.org.id, "L1", review_reason=None)  # the owner pressed Keep

    sync(world, db, edit_amount("113.85", "14.85"))

    assert line_by_key(db, world.org.id, "L1").review_reason is None
    assert spy.names() == ["amount_changed"]


def test_ac72_recoding_an_unrecorded_line_off_stock_removes_it_from_the_page(world, db, monkeypatch):
    spy = HookSpy(monkeypatch)
    sync(world, db, edit_amount("103.50", "13.50"))

    sync(world, db, edit_amount("103.50", "13.50", account_code="400"))

    row = line_by_key(db, world.org.id, "L1")
    assert row.account_code == "400" and row.treatment == "not_stock" and row.review_reason is None
    assert tab(world, "to_record")["items"] == [] and spy.calls == []


def test_ac72_recoding_into_a_stock_account_makes_the_line_appear(world, db, monkeypatch):
    HookSpy(monkeypatch)
    sync(world, db, edit_amount("23.00", "0", account_code="400"))
    assert tab(world, "to_record")["items"] == []

    sync(world, db, edit_amount("23.00", "0", account_code="310"))

    assert keys(tab(world, "to_record")) == ["L1"]


def test_ac72_recoding_a_recorded_line_off_stock_keeps_it_under_recorded_with_a_review(world, db, monkeypatch):
    spy = HookSpy(monkeypatch)
    sync(world, db, edit_amount("103.50", "13.50"))
    set_line(db, world.org.id, "L1", state="recorded")

    sync(world, db, edit_amount("103.50", "13.50", account_code="400"))

    row = line_by_key(db, world.org.id, "L1")
    assert row.review_reason == "recoded" and row.treatment == "not_stock" and row.state == "recorded"
    assert spy.names() == ["recoded"] and spy.calls[0][2] == ("310",)
    assert keys(tab(world, "recorded")) == ["L1"] and tab(world, "to_record")["items"] == []

    sync(world, db, edit_amount("103.50", "13.50", account_code="310"))  # back where it was
    assert line_by_key(db, world.org.id, "L1").review_reason is None


def test_ac72_recoding_between_two_stock_accounts_is_not_a_review(world, db, monkeypatch):
    spy = HookSpy(monkeypatch)
    world.fake.accounts.append(account("311", "Purchases - Packaging"))
    sync(world, db, edit_amount("103.50", "13.50"))
    set_line(db, world.org.id, "L1", state="recorded")

    sync(world, db, edit_amount("103.50", "13.50", account_code="311"))

    row = line_by_key(db, world.org.id, "L1")
    assert row.account_code == "311" and row.account_name == "Purchases - Packaging"
    assert row.review_reason is None and spy.calls == []


def test_ac72_a_hand_decision_survives_a_recode(world, db, monkeypatch):
    HookSpy(monkeypatch)
    sync(world, db, edit_amount("23.00", "0", account_code="400"))
    set_line(db, world.org.id, "L1", treatment="stock", treatment_override=True)

    sync(world, db, edit_amount("23.00", "0", account_code="400"))

    assert line_by_key(db, world.org.id, "L1").treatment == "stock"


def test_ac72_amount_changed_outranks_recoded_when_both_arrive_together(world, db, monkeypatch):
    spy = HookSpy(monkeypatch)
    sync(world, db, edit_amount("103.50", "13.50"))
    set_line(db, world.org.id, "L1", state="recorded")

    sync(world, db, edit_amount("113.85", "14.85", account_code="400"))

    assert line_by_key(db, world.org.id, "L1").review_reason == "amount_changed"
    assert sorted(spy.names()) == ["amount_changed", "recoded"]


def test_ac72_deleting_an_unrecorded_transaction_removes_its_cards(world, db, monkeypatch):
    spy = HookSpy(monkeypatch)
    sync(world, db, edit_amount("103.50", "13.50"))

    deleted = edit_amount("103.50", "13.50")
    deleted.status = "DELETED"
    sync(world, db, deleted)

    assert purchase_documents(db, world.org.id)[0].status == "voided"
    assert line_by_key(db, world.org.id, "L1").review_reason is None
    assert tab(world, "to_record")["items"] == [] and spy.calls == []


def test_ac72_deleting_a_recorded_transaction_flags_it_for_review(world, db, monkeypatch):
    spy = HookSpy(monkeypatch)
    sync(world, db, edit_amount("103.50", "13.50"))
    set_line(db, world.org.id, "L1", state="recorded")

    deleted = edit_amount("103.50", "13.50")
    deleted.status = "DELETED"
    sync(world, db, deleted)

    row = line_by_key(db, world.org.id, "L1")
    assert row.review_reason == "deleted_in_xero" and row.amount_ex_tax == D("90")
    assert spy.names() == ["deleted"]
    assert keys(tab(world, "to_record")) == ["L1"]  # AC35: shows in To record with the reason
    assert tab(world, "to_record")["items"][0]["review_reason"] == "deleted_in_xero"

    sync(world, db, deleted)  # fetching it again changes nothing
    assert spy.names() == ["deleted"]


def test_ac72_a_vanished_line_is_treated_like_a_deleted_one(world, db, monkeypatch):
    spy = HookSpy(monkeypatch)
    sync(world, db, transaction("t", [line(line_id="A"), line(line_id="B", description="Other")]))
    set_line(db, world.org.id, "B", state="recorded")

    sync(world, db, transaction("t", [line(line_id="A")]))

    row = line_by_key(db, world.org.id, "B")
    assert row.superseded_at is not None and row.review_reason == "deleted_in_xero"
    assert spy.names() == ["deleted"]
    assert sorted(keys(tab(world, "to_record"))) == ["A", "B"]


def test_ac72_a_deleted_reason_is_not_overwritten_by_a_lower_one(world, db, monkeypatch):
    HookSpy(monkeypatch)
    sync(world, db, edit_amount("103.50", "13.50"))
    set_line(db, world.org.id, "L1", state="recorded", review_reason="deleted_in_xero")

    sync(world, db, edit_amount("113.85", "14.85"))

    assert line_by_key(db, world.org.id, "L1").review_reason == "deleted_in_xero"


def test_ac72_a_line_that_comes_back_is_reinstated(world, db, monkeypatch):
    spy = HookSpy(monkeypatch)
    sync(world, db, transaction("t", [line(line_id="A"), line(line_id="B", description="Other")]))
    set_line(db, world.org.id, "B", state="recorded")
    sync(world, db, transaction("t", [line(line_id="A")]))

    sync(world, db, transaction("t", [line(line_id="A"), line(line_id="B", description="Other")]))

    row = line_by_key(db, world.org.id, "B")
    assert row.superseded_at is None and row.review_reason is None
    assert spy.names() == ["deleted", "reinstated"]


# --- AC73: the list ---------------------------------------------------------------------------


def test_ac73_tabs_hold_the_right_lines_and_counts(world, db, monkeypatch):
    HookSpy(monkeypatch)
    sync(
        world,
        db,
        *[
            transaction(f"t-{k}", [line(line_id=k, description=k, amount="10", tax="0")], amount_types="NoTax")
            for k in "OPRSN"
        ],
    )
    set_line(db, world.org.id, "P", state="partly_recorded")
    set_line(db, world.org.id, "R", state="recorded")
    set_line(db, world.org.id, "S", state="skipped")
    set_line(
        db,
        world.org.id,
        "N",
        state="not_stock",
        not_stock_amount=D("10"),
        treatment="not_stock",
        treatment_override=True,
    )

    assert sorted(keys(tab(world, "to_record"))) == ["O", "P"]
    assert keys(tab(world, "recorded")) == ["R"]
    assert keys(tab(world, "skipped")) == ["S"]
    assert keys(tab(world, "not_stock")) == ["N"]
    assert tab(world, "recorded")["counts"] == {"to_record": 2, "recorded": 1, "skipped": 1, "not_stock": 1}


def test_ac73_the_date_filter_applies_to_every_tab_and_is_inclusive(world, db):
    sync(
        world,
        db,
        transaction("a", [line(line_id="A")], day=date(2026, 10, 31)),
        transaction("b", [line(line_id="B")], day=date(2026, 11, 1)),
        transaction("c", [line(line_id="C")], day=date(2026, 11, 30)),
        transaction("d", [line(line_id="D")], day=date(2026, 12, 1)),
    )

    payload = tab(world, "to_record", **{"from": "2026-11-01", "to": "2026-11-30"})

    assert sorted(keys(payload)) == ["B", "C"]
    assert payload["counts"]["to_record"] == 2
    assert [i["document_date"] for i in payload["items"]] == ["2026-11-30", "2026-11-01"]  # newest first


def test_ac73_the_list_pages(world, db):
    sync(world, db, *[transaction(f"t{n}", [line(line_id=f"K{n}")], day=date(2026, 11, n + 1)) for n in range(5)])

    first = tab(world, "to_record", limit=2, offset=0)
    second = tab(world, "to_record", limit=2, offset=2)

    assert len(first["items"]) == 2 and len(second["items"]) == 2
    assert not {i["id"] for i in first["items"]} & {i["id"] for i in second["items"]}
    assert first["total"] == 5 and first["counts"]["to_record"] == 5


@pytest.mark.parametrize(
    "query",
    [
        "tab=nonsense",
        "tab=to_record&from=yesterday",
        "tab=to_record&to=2026-13-40",
        "tab=to_record&limit=0",
        "tab=to_record&limit=x",
        "tab=to_record&offset=-1",
    ],
)
def test_ac73_bad_parameters_are_400(world, query):
    assert world.admin.get(f"{API}/purchases?{query}").status_code == 400


def test_ac73_the_default_tab_is_to_record(world, db):
    sync(world, db, transaction("t", [line()]))
    response = world.admin.get(f"{API}/purchases")
    assert response.status_code == 200 and response.get_json()["tab"] == "to_record"
    assert len(response.get_json()["items"]) == 1
