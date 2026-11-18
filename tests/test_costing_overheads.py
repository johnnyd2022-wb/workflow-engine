"""Live-cogs 8.1h: overheads into cost, opt-in (spec .agents/specs/live-cogs-overheads.md).

Written before the implementation. Each test names the acceptance criterion it proves. Orgs here
have no Xero connection: overhead rates are typed, and a batch's overheads need nothing else.
"""

# ruff: noqa: F811 -- flask_app is re-exported as a fixture and used as a test argument

from __future__ import annotations

from datetime import date, datetime, time
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest

from app.core.db.models.execution import Execution
from app.features.compliant.models.alcohol_product_profile import AlcoholProductProfile
from tests.costing_helpers import (
    D,
    complete,
    execution_cost,
    lot,
    lot_cost,
    new_org,
    output_defs,
    price,
    produced_lots,
    purge,
    user_client,
    workflow,
)
from tests.test_compliant_routes import flask_app  # noqa: F401 -- fixture re-export

API = "/api/core/costing"
NZ = ZoneInfo("Pacific/Auckland")
LONG_AGO = "2026-01-01"


@pytest.fixture
def world(db, flask_app):
    org = new_org(db)
    client = user_client(db, flask_app, org)
    yield {"org": org, "client": client}
    purge(db, org)


# --- helpers -----------------------------------------------------------------------------------


def _switch(client, on=True):
    response = client.put(f"{API}/settings", json={"include_overheads": on})
    assert response.status_code == 200, response.get_json()
    return response.get_json()


def _rate(client, name, basis, amount, effective_from=LONG_AGO, expect=201):
    response = client.post(
        f"{API}/overhead-rates",
        json={"name": name, "basis": basis, "amount": str(amount), "effective_from": effective_from},
    )
    assert response.status_code == expect, response.get_json()
    return response.get_json()


def _set_completed(db, execution, on: date):
    db.expire_all()
    row = db.query(Execution).filter(Execution.id == execution.id).one()
    row.completed_at = datetime.combine(on, time(12, 0), tzinfo=NZ)
    db.commit()


def _batch(db, client, org, *, quantity=200, unit="L", materials=1000, name="Gin", on=None, outputs=None):
    """One finished batch: 100 L of spirit costing ``materials`` becomes ``quantity`` ``unit`` of
    ``name`` (a single terminal step, so its output is final product)."""
    spirit = lot(db, org.id, f"Neutral spirit {uuid4().hex[:6]}", 100, "L")
    price(db, org.id, spirit.id, materials, 100)
    execution, (step,) = workflow(db, org.id, [[{"name": name, "unit": unit}]])
    produced = outputs or [{"name": name, "quantity": quantity, "unit": unit, "output_id": output_defs(step)[0]["id"]}]
    complete(client, execution, step, [(spirit, 100, "L")], produced)
    if on is not None:
        _set_completed(db, execution, on)
    lots = produced_lots(db, org.id, step.id)
    return {"execution": execution, "step": step, "spirit": spirit, "lots": lots, "gin": lots[0]}


def _lot_json(client, item):
    response = client.get(f"{API}/lots/{item.id}/cost")
    assert response.status_code == 200, response.get_json()
    return response.get_json()


def _profile(db, org, name="Gin", pack_ml=700):
    db.add(
        AlcoholProductProfile(
            org_id=org.id, inventory_name=name, product_type="spirit", pack_volume_ml=pack_ml, is_active=True
        )
    )
    db.commit()


# --- AC-OV1: off by default ------------------------------------------------------------------


