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


def _purchase(w, db, amount, *, payee="Botanical Supply Co", account_code="310", description="Shop", on=PURCHASE_DATE):
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


def test_rule_update_preserves_auto_record_when_omitted_and_accepts_explicit_values(flask_app, world, db):  # noqa: F811
    client = user_client(db, flask_app, world["org"])
    template = [
        {
            "name": "Juniper",
            "inventory_type": "raw_material",
            "unit": "kg",
            "quantity_mode": "fixed",
            "quantity": "1",
            "share": "100",
        }
    ]
    created = _rule(client, payee_pattern="Auto Update Supplier", auto_record=True, template=template)
    assert created.status_code == 201, created.get_json()
    rule = created.get_json()

    legacy_payload = {
        "payee_pattern": rule["payee_pattern"],
        "match_type": rule["match_type"],
        "treatment": rule["treatment"],
        "template": rule["template"],
        "is_active": rule["is_active"],
    }
    omitted = client.put(f"{API}/rules/{rule['id']}", json=legacy_payload)
    assert omitted.status_code == 200, omitted.get_json()
    assert omitted.get_json()["auto_record"] is True

    enabled = client.put(f"{API}/rules/{rule['id']}", json={**legacy_payload, "auto_record": True})
    assert enabled.status_code == 200, enabled.get_json()
    assert enabled.get_json()["auto_record"] is True

    disabled = client.put(f"{API}/rules/{rule['id']}", json={**legacy_payload, "auto_record": False})
    assert disabled.status_code == 200, disabled.get_json()
    assert disabled.get_json()["auto_record"] is False


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


# --- 8.1c-2 review round 1 regressions -------------------------------------------------------------------


@pytest.mark.parametrize("state", ["recorded", "partly_recorded"])
def test_r1_bulk_apply_rule_leaves_recorded_lines_alone(flask_app, world, db, state):  # noqa: F811
    client = user_client(db, flask_app, world["org"])
    line_id = _purchase(world, db, "40", payee="Kept Co")
    spend = "40" if state == "recorded" else "15"
    _assert_success(_record(client, line_id, [_row("Juniper", 1, spend)]))
    db.expire_all()
    assert db.get(PurchaseLine, line_id).state == state
    before = _treatment(db, line_id)
    _rule(client, payee_pattern="Kept Co", treatment="not_stock")
    body = client.post(f"{API}/purchases/bulk", json={"line_ids": [str(line_id)], "action": "apply_rule"}).get_json()
    assert body["results"][0]["ok"] is False
    db.expire_all()
    row = db.get(PurchaseLine, line_id)
    assert row.treatment == before and row.treatment_rule_id is None


def test_r1_bulk_apply_rule_leaves_superseded_lines_alone(flask_app, world, db):  # noqa: F811
    from datetime import UTC, datetime

    client = user_client(db, flask_app, world["org"])
    line_id = _purchase(world, db, "40", payee="Gone Co")
    db.query(PurchaseLine).filter(PurchaseLine.id == line_id).update({"superseded_at": datetime.now(UTC)})
    db.commit()
    _rule(client, payee_pattern="Gone Co", treatment="not_stock")
    body = client.post(f"{API}/purchases/bulk", json={"line_ids": [str(line_id)], "action": "apply_rule"}).get_json()
    assert body["results"][0]["ok"] is False
    assert _treatment(db, line_id) == "stock"


def test_r1_bulk_rolls_back_only_the_item_that_failed_after_mutating(flask_app, world, db, monkeypatch):  # noqa: F811
    from app.features.costing import actions, service

    client = user_client(db, flask_app, world["org"])
    a, b, c = (_purchase(world, db, "10", payee=f"Roll {n}") for n in "ABC")
    real_skip = actions.skip

    def skip_then_fail(session, org_id, raw):
        result = real_skip(session, org_id, raw)
        session.flush()
        if str(raw) == str(b):
            raise service.CostingError("boom after the write")
        return result

    monkeypatch.setattr(actions, "skip", skip_then_fail)
    body = client.post(f"{API}/purchases/bulk", json={"line_ids": [str(a), str(b), str(c)], "action": "skip"})
    results = {r["line_id"]: r["ok"] for r in body.get_json()["results"]}
    assert results == {str(a): True, str(b): False, str(c): True}
    db.expire_all()
    assert [db.get(PurchaseLine, x).state for x in (a, b, c)] == ["skipped", "open", "skipped"]


