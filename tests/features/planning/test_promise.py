"""Promise dates (GL-P07 B5): planned and forecast ready dates on contract orders and the
portal, and "when can we deliver n?" for a new order."""

from __future__ import annotations

from datetime import timedelta

import pytest

from app.core.security.access_policy import requirement_for
from app.features.contract_manufacturing.services.orders import serialize_order
from app.features.planning import batch_service, contract_sync, promise
from app.features.planning.batch_models import PlanningBatch
from app.features.planning.models import PlanningDemand
from tests.features.planning import test_demand_sources as sources
from tests.features.planning.test_demand_sources import TODAY, _contract, _setup, _stock

# Fixtures re-exported the way the other planning modules share them.
base_demand_world = sources.base_demand_world
demand_world = sources.demand_world


def _planned_order(db, world, quantity=600):
    org_id, output_id, _ = _setup(db, world)
    _customer, order, line = _contract(db, org_id, output_id, quantity)
    contract_sync.sync_contract_demand(db, org_id)
    demand = db.query(PlanningDemand).filter(PlanningDemand.org_id == org_id, PlanningDemand.source == "contract").one()
    rows, _ = batch_service.plan_demand(db, org_id, demand.id, {}, today=TODAY)
    db.flush()
    return org_id, output_id, order, line, rows


def test_a_planned_order_has_a_planned_date_but_no_promise_until_materials_are_checked(db, demand_world):
    org_id, _out, order, line, rows = _planned_order(db, demand_world)
    assert rows and all(r.theoretical_ready_date for r in rows)
    dates = promise.dates_for_orders(db, org_id, [order])[str(order.id)]
    latest = max(r.theoretical_ready_date for r in rows)
    assert dates["planned_ready_date"] == latest.isoformat()
    assert dates["forecast_ready_date"] is None  # "Materials have not been checked" is still on the batches
    assert "not yet promised: Materials have not been checked" in dates["ready_reason"]


def test_once_no_batch_is_blocked_the_planned_date_becomes_the_forecast(db, demand_world):
    org_id, _out, order, _line, rows = _planned_order(db, demand_world)
    for row in rows:  # what a clean materials check and capacity placement leave behind
        row.status, row.blockers = "planned", []
    db.flush()
    dates = promise.dates_for_orders(db, org_id, [order])[str(order.id)]
    latest = max(r.theoretical_ready_date for r in rows)
    assert dates["forecast_ready_date"] == latest.isoformat() == dates["planned_ready_date"]
    assert dates["ready_reason"].startswith("Can be ready")
    one = rows[0]
    one.status, one.blockers = "blocked", ["Not enough materials to start"]
    db.flush()
    dates = promise.dates_for_orders(db, org_id, [order])[str(order.id)]
    assert dates["forecast_ready_date"] is None and "Not enough materials" in dates["ready_reason"]


def test_serialized_order_carries_the_dates_and_an_unplanned_order_says_so(db, demand_world):
    org_id, output_id, order, _line, _rows = _planned_order(db, demand_world)
    out = serialize_order(order, True, promise.dates_for_orders(db, org_id, [order])[str(order.id)])
    assert out["planned_ready_date"] and out["ready_reason"]
    _c, unplanned, _l = _contract(db, org_id, output_id, 100, status="draft")
    db.flush()
    dates = promise.dates_for_orders(db, org_id, [unplanned])[str(unplanned.id)]
    assert dates == {"planned_ready_date": None, "forecast_ready_date": None, "ready_reason": "Not planned yet"}
    assert serialize_order(unplanned)["ready_reason"] == "Not planned yet"


def test_cancelled_batches_do_not_count(db, demand_world):
    org_id, _out, order, _line, rows = _planned_order(db, demand_world)
    for row in rows:
        row.status = "cancelled"
    db.flush()
    dates = promise.dates_for_orders(db, org_id, [order])[str(order.id)]
    assert dates["planned_ready_date"] is None and dates["ready_reason"] == "Not planned yet"


def test_promise_from_stock_on_hand(db, demand_world):
    org_id, output_id, _ = _setup(db, demand_world)
    _stock(db, org_id, output_id, 700)
    result = promise.promise(db, org_id, {"source_output_id": str(output_id), "quantity": "600"}, today=TODAY)
    assert result["from"] == "stock" and result["ready_date"] == TODAY.isoformat()