def test_ac_ov01_off_by_default_and_rates_change_nothing(world, db):
    org, client = world["org"], world["client"]
    batch = _batch(db, client, org)
    before_lot = lot_cost(db, org.id, batch["gin"].id)
    before_batch = execution_cost(db, org.id, batch["execution"].id)
    assert D(before_lot["unit_cost"]) == D("5.000000")

    assert client.get(f"{API}/settings").get_json() == {"use_last_known_price": True, "split_basis": "quantity"}
    # Rates can be typed in beforehand; with the setting off they do nothing at all.
    _rate(client, "Rent", "per_litre", "0.50")
    _rate(client, "Labour", "per_batch", "40")
    assert client.get(f"{API}/settings").get_json() == {"use_last_known_price": True, "split_basis": "quantity"}

    assert lot_cost(db, org.id, batch["gin"].id) == before_lot
    assert execution_cost(db, org.id, batch["execution"].id) == before_batch
    assert "overheads" not in before_batch and "overhead_unit_cost" not in before_lot
    assert all("overhead_amount" not in out for out in before_batch["outputs"])

    # Switching on and back off puts everything back exactly as it was.
    _switch(client, True)
    assert D(lot_cost(db, org.id, batch["gin"].id)["unit_cost"]) == D("5.700000")
    _switch(client, False)
    assert client.get(f"{API}/settings").get_json() == {"use_last_known_price": True, "split_basis": "quantity"}
    assert lot_cost(db, org.id, batch["gin"].id) == before_lot
    assert execution_cost(db, org.id, batch["execution"].id) == before_batch


# --- AC-OV2: the switch ----------------------------------------------------------------------


def test_ac_ov02_setting_round_trip_and_validation(world, db, flask_app):
    client = world["client"]
    assert "include_overheads" not in client.get(f"{API}/settings").get_json()
    assert _switch(client, True) == {"use_last_known_price": True, "split_basis": "quantity", "include_overheads": True}
    assert client.get(f"{API}/settings").get_json()["include_overheads"] is True
    assert client.put(f"{API}/settings", json={"include_overheads": "yes"}).status_code == 400
    assert client.put(f"{API}/settings", json={"include_overheads": 1}).status_code == 400
    assert _switch(client, False) == {"use_last_known_price": True, "split_basis": "quantity"}

    viewer = user_client(db, flask_app, world["org"], permissions=["costs.view"])
    assert viewer.put(f"{API}/settings", json={"include_overheads": True}).status_code == 403
    assert viewer.get(f"{API}/settings").status_code == 200


# --- AC-OV3: rates ---------------------------------------------------------------------------


def test_ac_ov03_rates_crud_and_validation(world, db):
    client = world["client"]
    made = _rate(client, "  Rent ", "per_litre", "0.5", "2026-10-01")
    assert made["name"] == "Rent" and made["basis"] == "per_litre"
    assert D(made["amount"]) == D("0.5") and made["effective_from"] == "2026-10-01" and made["is_active"] is True

    for bad in (
        {"name": "", "basis": "per_litre", "amount": "1", "effective_from": "2026-10-01"},
        {"name": "x" * 81, "basis": "per_litre", "amount": "1", "effective_from": "2026-10-01"},
        {"name": "Rent", "basis": "per_hour", "amount": "1", "effective_from": "2026-10-01"},
        {"name": "Rent", "basis": "per_litre", "amount": "-1", "effective_from": "2026-10-01"},
        {"name": "Rent", "basis": "per_litre", "amount": "abc", "effective_from": "2026-10-01"},
        {"name": "Rent", "basis": "per_litre", "amount": "NaN", "effective_from": "2026-10-01"},
        {"name": "Rent", "basis": "per_litre", "amount": "0.1234567", "effective_from": "2026-10-01"},
        {"name": "Rent", "basis": "per_litre", "amount": True, "effective_from": "2026-10-01"},
        {"name": "Rent", "basis": "per_litre", "amount": "1", "effective_from": "not a date"},
        {"name": "Rent", "basis": "per_litre", "amount": "1"},
        {"name": "Rent", "basis": "per_litre", "amount": "1", "effective_from": "2026-10-01", "extra": 1},
    ):
        assert client.post(f"{API}/overhead-rates", json=bad).status_code == 400, bad

    # One rate per name, basis and date (case-insensitive); a different date or basis is fine.
    assert (
        client.post(
            f"{API}/overhead-rates",
            json={"name": "RENT", "basis": "per_litre", "amount": "9", "effective_from": "2026-10-01"},
        ).status_code
        == 409
    )
    _rate(client, "Rent", "per_litre", "0.60", "2026-11-01")
    _rate(client, "Rent", "per_batch", "20", "2026-10-01")

    rows = client.get(f"{API}/overhead-rates").get_json()["rates"]
    dates = [r["effective_from"] for r in rows]
    assert len(rows) == 3 and dates == sorted(dates, reverse=True)  # newest effective date first

    changed = client.put(f"{API}/overhead-rates/{made['id']}", json={"amount": "0.55", "is_active": False})
    assert changed.status_code == 200 and D(changed.get_json()["amount"]) == D("0.55")
    assert changed.get_json()["is_active"] is False
    assert client.put(f"{API}/overhead-rates/{made['id']}", json={"basis": "nope"}).status_code == 400
    assert client.put(f"{API}/overhead-rates/not-a-uuid", json={"amount": "1"}).status_code == 404

    assert client.delete(f"{API}/overhead-rates/{made['id']}").status_code == 200
    assert client.delete(f"{API}/overhead-rates/{made['id']}").status_code == 404
    assert len(client.get(f"{API}/overhead-rates").get_json()["rates"]) == 2