@pytest.mark.parametrize(
    "body",
    [
        {"account_code": "   "},
        {"account_code": "   ", "payee_pattern": "  "},
    ],
)
def test_r1_whitespace_only_account_is_not_a_matcher(flask_app, world, db, body):  # noqa: F811
    client = user_client(db, flask_app, world["org"])
    assert _rule(client, **body).status_code == 400, "no real matcher left"


def test_r1_whitespace_account_with_a_payee_is_payee_only(flask_app, world, db):  # noqa: F811
    client = user_client(db, flask_app, world["org"])
    made = _rule(client, account_code="   ", payee_pattern="Space Co")
    assert made.status_code == 201, made.get_json()
    assert made.get_json()["account_code"] is None
    assert _rule(client, payee_pattern="Space Co").status_code == 409, "same matchers as the payee-only rule"


@pytest.mark.parametrize(
    "body",
    [
        {"payee_pattern": {"x": 1}},
        {"payee_pattern": ["a"]},
        {"account_code": 310},
        {"account_code": "9" * 51},
        {"payee_pattern": "p" * 256},
        {"payee_pattern": "X", "description_pattern": "d" * 501},
        {
            "payee_pattern": "X",
            "template": [
                {"name": ["A"], "unit": "kg", "inventory_type": "raw_material", "quantity_mode": "ask", "share": "rest"}
            ],
        },
        {
            "payee_pattern": "X",
            "template": [
                {
                    "name": "A" * 256,
                    "unit": "kg",
                    "inventory_type": "raw_material",
                    "quantity_mode": "ask",
                    "share": "rest",
                }
            ],
        },
        {
            "payee_pattern": "X",
            "template": [
                {
                    "name": "A",
                    "unit": "kg",
                    "inventory_type": "raw_material",
                    "quantity_mode": "ask",
                    "share": "rest",
                    "ask_expiry": "false",
                }
            ],
        },
    ],
)
def test_r1_rule_validation_types_and_lengths(flask_app, world, db, body):  # noqa: F811
    client = user_client(db, flask_app, world["org"])
    response = _rule(client, **body)
    assert response.status_code == 400, (body, response.status_code)


def test_r1_remember_shares_never_exceed_100_percent(flask_app, world, db):  # noqa: F811
    client = user_client(db, flask_app, world["org"])
    first = _purchase(world, db, "6", payee="Thirds Co")
    _assert_success(_record(client, first, [_row("A", 1, 1), _row("B", 1, 1), _row("C", 1, 4)]))
    made = client.post(f"{API}/purchases/{first}/remember", headers=_key())
    assert made.status_code in (200, 201), made.get_json()
    shares = [D(r["share"]) for r in made.get_json()["template"]]
    assert sum(shares) == D("100"), shares
    assert max(shares) == D("66.6668") and shares.count(D("16.6666")) == 2


def test_r1_last_time_prefill_survives_many_newer_purchases(flask_app, world, db):  # noqa: F811
    client = user_client(db, flask_app, world["org"])
    first = _purchase(world, db, "50", payee="Rare Supplier", on=PURCHASE_DATE - timedelta(days=3))
    _assert_success(_record(client, first, [_row("Orris", 1, 50)]))
    # 201 newer recorded purchases from other payees, written directly so the test stays fast
    template = db.get(PurchaseLine, first)
    from app.features.costing.models import PurchaseAllocation, PurchaseDocument

    doc = db.get(PurchaseDocument, template.document_id)
    alloc = db.query(PurchaseAllocation).filter(PurchaseAllocation.purchase_line_id == first).one()
    for n in range(201):
        new_doc = PurchaseDocument(
            **{
                c.name: getattr(doc, c.name)
                for c in PurchaseDocument.__table__.columns
                if c.name not in ("id", "external_id", "payee_name", "document_date", "created_at", "updated_at")
            },
            external_id=f"noise-{n}-{uuid4()}",
            payee_name=f"Noise {n}",
            document_date=PURCHASE_DATE,
        )
        db.add(new_doc)
        db.flush()
        new_line = PurchaseLine(
            **{
                c.name: getattr(template, c.name)
                for c in PurchaseLine.__table__.columns
                if c.name not in ("id", "document_id", "line_key", "fingerprint", "created_at", "updated_at")
            },
            document_id=new_doc.id,
            line_key=f"noise-{n}",
            fingerprint=f"noise-{n}",
        )
        db.add(new_line)
        db.flush()
        db.add(
            PurchaseAllocation(
                **{
                    c.name: getattr(alloc, c.name)
                    for c in PurchaseAllocation.__table__.columns
                    if c.name not in ("id", "purchase_line_id", "created_at", "updated_at")
                },
                purchase_line_id=new_line.id,
            )
        )
    db.commit()
    card = _card(client, _purchase(world, db, "100", payee="Rare Supplier"))
    assert card["prefill"]["source"] == "last_time", card["prefill"]