def test_promise_from_the_workflow_timing_when_stock_is_short(db, demand_world):
    org_id, output_id, _ = _setup(db, demand_world)  # 250-bottle batches taking 2 days
    _stock(db, org_id, output_id, 100)
    result = promise.promise(db, org_id, {"source_output_id": str(output_id), "quantity": "600"}, today=TODAY)
    assert result["from"] == "plan"
    assert result["batches"] == 2  # 500 short at 250 a batch
    assert result["ready_date"] == (TODAY + timedelta(days=2)).isoformat()
    assert "Materials are checked when you plan it" in result["reason"]


@pytest.mark.parametrize("bad", ["0", "-5", "NaN", "lots", "Infinity"])
def test_promise_refuses_a_bad_quantity(db, demand_world, bad):
    org_id, output_id, _ = _setup(db, demand_world)
    with pytest.raises(ValueError):
        promise.promise(db, org_id, {"source_output_id": str(output_id), "quantity": bad}, today=TODAY)


def test_promise_needs_the_products_planning_settings(db, demand_world):
    org_id = demand_world[0]
    output_id = demand_world[2][org_id]
    with pytest.raises(ValueError, match="batch size and step timings"):
        promise.promise(db, org_id, {"source_output_id": str(output_id), "quantity": "10"}, today=TODAY)


def test_promise_never_reads_another_orgs_batches(db, demand_world):
    org_a, _out, order, _line, _rows = _planned_order(db, demand_world)
    other = demand_world[1]
    assert promise.dates_for_orders(db, other, [order])[str(order.id)]["planned_ready_date"] is None
    assert db.query(PlanningBatch).filter(PlanningBatch.org_id == org_a).count() > 0


def test_promise_endpoint_is_a_production_read():
    assert requirement_for("planning.get_promise", "GET") == "production.view"


def test_a_promise_places_every_batch_it_needs_on_capacity(db, demand_world):
    """!681 review: three batches on a one-unit still go on days 0, 1 and 2, so the promise is
    the last one's ready date, as plan_demand would schedule them."""
    from tests.features.planning import test_capacity_start_replan as cap

    org_id, output_id, _site = cap._setup(db, demand_world, units=1)
    result = promise.promise(db, org_id, {"source_output_id": str(output_id), "quantity": "750"}, today=TODAY)
    demand = cap._demand(db, org_id, output_id, 750, 2)  # due soon: planned as early as capacity allows
    rows, _ = batch_service.plan_demand(db, org_id, demand.id, {}, today=TODAY)
    planned_last = max(r.proposed_start_date for r in rows) + timedelta(days=int(rows[0].snapshot["elapsed_days"]))
    assert result["batches"] == 3
    assert result["ready_date"] == planned_last.isoformat()


def test_finished_and_cancelled_lines_dont_erase_an_orders_dates():
    """!681 review: an order takes the latest of its lines still to make."""
    from datetime import date
    from types import SimpleNamespace

    a, b, c = (SimpleNamespace(id=f"line-{n}") for n in "abc")
    order = SimpleNamespace(lines=[a, b, c])
    ready = date(2026, 11, 18)
    lines = {
        "line-a": {"planned": None, "forecast": None, "reason": "Made and finished", "done": "fulfilled"},
        "line-b": {"planned": ready, "forecast": ready, "reason": "Can be ready 18 Nov"},
        "line-c": {"planned": None, "forecast": None, "reason": "Not being planned", "done": "cancelled"},
    }
    out = promise.order_dates(order, lines)
    assert out["forecast_ready_date"] == "2026-11-18" == out["planned_ready_date"]
    finished = promise.order_dates(SimpleNamespace(lines=[a]), lines)
    assert finished["ready_reason"] == "Made and finished" and finished["planned_ready_date"] is None


def test_a_promise_too_large_to_place_says_plan_it_instead(db, demand_world):
    """!681 review follow-up: the batch loop is capped, so one request can't run for seconds."""
    from app.features.planning.material_adapter import MAX_BATCHES

    org_id, output_id, _ = _setup(db, demand_world)  # 250 a batch
    too_many = 250 * (MAX_BATCHES + 1)
    result = promise.promise(db, org_id, {"source_output_id": str(output_id), "quantity": str(too_many)}, today=TODAY)
    assert result["from"] == "too_large" and result["ready_date"] is None
    assert "plan it instead" in result["reason"]