# --- AC-OV4: the worked example, with no Xero ----------------------------------------------------


def test_ac_ov04_worked_example_200_litre_batch_without_xero(world, db):
    org, client = world["org"], world["client"]
    assert client.get(f"{API}/me").get_json()["xero_connected"] is False
    batch = _batch(db, client, org)  # $1,000 of spirit -> 200 L
    _rate(client, "Rent", "per_litre", "0.50")
    _rate(client, "Labour", "per_batch", "40")
    _switch(client, True)

    cost = _lot_json(client, batch["gin"])
    assert cost["status"] == "actual"
    assert D(cost["unit_cost"]) == D("5.700000")
    assert D(cost["materials_unit_cost"]) == D("5.000000")
    assert D(cost["overhead_unit_cost"]) == D("0.700000")

    result = execution_cost(db, org.id, batch["execution"].id)
    assert result["status"] == "actual"
    overheads = result["overheads"]
    assert overheads["note"] is None and D(overheads["amount"]) == D("140.0000")
    lines = {row["name"]: row for row in overheads["lines"]}
    assert (lines["Rent"]["basis"], D(lines["Rent"]["quantity"]), D(lines["Rent"]["amount"])) == (
        "per_litre",
        D("200"),
        D("100.0000"),
    )
    assert D(lines["Rent"]["rate"]) == D("0.5")
    assert (lines["Labour"]["basis"], D(lines["Labour"]["amount"])) == ("per_batch", D("40.0000"))
    (out,) = result["outputs"]
    assert D(out["known_amount"]) == D("1140.0000") and D(out["unit_cost"]) == D("5.700000")
    assert D(out["overhead_amount"]) == D("140.0000")
    assert D(out["overhead_unit_cost"]) == D("0.700000") and D(out["materials_unit_cost"]) == D("5.000000")
    assert D(result["known_input_cost"]) == D("1000.0000")  # what went in is still materials

    # The material lot itself carries no overhead.
    spirit = _lot_json(client, batch["spirit"])
    assert D(spirit["overhead_unit_cost"]) == D("0")


# --- AC-OV5: effective dates ----------------------------------------------------------------------


def test_ac_ov05_effective_dates(world, db):
    org, client = world["org"], world["client"]
    _rate(client, "Rent", "per_litre", "0.50", "2026-10-01")
    _rate(client, "Rent", "per_litre", "0.60", "2026-11-01")
    _rate(client, "Rent", "per_litre", "0", "2026-12-01")  # $0 ends Rent from 1 Dec
    _switch(client, True)

    def unit(on):
        batch = _batch(db, client, org, on=on)
        return D(lot_cost(db, org.id, batch["gin"].id)["unit_cost"])

    assert unit(date(2026, 9, 20)) == D("5.000000")  # before every rate
    assert unit(date(2026, 10, 1)) == D("5.500000")  # the effective date itself takes it
    assert unit(date(2026, 10, 15)) == D("5.500000")
    assert unit(date(2026, 11, 15)) == D("5.600000")  # the later row supersedes
    assert unit(date(2026, 12, 5)) == D("5.000000")  # a $0 row ends it

    # An inactive row is ignored: switching off Nov's rate leaves Oct's in force.
    nov = next(
        r for r in client.get(f"{API}/overhead-rates").get_json()["rates"] if r["effective_from"] == "2026-11-01"
    )
    client.put(f"{API}/overhead-rates/{nov['id']}", json={"is_active": False})
    assert unit(date(2026, 11, 15)) == D("5.500000")


# --- AC-OV6: running batches --------------------------------------------------------------------