def test_r1_historical_list_needs_both_dates(flask_app, world, db):  # noqa: F811
    client = user_client(db, flask_app, world["org"])
    for query in ("historical=1", "historical=1&from=2026-10-01", "historical=1&from=2026-10-31&to=2026-10-01"):
        assert client.get(f"{API}/purchases?tab=to_record&{query}").status_code == 400, query


@pytest.mark.parametrize(
    ("date_from", "date_to", "ok"),
    [
        ("2023-01-01", "2025-12-31", True),
        ("2023-01-01", "2026-01-01", False),
        ("2023-01-01", "2026-01-03", False),
    ],
)
def test_r1_historical_run_is_three_calendar_years(flask_app, world, db, date_from, date_to, ok):  # noqa: F811
    client = user_client(db, flask_app, world["org"])
    sync(db, world["org"].id)
    status = client.post(f"{API}/purchases/historical-run", json={"from": date_from, "to": date_to}).status_code
    assert (status == 200) is ok, status


def test_r1_historical_run_failure_after_accounts_rolls_back_and_is_sanitized(flask_app, world, db, monkeypatch):  # noqa: F811
    from app.features.crm.models.xero_account import XeroAccount
    from app.features.crm.services import xero_api_client as module

    org, fake = world["org"], world["fake"]
    client = user_client(db, flask_app, org)
    sync(db, org.id)
    settings = db.query(CostingSettings).filter(CostingSettings.org_id == org.id).one()
    before = (settings.start_date, settings.purchases_cursor, settings.last_history_from)
    from tests.test_costing_purchases import account as xero_account

    first = fake.accounts[0]
    original_name = (
        db.query(XeroAccount).filter(XeroAccount.org_id == org.id, XeroAccount.code == first.code).one().name
    )
    renamed = xero_account(first.code, "Renamed during a failed run", account_id=first.account_id)
    fake.accounts = [renamed, *fake.accounts[1:]]  # a copy: the shared ACCOUNTS list stays untouched

    def explode(_self, **_kwargs):
        raise RuntimeError("SECRET relation purchase_lines value Botanical")

    monkeypatch.setattr(module.XeroAPIClient, "get_bank_transactions", explode)
    response = client.post(f"{API}/purchases/historical-run", json={"from": "2026-10-01", "to": "2026-10-31"})
    assert response.status_code == 502
    payload = response.get_json()
    assert payload["code"] == "historical_failed" and "SECRET" not in payload["error"]
    db.expire_all()
    settings = db.query(CostingSettings).filter(CostingSettings.org_id == org.id).one()
    assert (settings.start_date, settings.purchases_cursor, settings.last_history_from) == before
    account = db.query(XeroAccount).filter(XeroAccount.org_id == org.id, XeroAccount.code == renamed.code).one()
    assert account.name == original_name, "account writes roll back with the run"


# --- 8.1c-2 review round 2 regressions -------------------------------------------------------------------


def test_r2_pattern_that_lengthens_when_normalised_is_400(flask_app, world, db):  # noqa: F811
    client = user_client(db, flask_app, world["org"])
    assert _rule(client, payee_pattern="ẞ" * 200).status_code == 400


def test_r2_last_time_matches_payees_the_way_rules_do(flask_app, world, db):  # noqa: F811
    client = user_client(db, flask_app, world["org"])
    first = _purchase(world, db, "50", payee="Straße Botanicals", on=PURCHASE_DATE - timedelta(days=3))
    _assert_success(_record(client, first, [_row("Orris", 1, 50)]))
    card = _card(client, _purchase(world, db, "100", payee="STRASSE BOTANICALS"))
    assert card["prefill"]["source"] == "last_time", card["prefill"]


def test_r2_last_time_skips_voided_history_without_a_limit(flask_app, world, db):  # noqa: F811
    from app.features.costing.models import PurchaseAllocation, PurchaseDocument

    client = user_client(db, flask_app, world["org"])
    good = _purchase(world, db, "50", payee="Busy Co", on=PURCHASE_DATE - timedelta(days=10))
    _assert_success(_record(client, good, [_row("Good Orris", 1, 50)]))
    newer = []
    for n in range(25):
        lid = _purchase(world, db, "10", payee="Busy Co", on=PURCHASE_DATE - timedelta(days=5))
        _assert_success(_record(client, lid, [_row(f"Voided {n}", 1, 10)]))
        newer.append(lid)
    target = _purchase(world, db, "100", payee="Busy Co")  # synced before the voids, which a re-sync would undo
    db.expire_all()
    doc_ids = [db.get(PurchaseLine, lid).document_id for lid in newer]
    db.query(PurchaseDocument).filter(PurchaseDocument.id.in_(doc_ids)).update(
        {"status": "voided"}, synchronize_session=False
    )
    db.query(PurchaseAllocation).filter(PurchaseAllocation.purchase_line_id.in_(newer)).update(
        {"status": "orphaned", "orphaned_by": "void"}, synchronize_session=False
    )
    db.commit()
    card = _card(client, target)
    assert card["prefill"]["source"] == "last_time"
    assert [r["name"] for r in card["prefill"]["rows"]] == ["Good Orris"]


