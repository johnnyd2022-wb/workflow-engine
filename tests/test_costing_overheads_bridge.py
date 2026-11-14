"""Live-cogs 8.1h with 8.1g: absorbed overhead in the bridge's roll-forward (AC-OV20).

Overheads absorbed into stock (a batch's rent and labour, freight on a purchase) raise the stock
value without a recorded purchase behind them. The bridge shows that as its own component, not as
a negative production loss or an "estimate change". Written before the implementation.
"""

# ruff: noqa: F811 -- flask_app / world are re-exported fixtures used as test arguments

from __future__ import annotations

from datetime import date

import pytest

from tests.costing_helpers import D, complete, lot, new_org, price, purge, user_client, workflow
from tests.test_compliant_routes import flask_app  # noqa: F401 -- fixture re-export
from tests.test_costing_bridge import bridge, snap
from tests.test_costing_overheads import _rate, _switch
from tests.test_costing_overheads_freight import _bill, _lot_id
from tests.test_costing_allocations import _record, _row
from tests.test_costing_purchases import FakeXero, connect
from tests.test_costing_overheads_freight import JUNIPER_AND_CORIANDER  # noqa: F401

OPENING, CLOSING = date(2026, 10, 31), date(2026, 11, 30)


@pytest.fixture
def plain(db, flask_app):
    org = new_org(db)
    client = user_client(db, flask_app, org)
    yield org, client
    purge(db, org)


@pytest.fixture
def world(db, flask_app, monkeypatch):
    org = new_org(db)
    connect(db, org.id)
    fake = FakeXero().install(monkeypatch)
    client = user_client(db, flask_app, org)
    yield {"org": org, "fake": fake, "client": client}
    purge(db, org)


def _components(body):
    return {k: D(v) for k, v in body["roll_forward"]["components"].items()}


def _a_batch_with_labour(plain, db, *, on):
    org, client = plain
    juniper = lot(db, org.id, "Juniper", 10, "kg")
    price(db, org.id, juniper.id, 50, 10)
    _rate(client, "Labour", "per_batch", "40")
    if on:
        _switch(client, True)
    opening = snap(db, org, OPENING)
    execution, (step,) = workflow(db, org.id, [[{"name": "Gin", "unit": "bottles"}]])
    complete(client, execution, step, [(juniper, 2, "kg")], [{"name": "Gin", "quantity": 4, "unit": "bottles"}])
    return bridge(client, opening, snap(db, org, CLOSING))


def test_ac_ov20_a_batchs_overhead_is_its_own_component_not_a_production_loss(plain, db):
    body = _a_batch_with_labour(plain, db, on=True)
    roll = body["roll_forward"]
    # $10 of juniper became 4 bottles, and the batch took $40 of labour: stock rose by $40.
    assert (D(roll["opening"]), D(roll["purchases"]), D(roll["closing"]), D(roll["cost_left"])) == (
        D("50"),
        D("0"),
        D("90"),
        D("-40"),
    )
    parts = _components(body)
    assert parts["overhead_absorbed"] == D("-40") and parts["production_loss"] == D("0")
    assert sum(parts.values()) == D(roll["cost_left"])
    assert roll["balanced"] is True
    assert D(body["overhead"]["absorbed"]["batch"]) == D("40") and D(body["overhead"]["absorbed"]["total"]) == D("40")


def test_ac_ov20_off_the_roll_forward_is_the_8_1g_one(plain, db):
    body = _a_batch_with_labour(plain, db, on=False)
    roll = body["roll_forward"]
    assert (D(roll["opening"]), D(roll["closing"]), D(roll["cost_left"])) == (D("50"), D("50"), D("0"))
    assert "overhead_absorbed" not in roll["components"] and "absorbed" not in body["overhead"]


def test_ac_ov20_freight_is_overhead_absorbed_not_an_estimate_change(world, db):
    org, client = world["org"], world["client"]
    salt = lot(db, org.id, "Salt", 1, "kg")
    price(db, org.id, salt.id, 10, 1)
    _switch(client, True)
    opening = snap(db, org, OPENING)

    juniper_line, _coriander, _freight = _bill(world, db, JUNIPER_AND_CORIANDER)
    juniper = _lot_id(_record(client, juniper_line.id, [_row("Juniper berries", 2, 150)]))
    assert D("2") * D(client.get(f"/api/core/costing/lots/{juniper}/cost").get_json()["unit_cost"]) == D("200")

    body = bridge(client, opening, snap(db, org, CLOSING))
    roll = body["roll_forward"]
    # $150 recorded as stock, and the $50 courier line spread onto it: stock rose by $200.
    assert (D(roll["opening"]), D(roll["purchases"]), D(roll["closing"])) == (D("10"), D("150"), D("210"))
    parts = _components(body)
    assert parts["overhead_absorbed"] == D("-50") and parts["estimate_changes"] == D("0")
    assert sum(parts.values()) == D(roll["cost_left"]) == D("-50")
    assert roll["balanced"] is True
    assert D(body["overhead"]["absorbed"]["freight"]) == D("50")