def _two_step(db, client, org):
    spirit = lot(db, org.id, f"Neutral spirit {uuid4().hex[:6]}", 100, "L")
    price(db, org.id, spirit.id, 1000, 100)
    execution, (one, two) = workflow(db, org.id, [[{"name": "Gin base", "unit": "L"}], [{"name": "Gin", "unit": "L"}]])
    complete(
        client,
        execution,
        one,
        [(spirit, 100, "L")],
        [{"name": "Gin base", "quantity": 200, "unit": "L", "output_id": output_defs(one)[0]["id"]}],
    )
    (base,) = produced_lots(db, org.id, one.id)
    return {"execution": execution, "one": one, "two": two, "spirit": spirit, "base": base}


def _finish(db, client, org, made):
    complete(
        client,
        made["execution"],
        made["two"],
        [(made["base"], 200, "L")],
        [{"name": "Gin", "quantity": 200, "unit": "L", "output_id": output_defs(made["two"])[0]["id"]}],
    )
    (gin,) = produced_lots(db, org.id, made["two"].id)
    return gin


def test_ac_ov06_running_batch_has_no_overheads_yet(world, db):
    org, client = world["org"], world["client"]
    _rate(client, "Rent", "per_litre", "0.50")
    _rate(client, "Labour", "per_batch", "40")
    _switch(client, True)
    made = _two_step(db, client, org)

    running = execution_cost(db, org.id, made["execution"].id)
    assert running["overheads"] == {"amount": None, "lines": [], "note": "in_progress"}
    assert D(running["cost_so_far"]) == D("0.0000")  # step 1's output is the WIP lot
    assert D(lot_cost(db, org.id, made["base"].id)["unit_cost"]) == D("5.000000")

    gin = _finish(db, client, org, made)
    done = execution_cost(db, org.id, made["execution"].id)
    assert D(done["overheads"]["amount"]) == D("140.0000") and done["overheads"]["note"] is None
    assert D(lot_cost(db, org.id, gin.id)["unit_cost"]) == D("5.700000")


# --- AC-OV7: once, on the finished product ----------------------------------------------------


def test_ac_ov07_overheads_land_once_on_finished_product(world, db):
    org, client = world["org"], world["client"]
    _rate(client, "Rent", "per_litre", "0.50")
    _rate(client, "Labour", "per_batch", "40")
    _switch(client, True)
    made = _two_step(db, client, org)
    gin = _finish(db, client, org, made)

    base = lot_cost(db, org.id, made["base"].id)
    assert D(base["unit_cost"]) == D("5.000000") and D(base["overhead_unit_cost"]) == D("0")  # WIP: none
    final = lot_cost(db, org.id, gin.id)
    assert D(final["unit_cost"]) == D("5.700000")  # once, not twice
    assert D(final["overhead_unit_cost"]) == D("0.700000")

    result = execution_cost(db, org.id, made["execution"].id)
    assert D(result["overheads"]["amount"]) == D("140.0000")
    by_step = {row["step_number"]: row for row in result["outputs"]}
    assert D(by_step[1]["overhead_amount"]) == D("0")
    assert D(by_step[2]["overhead_amount"]) == D("140.0000")

    # A finished batch that only makes work-in-progress (a sample-only output is never finished
    # stock, even on the last step) takes nothing, and says why.
    spirit = lot(db, org.id, f"Neutral spirit {uuid4().hex[:6]}", 100, "L")
    price(db, org.id, spirit.id, 1000, 100)
    only_wip, (single,) = workflow(db, org.id, [[{"name": "Sample", "unit": "L", "extra_data": {"sample_only": True}}]])
    complete(
        client,
        only_wip,
        single,
        [(spirit, 100, "L")],
        [{"name": "Sample", "quantity": 100, "unit": "L", "output_id": output_defs(single)[0]["id"]}],
    )
    (made_lot,) = produced_lots(db, org.id, single.id)
    assert made_lot.inventory_type == "work_in_progress"
    result = execution_cost(db, org.id, only_wip.id)
    assert result["overheads"] == {"amount": None, "lines": [], "note": "no_finished_product"}
    assert D(lot_cost(db, org.id, made_lot.id)["unit_cost"]) == D("10.000000")


# --- AC-OV8: bottles, Library stock, unknown pack size --------------------------------------------