def test_r2_rule_change_leaves_voided_purchases_alone(flask_app, world, db):  # noqa: F811
    from app.features.costing.models import PurchaseDocument

    client = user_client(db, flask_app, world["org"])
    line_id = _purchase(world, db, "40", payee="Void Co")
    db.expire_all()
    doc_id = db.get(PurchaseLine, line_id).document_id
    db.query(PurchaseDocument).filter(PurchaseDocument.id == doc_id).update({"status": "voided"})
    db.commit()
    before = _treatment(db, line_id)
    assert _rule(client, payee_pattern="Void Co", treatment="not_stock").status_code == 201
    db.expire_all()
    row = db.get(PurchaseLine, line_id)
    assert row.treatment == before and row.treatment_rule_id is None


@pytest.mark.parametrize("bad", [[2026], {"y": 2026}, 20261001])
def test_r2_non_string_dates_are_400(flask_app, world, db, bad):  # noqa: F811
    client = user_client(db, flask_app, world["org"])
    response = client.post(f"{API}/purchases/historical-run", json={"from": bad, "to": "2026-10-31"})
    assert response.status_code == 400


def test_r3_purchase_list_reads_last_time_history_once(flask_app, world, db):  # noqa: F811
    """Round 3: last-time history is built once per list, not once per card."""
    from sqlalchemy import event

    client = user_client(db, flask_app, world["org"])
    for n in range(4):
        old = _purchase(world, db, "10", payee=f"Hist {n}", on=PURCHASE_DATE - timedelta(days=9))
        _assert_success(_record(client, old, [_row(f"Old {n}", 1, 10)]))
    for n in range(4):
        _purchase(world, db, "20", payee=f"Hist {n}")

    def count_history_reads():
        seen = []
        bind = db.get_bind()
        engine = getattr(bind, "engine", bind)

        def hook(_conn, _cursor, statement, *_a):
            if "purchase_allocations" in statement and "EXISTS" in statement.upper():
                seen.append(statement)

        event.listen(engine, "before_cursor_execute", hook)
        try:
            body = client.get(f"{API}/purchases?tab=to_record").get_json()
        finally:
            event.remove(engine, "before_cursor_execute", hook)
        return body, len(seen)

    body, reads = count_history_reads()
    assert len(body["cards"]) == 4 and all(c["prefill"]["source"] == "last_time" for c in body["cards"])
    assert reads == 1, f"{reads} history reads for 4 cards"


def test_polish_last_time_prefill_reads_in_cents_and_still_adds_up(flask_app, world, db):  # noqa: F811
    """Polish: suggestions read "33.33", not "33.3333", and the last row takes the exact rest."""
    client = user_client(db, flask_app, world["org"])
    first = _purchase(world, db, "90", payee="Even Thirds")
    _assert_success(_record(client, first, [_row("A", 1, 30), _row("B", 1, 30), _row("C", 1, 30)]))
    card = _card(client, _purchase(world, db, "100", payee="Even Thirds"))
    assert card["prefill"]["source"] == "last_time"
    amounts = [D(r["amount"]) for r in card["prefill"]["rows"]]
    assert sorted(amounts) == [D("33.33"), D("33.33"), D("33.34")]
    assert sum(amounts) == D("100")


@pytest.mark.parametrize(
    ("shares", "remaining"),
    [(["1"] * 5, "0.03"), (["30", "30", "30"], "100"), (["1", "2", "3"], "10.005"), (["7"], "12.34")],
)
def test_polish_cent_split_adds_up_and_never_goes_negative(shares, remaining):
    from app.features.costing.actions import _split_in_cents

    total = D(remaining)
    whole = sum(D(x) for x in shares)
    exact = [total * D(x) / whole for x in shares]
    amounts = _split_in_cents(exact, total)
    assert sum(amounts) == total and all(a >= 0 for a in amounts)
    assert all(abs(a - e) < D("0.02") for a, e in zip(amounts, exact, strict=True))
