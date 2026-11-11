"""Live-cogs 8.1c-2: purchase rules, pre-fill, remember, bulk, historical runs.

Spec .agents/specs/live-cogs.md, "8.1c-2 build contract". Written before the implementation.
Purchases come in through the real 8.1b sync (FakeXero); actions go through the HTTP API.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest

from app.features.costing.models import CostingSettings, PurchaseLine
from tests.costing_helpers import lot_cost, new_org, purge, user_client
from tests.test_compliant_routes import flask_app  # noqa: F401 -- fixture re-export
from tests.test_costing_allocations import (  # noqa: F401 -- fixture re-export
    PURCHASE_DATE,
    _assert_success,
    _record,
    _row,
    _set_start_date,
    world,
)
from tests.test_costing_purchases import line, sync, txn

API = "/api/core/costing"
D = Decimal


def _key():
    return {"Idempotency-Key": str(uuid4())}


def _purchase(
    w, db, amount, *, payee="Botanical Supply Co", account_code="310", description="Shop", on=PURCHASE_DATE
):
    """Sync one purchase (keeping earlier ones) and return its line id."""
    _set_start_date(db, w["org"].id)
    t = txn(
        [line(account_code, amount, line_item_id=str(uuid4()), description=description)],
        payee=payee,
        on=on,
        amounts="NoTax",
    )
    w.setdefault("all", []).append(t)
    w["fake"].transactions = list(w["all"])
    assert sync(db, w["org"].id).success
    db.expire_all()
    row = (
        db.query(PurchaseLine)
        .filter(PurchaseLine.org_id == w["org"].id, PurchaseLine.line_key == t.line_items[0].line_item_id)
        .one()
    )
    return row.id


def _card(client, line_id, tab="to_record", **params):
    query = "&".join(f"{k}={v}" for k, v in {"tab": tab, **params}.items())
    body = client.get(f"{API}/purchases?{query}").get_json()
    return next((c for c in body["cards"] if c["line_id"] == str(line_id)), None)


def _rule(client, **body):
    body.setdefault("match_type", "exact")
    body.setdefault("treatment", "stock")
    return client.post(f"{API}/rules", json=body)


def _treatment(db, line_id):
    db.expire_all()
    return db.get(PurchaseLine, line_id).treatment


# --- AC14 / AC83: pre-fill ------------------------------------------------------------------------


def test_ac14_rule_template_prefills_and_records(flask_app, world, db):  # noqa: F811
    client = user_client(db, flask_app, world["org"])
    made = _rule(
        client,
        payee_pattern="Spirits Co",
        match_type="contains",
        template=[
            {
                "name": "Neutral Spirit",
                "inventory_type": "raw_material",
                "unit": "L",
                "quantity_mode": "fixed",
                "quantity": "20",
                "share": "rest",
                "ask_batch_number": True,
            }
        ],
    )
    assert made.status_code == 201, made.get_json()
    line_id = _purchase(world, db, "400", payee="Spirits Co Ltd")
    card = _card(client, line_id)
    assert card["prefill"]["source"] == "rule"
    (row,) = card["prefill"]["rows"]
    assert (row["name"], D(row["quantity"]), D(row["amount"]), row["ask"]) == (
        "Neutral Spirit",
        D("20"),
        D("400"),
        ["batch_number"],
    )
    rec = _record(client, line_id, [_row("Neutral Spirit", 20, 400, unit="L", supplier_batch_number="NS-1")])
    _assert_success(rec)
    item_id = rec.get_json()["allocations"][0]["inventory_item_id"]
    assert D(lot_cost(db, world["org"].id, item_id)["unit_cost"]) == D("20")


def test_ac83_prefill_from_price_rest_never_negative_last_time_and_none(flask_app, world, db):  # noqa: F811
    client = user_client(db, flask_app, world["org"])
    _rule(
        client,
        payee_pattern="Glass Co",
        template=[
            {
                "name": "Bottle",
                "inventory_type": "raw_material",
                "unit": "units",
                "quantity_mode": "from_price",
                "unit_price": "2.5",
                "share": "80",
            },
            {"name": "Cap", "inventory_type": "raw_material", "unit": "units", "quantity_mode": "ask", "share": "rest"},
        ],
    )
    glass = _card(client, _purchase(world, db, "100", payee="Glass Co"))
    rows = {r["name"]: r for r in glass["prefill"]["rows"]}
    assert D(rows["Bottle"]["amount"]) == D("80") and D(rows["Bottle"]["quantity"]) == D("32")
    assert D(rows["Cap"]["amount"]) == D("20") and rows["Cap"]["quantity"] is None and "quantity" in rows["Cap"]["ask"]

    # last time: a payee with no rule but an earlier recording
    first = _purchase(world, db, "100", payee="Herb Farm")
    _assert_success(_record(client, first, [_row("Thyme", 2, 60), _row("Sage", 1, 40)]))
    second = _card(client, _purchase(world, db, "50", payee="Herb Farm"))
    assert second["prefill"]["source"] == "last_time"
    assert {r["name"]: D(r["amount"]) for r in second["prefill"]["rows"]} == {"Thyme": D("30"), "Sage": D("20")}

    nothing = _card(client, _purchase(world, db, "75", payee="Somewhere New"))
    assert nothing["prefill"]["source"] == "none"
    assert [D(r["amount"]) for r in nothing["prefill"]["rows"]] == [D("75")]


def test_ac83_rest_row_takes_the_remainder_after_rounding(flask_app, world, db):  # noqa: F811
    client = user_client(db, flask_app, world["org"])
    _rule(
        client,
        payee_pattern="Third Co",
        template=[
            {"name": n, "inventory_type": "raw_material", "unit": "kg", "quantity_mode": "ask", "share": s}
            for n, s in (("A", "33.3333"), ("B", "33.3333"), ("C", "rest"))
        ],
    )
    rows = _card(client, _purchase(world, db, "10", payee="Third Co"))["prefill"]["rows"]
    amounts = [D(r["amount"]) for r in rows]
    assert sum(amounts) == D("10") and all(a >= 0 for a in amounts)


# --- AC15 / AC81: precedence ----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("rules", "expected"),
    [
        # payee + account beats payee only
        (
            [
                dict(payee_pattern="Moore Wilson", account_code="429", treatment="stock"),
                dict(payee_pattern="Moore Wilson", treatment="overhead"),
            ],
            "stock",
        ),
        # payee only beats account only
        (
            [dict(payee_pattern="Moore Wilson", treatment="stock"), dict(account_code="429", treatment="overhead")],
            "stock",
        ),
        # account only beats the account default (429 Office Expense = not_stock)
        ([dict(account_code="429", treatment="stock")], "stock"),
        # same number of matchers: exact beats contains
        (
            [
                dict(payee_pattern="moore", match_type="contains", treatment="overhead"),
                dict(payee_pattern="Moore Wilson", treatment="stock"),
            ],
            "stock",
        ),
        # same count and type: payee beats description-only
        (
            [
                dict(description_pattern="weekly shop", treatment="overhead"),
                dict(payee_pattern="Moore Wilson", treatment="stock"),
            ],
            "stock",
        ),
    ],
)
def test_ac15_ac81_rule_precedence(flask_app, world, db, rules, expected):  # noqa: F811
    client = user_client(db, flask_app, world["org"])
    for body in rules:
        assert _rule(client, **body).status_code == 201
    line_id = _purchase(world, db, "50", payee="Moore Wilson", account_code="429", description="Weekly  shop")
    assert _treatment(db, line_id) == expected


def test_ac81_most_recently_updated_wins_a_full_tie(flask_app, world, db):  # noqa: F811
    client = user_client(db, flask_app, world["org"])
    a = _rule(client, description_pattern="weekly shop", treatment="overhead").get_json()
    _rule(client, description_pattern="shop", match_type="contains", treatment="duty")
    line_id = _purchase(world, db, "50", description="Weekly shop")
    assert _treatment(db, line_id) == "overhead", "exact before contains"
    b = _rule(client, payee_pattern="moore", match_type="contains", treatment="not_stock").get_json()
    c = _rule(client, payee_pattern="wilson", match_type="contains", treatment="stock").get_json()
    line2 = _purchase(world, db, "50", payee="Moore Wilson", description="Other")
    assert _treatment(db, line2) == "stock", "the later of two equal rules wins"
    client.put(f"{API}/rules/{b['id']}", json={**b, "treatment": "duty"})
    assert _treatment(db, line2) == "duty", "updating makes it the most recent"
    del a, c


# --- AC17 / AC84: re-classification -------------------------------------------------------------


def test_ac17_rule_change_reclassifies_open_and_skipped_only(flask_app, world, db):  # noqa: F811
    client = user_client(db, flask_app, world["org"])
    open_line = _purchase(world, db, "10", payee="Changer")
    skipped = _purchase(world, db, "20", payee="Changer")
    recorded = _purchase(world, db, "30", payee="Changer")
    client.post(f"{API}/purchases/{skipped}/skip", headers=_key())
    _assert_success(_record(client, recorded, [_row("Kept", 1, 30)]))
    rule = _rule(client, payee_pattern="Changer", treatment="not_stock").get_json()
    assert (_treatment(db, open_line), _treatment(db, skipped), _treatment(db, recorded)) == (
        "not_stock",
        "not_stock",
        "stock",
    )
    db.expire_all()
    assert db.get(PurchaseLine, open_line).treatment_rule_id is not None

    assert client.delete(f"{API}/rules/{rule['id']}").status_code in (200, 204)
    db.expire_all()
    assert _treatment(db, open_line) == "stock" and db.get(PurchaseLine, open_line).treatment_rule_id is None
    assert _treatment(db, recorded) == "stock"


# --- AC16 / AC10: remember ------------------------------------------------------------------------


def test_ac16_remember_creates_a_rule_that_prefills_by_share(flask_app, world, db):  # noqa: F811
    client = user_client(db, flask_app, world["org"])
    first = _purchase(world, db, "100", payee="Spice Merchant")
    _assert_success(_record(client, first, [_row("Cardamom", 2, 60), _row("Clove", 1, 25)], rest="not_stock"))
    made = client.post(f"{API}/purchases/{first}/remember", headers=_key())
    assert made.status_code in (200, 201), made.get_json()
    card = _card(client, _purchase(world, db, "200", payee="Spice Merchant"))
    assert card["prefill"]["source"] == "rule"
    got = {r["name"]: (D(r["amount"]), D(r["quantity"])) for r in card["prefill"]["rows"]}
    assert got == {"Cardamom": (D("120"), D("2")), "Clove": (D("50"), D("1"))}
    again = client.post(f"{API}/purchases/{first}/remember", headers=_key())
    assert again.status_code in (200, 201)
    assert len(client.get(f"{API}/rules").get_json()["rules"]) == 1, "remembering twice updates the rule"


def test_ac10_not_stock_always_creates_a_rule(flask_app, world, db):  # noqa: F811
    client = user_client(db, flask_app, world["org"])
    first = _purchase(world, db, "40", payee="Cafe Down The Road")
    _assert_success(client.post(f"{API}/purchases/{first}/not-stock", json={"always": True}, headers=_key()))
    later = _purchase(world, db, "12", payee="Cafe Down The Road")
    assert _treatment(db, later) == "not_stock"
    assert _card(client, later) is None and _card(client, later, tab="not_stock") is None


# --- AC82: rules API validation ---------------------------------------------------------------------


@pytest.mark.parametrize(
    "body",
    [
        dict(),  # no matcher
        dict(payee_pattern="X", match_type="fuzzy"),
        dict(payee_pattern="X", treatment="gold"),
        dict(
            payee_pattern="X",
            treatment="not_stock",
            template=[
                {"name": "A", "unit": "kg", "inventory_type": "raw_material", "quantity_mode": "ask", "share": "rest"}
            ],
        ),
        dict(
            payee_pattern="X",
            template=[
                {"name": "A", "unit": "kg", "inventory_type": "raw_material", "quantity_mode": "ask", "share": "rest"},
                {"name": "B", "unit": "kg", "inventory_type": "raw_material", "quantity_mode": "ask", "share": "rest"},
            ],
        ),
        dict(
            payee_pattern="X",
            template=[
                {"name": "A", "unit": "kg", "inventory_type": "raw_material", "quantity_mode": "ask", "share": "70"},
                {"name": "B", "unit": "kg", "inventory_type": "raw_material", "quantity_mode": "ask", "share": "40"},
            ],
        ),
        dict(
            payee_pattern="X",
            template=[
                {"name": "A", "unit": "kg", "inventory_type": "raw_material", "quantity_mode": "magic", "share": "rest"}
            ],
        ),
        dict(
            payee_pattern="X",
            template=[
                {"name": "A", "unit": "kg", "inventory_type": "raw_material", "quantity_mode": "fixed", "share": "rest"}
            ],
        ),
        dict(
            payee_pattern="X",
            template=[
                {
                    "name": "A",
                    "unit": "kg",
                    "inventory_type": "work_in_progress",
                    "quantity_mode": "ask",
                    "share": "rest",
                }
            ],
        ),
    ],
)
def test_ac82_rule_validation(flask_app, world, db, body):  # noqa: F811
    client = user_client(db, flask_app, world["org"])
    response = client.post(f"{API}/rules", json={"match_type": "exact", "treatment": "stock", **body})
    assert response.status_code == 400, (body, response.get_json())


def test_ac82_duplicate_matchers_conflict_and_isolation_and_permissions(flask_app, world, db):  # noqa: F811
    client = user_client(db, flask_app, world["org"])
    first = _rule(client, payee_pattern="Dup Co", account_code="310")
    assert first.status_code == 201
    assert _rule(client, payee_pattern="  dup   co ", account_code="310").status_code == 409, "patterns are normalised"
    rule_id = first.get_json()["id"]
    viewer = user_client(db, flask_app, world["org"], permissions=["costs.view"])
    assert viewer.get(f"{API}/rules").status_code == 200
    assert (
        viewer.post(
            f"{API}/rules", json={"payee_pattern": "Y", "match_type": "exact", "treatment": "stock"}
        ).status_code
        == 403
    )
    other = new_org(db)
    try:
        intruder = user_client(db, flask_app, other)
        assert intruder.delete(f"{API}/rules/{rule_id}").status_code == 404
        assert (
            intruder.put(
                f"{API}/rules/{rule_id}", json={"payee_pattern": "Z", "match_type": "exact", "treatment": "stock"}
            ).status_code
            == 404
        )
        assert intruder.get(f"{API}/rules").get_json()["rules"] == []
    finally:
        purge(db, other)


# --- AC13 / AC86: bulk -------------------------------------------------------------------------------


def test_ac13_bulk_skip_reports_foreign_lines_and_changes_nothing_there(flask_app, world, db, monkeypatch):  # noqa: F811
    client = user_client(db, flask_app, world["org"])
    a = _purchase(world, db, "10", payee="Bulk A")
    b = _purchase(world, db, "20", payee="Bulk B")
    other = new_org(db)
    try:
        from tests.test_costing_purchases import FakeXero, connect

        connect(db, other.id)
        foreign_world = {"org": other, "fake": FakeXero().install(monkeypatch)}
        foreign = _purchase(foreign_world, db, "30", payee="Theirs")
        world["fake"].install(monkeypatch)
        body = client.post(
            f"{API}/purchases/bulk", json={"line_ids": [str(a), str(b), str(foreign)], "action": "skip"}
        ).get_json()
        results = {r["line_id"]: r for r in body["results"]}
        assert results[str(a)]["ok"] and results[str(b)]["ok"]
        assert results[str(foreign)] == {"line_id": str(foreign), "ok": False, "error": "not found"}
        db.expire_all()
        assert db.get(PurchaseLine, foreign).state == "open"
        assert db.get(PurchaseLine, a).state == "skipped"
    finally:
        purge(db, other)


def test_ac86_bulk_limits(flask_app, world, db):  # noqa: F811
    client = user_client(db, flask_app, world["org"])
    a = _purchase(world, db, "10")
    assert (
        client.post(f"{API}/purchases/bulk", json={"line_ids": [str(a), str(a)], "action": "skip"}).status_code == 400
    )
    ids = [str(uuid4()) for _ in range(201)]
    assert client.post(f"{API}/purchases/bulk", json={"line_ids": ids, "action": "skip"}).status_code == 400
    assert client.post(f"{API}/purchases/bulk", json={"line_ids": [str(a)], "action": "explode"}).status_code == 400


def test_bulk_apply_rule_reclassifies_and_returns_cards(flask_app, world, db):  # noqa: F811
    client = user_client(db, flask_app, world["org"])
    line_id = _purchase(world, db, "15", payee="Later Rule Co", account_code="429")
    assert _treatment(db, line_id) == "not_stock"
    db.query(PurchaseLine).filter(PurchaseLine.id == line_id).update({"treatment": "not_stock"})
    db.commit()
    from app.features.costing.models import PurchaseRule

    db.add(
        PurchaseRule(
            org_id=world["org"].id, payee_pattern="later rule co", match_type="exact", treatment="stock", is_active=True
        )
    )
    db.commit()
    body = client.post(f"{API}/purchases/bulk", json={"line_ids": [str(line_id)], "action": "apply_rule"}).get_json()
    (result,) = body["results"]
    assert result["ok"] and result["card"]["line_id"] == str(line_id)
    assert _treatment(db, line_id) == "stock"


# --- AC18–AC20 / AC85: historical runs ------------------------------------------------------------------


def _start(db, org_id, value):
    settings = db.query(CostingSettings).filter(CostingSettings.org_id == org_id).one()
    settings.start_date = value
    db.commit()


def test_ac18_ac20_historical_run_fetches_lists_and_is_idempotent(flask_app, world, db):  # noqa: F811
    org, fake = world["org"], world["fake"]
    client = user_client(db, flask_app, org)
    sync(db, org.id)
    _start(db, org.id, date(2026, 11, 1))
    october = txn(
        [line("310", "45", line_item_id=str(uuid4()))], on=date(2026, 10, 15), amounts="NoTax", payee="Old Co"
    )
    fake.transactions = [october]
    sync(db, org.id, full=False)
    assert client.get(f"{API}/purchases?tab=to_record").get_json()["counts"]["to_record"] == 0, "before start_date"

    calls_before = len(fake.bank_calls())
    run = client.post(f"{API}/purchases/historical-run", json={"from": "2026-10-01", "to": "2026-10-31"})
    assert run.status_code == 200, run.get_json()
    assert run.get_json()["documents"] == 1
    call = fake.bank_calls()[calls_before]
    assert call["from_date"] == date(2026, 10, 1) and call["to_date"] == date(2026, 10, 31)
    assert call["modified_after"] is None
    settings = db.query(CostingSettings).filter(CostingSettings.org_id == org.id).one()
    db.refresh(settings)
    assert (settings.last_history_from, settings.last_history_to) == (date(2026, 10, 1), date(2026, 10, 31))

    hist = client.get(f"{API}/purchases?tab=to_record&historical=1&from=2026-10-01&to=2026-10-31").get_json()
    assert hist["counts"]["to_record"] == 1

    again = client.post(f"{API}/purchases/historical-run", json={"from": "2026-10-01", "to": "2026-10-31"})
    assert again.status_code == 200 and len(fake.bank_calls()) == calls_before + 2, "always refetches"
    from tests.test_costing_purchases import documents

    assert len([d for d in documents(db, org.id) if d.payee_name == "Old Co"]) == 1


def test_ac19_historical_mode_skipped_actionable_and_not_stock_undo(flask_app, world, db):  # noqa: F811
    org = world["org"]
    client = user_client(db, flask_app, org)
    skipped = _purchase(world, db, "10", payee="Skippy", on=date(2026, 10, 15))
    excluded = _purchase(world, db, "20", payee="Notty", on=date(2026, 10, 16))
    client.post(f"{API}/purchases/{skipped}/skip", headers=_key())
    client.post(f"{API}/purchases/{excluded}/not-stock", headers=_key())
    _start(db, org.id, date(2026, 11, 1))
    params = dict(historical=1, **{"from": "2026-10-01", "to": "2026-10-31"})
    assert _card(client, skipped, tab="to_record", **params) is not None
    undo = _card(client, excluded, tab="not_stock", **params)
    assert undo is not None and undo["undo"] is True
    _assert_success(client.post(f"{API}/purchases/{excluded}/reopen", headers=_key()))
    assert D(_card(client, excluded, tab="to_record", **params)["open"]) == D("20")


@pytest.mark.parametrize(
    "body",
    [
        {"from": "2026-10-31", "to": "2026-10-01"},
        {"from": "2026-10-01", "to": (date.today() + timedelta(days=30)).isoformat()},
        {"from": "2020-01-01", "to": "2026-10-01"},
        {"from": "2026-10-01"},
        {"from": "nope", "to": "2026-10-01"},
    ],
)
def test_ac85_historical_run_validation(flask_app, world, db, body):  # noqa: F811
    client = user_client(db, flask_app, world["org"])
    assert client.post(f"{API}/purchases/historical-run", json=body).status_code == 400


def test_ac85_historical_run_without_scopes_is_409(flask_app, db, monkeypatch):  # noqa: F811
    from tests.test_costing_purchases import FakeXero, connect

    org = new_org(db)
    try:
        connect(db, org.id, scopes="openid accounting.contacts accounting.invoices offline_access")
        FakeXero().install(monkeypatch)
        client = user_client(db, flask_app, org)
        response = client.post(f"{API}/purchases/historical-run", json={"from": "2026-10-01", "to": "2026-10-31"})
        assert response.status_code == 409 and response.get_json()["code"] == "needs_reconnect"
    finally:
        purge(db, org)