def _bottles(db, client, org, *, library=True):
    spirit = lot(db, org.id, f"Neutral spirit {uuid4().hex[:6]}", 10, "L")
    price(db, org.id, spirit.id, 90, 10)
    execution, (step,) = workflow(db, org.id, [[{"name": "Gin", "unit": "bottles"}]])
    out = {"name": "Gin", "quantity": 10, "unit": "bottles", "output_id": output_defs(step)[0]["id"]}
    if library:
        out["library_remainder_ml"] = "2000"
    complete(client, execution, step, [(spirit, 10, "L")], [out])
    return execution, step


def test_ac_ov08_bottle_litres_library_and_unknown_pack_size(world, db):
    org, client = world["org"], world["client"]
    _rate(client, "Rent", "per_litre", "0.50")
    _rate(client, "Labour", "per_batch", "40")
    _switch(client, True)
    execution, step = _bottles(db, client, org)

    # No pack size on the product yet: Rent can't be worked out. It is not guessed and not $0.
    unknown = execution_cost(db, org.id, execution.id)
    assert unknown["status"] == "partial" and "overhead_litres_unknown" in unknown["warnings"]
    assert unknown["overheads"]["note"] == "litres_unknown"
    assert [row["name"] for row in unknown["overheads"]["lines"]] == ["Labour"]
    assert D(unknown["overheads"]["amount"]) == D("40.0000")
    gin = next(o for o in unknown["outputs"] if o["name"] == "Gin")
    assert gin["unit_cost"] is None and D(gin["known_unit_cost"]) == D("13.000000")  # (90 + 40) / 10
    assert gin["status"] == "partial"

    # With the 700 mL pack size: 10 bottles = 7 L (Library stock is a remainder, outside the base).
    _profile(db, org)
    known = execution_cost(db, org.id, execution.id)
    assert known["status"] == "actual" and "overhead_litres_unknown" not in known["warnings"]
    lines = {row["name"]: row for row in known["overheads"]["lines"]}
    assert D(lines["Rent"]["quantity"]) == D("7") and D(lines["Rent"]["amount"]) == D("3.5000")
    assert D(known["overheads"]["amount"]) == D("43.5000")
    gin = next(o for o in known["outputs"] if o["name"] == "Gin")
    assert D(gin["unit_cost"]) == D("13.350000")  # (90 + 43.50) / 10
    assert D(gin["materials_unit_cost"]) == D("9.000000") and D(gin["overhead_unit_cost"]) == D("4.350000")
    library = next(o for o in known["outputs"] if o["name"].endswith("Library stock"))
    assert D(library["known_amount"]) == D("0")  # quantity split: Library stock takes no share (A9)


# --- AC-OV9: joint outputs ------------------------------------------------------------------------


def test_ac_ov09_overheads_follow_the_cost_share(world, db):
    org, client = world["org"], world["client"]
    _rate(client, "Rent", "per_litre", "0.50")
    _switch(client, True)
    spirit = lot(db, org.id, f"Neutral spirit {uuid4().hex[:6]}", 100, "L")
    price(db, org.id, spirit.id, 1000, 100)
    execution, (step,) = workflow(
        db,
        org.id,
        [
            [
                {"name": "Gin", "unit": "L", "cost_share": {"mode": "percent", "value": 80}},
                {"name": "Vodka", "unit": "L"},
            ]
        ],
    )
    defs = {d["name"]: d["id"] for d in output_defs(step)}
    complete(
        client,
        execution,
        step,
        [(spirit, 100, "L")],
        [
            {"name": "Gin", "quantity": 80, "unit": "L", "output_id": defs["Gin"]},
            {"name": "Vodka", "quantity": 20, "unit": "L", "output_id": defs["Vodka"]},
        ],
    )
    result = execution_cost(db, org.id, execution.id)
    outs = {o["name"]: o for o in result["outputs"]}
    assert D(result["overheads"]["amount"]) == D("50.0000")  # 0.50 x (80 + 20) L
    assert D(outs["Gin"]["known_amount"]) == D("840.0000") and D(outs["Gin"]["overhead_amount"]) == D("40.0000")
    assert D(outs["Vodka"]["known_amount"]) == D("210.0000") and D(outs["Vodka"]["overhead_amount"]) == D("10.0000")
    assert D(outs["Gin"]["unit_cost"]) == D("10.500000")


# --- AC-OV10: carried into a later batch -----------------------------------------------------------


def test_ac_ov10_overhead_carries_into_a_later_batch(world, db):
    org, client = world["org"], world["client"]
    _rate(client, "Rent", "per_litre", "0.50")
    _rate(client, "Labour", "per_batch", "40")
    _switch(client, True)
    first = _batch(db, client, org)  # 200 L at 5.70 (5.00 + 0.70)

    water = lot(db, org.id, f"Botanical water {uuid4().hex[:6]}", 100, "L")
    price(db, org.id, water.id, 90, 100)
    execution, (step,) = workflow(db, org.id, [[{"name": "Gin and tonic", "unit": "L"}]])
    complete(
        client,
        execution,
        step,
        [(first["gin"], 50, "L"), (water, 100, "L")],
        [{"name": "Gin and tonic", "quantity": 100, "unit": "L", "output_id": output_defs(step)[0]["id"]}],
    )
    (second,) = produced_lots(db, org.id, step.id)
    result = execution_cost(db, org.id, execution.id)
    # Pool: 50 L x 5.70 = 285 (of which 35 is overhead) + 90 = 375, plus its own 90 (0.50 x 100 L + 40).
    assert D(result["overheads"]["amount"]) == D("90.0000")
    cost = lot_cost(db, org.id, second.id)
    assert D(cost["unit_cost"]) == D("4.650000")
    assert D(cost["overhead_unit_cost"]) == D("1.250000")  # 35 inherited + 90 new, over 100 L
    assert D(cost["materials_unit_cost"]) == D("3.400000")


# --- AC-OV14: readiness ------------------------------------------------------------------------------


def test_ac_ov14_readiness_is_unaffected(world, db):
    org, client = world["org"], world["client"]
    _bottles(db, client, org, library=False)  # bottles, no pack size: overhead can't be measured
    before = client.get(f"{API}/readiness").get_json()["products"]
    gin_before = next(p for p in before if p["name"].lower() == "gin")
    assert gin_before["ready"] is True

    _rate(client, "Rent", "per_litre", "0.50")
    _rate(client, "Labour", "per_batch", "40")
    _switch(client, True)
    after = client.get(f"{API}/readiness").get_json()["products"]
    gin_after = next(p for p in after if p["name"].lower() == "gin")
    assert gin_after["ready"] is True  # an unmeasured overhead never makes a product "not ready"
    assert {p["key"]: p["ready"] for p in before} == {p["key"]: p["ready"] for p in after}


# --- AC-OV16: isolation and permissions -----------------------------------------------------------------


def test_ac_ov16_tenant_isolation_and_permissions(world, db, flask_app):
    org, client = world["org"], world["client"]
    mine = _rate(client, "Rent", "per_litre", "0.50")

    other = new_org(db)
    off = new_org(db, grant=False)
    try:
        other_client = user_client(db, flask_app, other)
        theirs = other_client.get(f"{API}/overhead-rates").get_json()["rates"]
        assert theirs == []
        assert other_client.put(f"{API}/overhead-rates/{mine['id']}", json={"amount": "9"}).status_code == 404
        assert other_client.delete(f"{API}/overhead-rates/{mine['id']}").status_code == 404
        assert len(client.get(f"{API}/overhead-rates").get_json()["rates"]) == 1
        # Another org's rate never reaches this org's batch.
        _rate(other_client, "Rent", "per_litre", "9")
        _switch(client, True)
        batch = _batch(db, client, org)
        assert D(lot_cost(db, org.id, batch["gin"].id)["unit_cost"]) == D("5.500000")

        no_feature = user_client(db, flask_app, off)
        assert no_feature.get(f"{API}/overhead-rates").status_code == 404
        assert (
            no_feature.post(
                f"{API}/overhead-rates",
                json={"name": "Rent", "basis": "per_litre", "amount": "1", "effective_from": LONG_AGO},
            ).status_code
            == 404
        )

        viewer = user_client(db, flask_app, org, permissions=["costs.view"])
        assert viewer.get(f"{API}/overhead-rates").status_code == 200
        assert (
            viewer.post(
                f"{API}/overhead-rates",
                json={"name": "Rent", "basis": "per_litre", "amount": "1", "effective_from": "2026-02-02"},
            ).status_code
            == 403
        )
        assert viewer.delete(f"{API}/overhead-rates/{mine['id']}").status_code == 403
        nobody = user_client(db, flask_app, org, permissions=["inventory.view"])
        assert nobody.get(f"{API}/overhead-rates").status_code == 403
    finally:
        purge(db, other, off)


# --- AC-OV17: the migration -----------------------------------------------------------------------------


def test_ac_ov17_migration_shape(db):
    from sqlalchemy import inspect

    inspector = inspect(db.get_bind())
    settings = {c["name"]: c for c in inspector.get_columns("costing_settings")}
    assert settings["include_overheads"]["nullable"] is False
    assert "false" in str(settings["include_overheads"]["default"]).lower()
    lines = {c["name"]: c for c in inspector.get_columns("purchase_lines")}
    assert lines["freight"]["nullable"] is False and "false" in str(lines["freight"]["default"]).lower()
    rates = {c["name"]: c for c in inspector.get_columns("overhead_rates")}
    assert {"org_id", "name", "basis", "amount", "effective_from", "is_active"} <= set(rates)
    checks = {c["name"]: c["sqltext"] for c in inspector.get_check_constraints("overhead_rates")}
    assert any("per_litre" in text and "per_batch" in text for text in checks.values())
    assert any("amount" in text and ">=" in text for text in checks.values())
    uniques = {i["name"] for i in inspector.get_indexes("overhead_rates") if i.get("unique")}
    assert "uq_overhead_rates_name_basis_date" in uniques


# --- AC-OV19: no query per batch ---------------------------------------------------------------------------


def test_ac_ov19_primed_costs_do_not_query_per_batch(world, db):
    from sqlalchemy import event

    from app.features.costing.engine import CostEngine

    org, client = world["org"], world["client"]
    _rate(client, "Rent", "per_litre", "0.50")
    _rate(client, "Labour", "per_batch", "40")
    _switch(client, True)
    batches = [_batch(db, client, org) for _ in range(6)]

    def queries(count):
        db.expire_all()
        ids = {batch["gin"].id for batch in batches[:count]}
        seen = 0

        def tick(*_args):
            nonlocal seen
            seen += 1

        engine = CostEngine(db, org.id)
        event.listen(db.get_bind(), "before_cursor_execute", tick)
        try:
            engine.prime(ids)
            costs = [engine._solve(("lot", item_id)) for item_id in ids]
        finally:
            event.remove(db.get_bind(), "before_cursor_execute", tick)
        assert all(cost.unit_known == D("5.7") for cost in costs)  # overheads included, every time
        return seen

    assert abs(queries(6) - queries(2)) <= 1


# --- review follow-ups ---------------------------------------------------------------------------------


def test_ac_ov14b_a_bottled_lot_with_unmeasured_overhead_does_not_unready_what_uses_it(world, db):
    org, client = world["org"], world["client"]
    _bottles(db, client, org, library=False)  # Gin in bottles, no pack size
    _rate(client, "Rent", "per_litre", "0.50")
    _switch(client, True)
    from app.features.costing.models import CostFlow

    gin = db.query(CostFlow).filter(CostFlow.org_id == org.id, CostFlow.kind == "produced").first()
    execution, (step,) = workflow(db, org.id, [[{"name": "Gift pack", "unit": "packs"}]])
    from app.core.db.models.inventory_item import InventoryItem

    lot_row = db.query(InventoryItem).filter(InventoryItem.id == gin.inventory_item_id).one()
    complete(
        client,
        execution,
        step,
        [(lot_row, 2, "bottles")],
        [{"name": "Gift pack", "quantity": 1, "unit": "packs", "output_id": output_defs(step)[0]["id"]}],
    )
    products = {p["name"].lower(): p for p in client.get(f"{API}/readiness").get_json()["products"]}
    assert products["gift pack"]["ready"] is True


def test_ac_ov05b_completion_date_is_the_nz_date(world, db):
    org, client = world["org"], world["client"]
    _rate(client, "Rent", "per_litre", "0.50", "2026-11-01")
    _switch(client, True)
    batch = _batch(db, client, org)
    row = db.query(Execution).filter(Execution.id == batch["execution"].id).one()
    row.completed_at = datetime(2026, 10, 31, 23, 30, tzinfo=ZoneInfo("UTC"))  # 12:30 on 1 Nov in NZ
    db.commit()
    assert D(lot_cost(db, org.id, batch["gin"].id)["unit_cost"]) == D("5.500000")
