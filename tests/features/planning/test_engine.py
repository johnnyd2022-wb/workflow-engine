"""Pure planning arithmetic; no inventory writes or external services."""

from datetime import date, timedelta
from decimal import Decimal

import pytest

from app.features.planning.engine import (
    BatchRule,
    Demand,
    StepTiming,
    StockKey,
    Supply,
    build_plan,
    workflow_duration,
)

TODAY = date(2026, 9, 28)
KEY = StockKey("gin-output-uuid", "bottles", "distillery", None)


def demand(identity="order-1", quantity="600", due=TODAY + timedelta(days=10), key=KEY):
    return Demand(identity, key, Decimal(quantity), due)


def supply(identity="lot-1", quantity="100", ready=TODAY, expires=None, key=KEY):
    return Supply(identity, key, Decimal(quantity), ready, expires)


def rule(quantity="250", days=7, key=KEY):
    return BatchRule(key, "gin-workflow", Decimal(quantity), timedelta(days=days))


def test_net_requirements_round_batches_and_plan_backwards():
    result = build_plan((demand(),), (supply(),), (rule(),), today=TODAY)
    position = result.positions[0]
    assert position.supplied_quantity == Decimal(100)
    assert position.shortfall == Decimal(500)
    assert position.planned_quantity == Decimal(500)
    assert position.unplanned_quantity == 0
    batch = result.batches[0]
    assert batch.batch_count == 2
    assert batch.start_date == TODAY + timedelta(days=3)
    assert batch.ready_date == TODAY + timedelta(days=10)
    assert not batch.late


def test_impossible_due_date_forecasts_forward_with_reason():
    result = build_plan((demand(due=TODAY + timedelta(days=2)),), (), (rule(),), today=TODAY)
    batch = result.batches[0]
    assert batch.start_date == TODAY
    assert batch.ready_date == TODAY + timedelta(days=7)
    assert batch.late
    assert "earliest start is today" in batch.reason


def test_supply_is_not_double_allocated_to_orders():
    result = build_plan(
        (demand("second", "3"), demand("first", "3", due=TODAY + timedelta(days=1))),
        (supply(quantity="5"),),
        (),
        today=TODAY,
    )
    assert [row.demand_id for row in result.positions] == ["first", "second"]
    assert [row.supplied_quantity for row in result.positions] == [Decimal(3), Decimal(2)]
    assert result.positions[1].unplanned_quantity == Decimal(1)


def test_stock_and_known_wip_reduce_requirements_only_when_ready():
    result = build_plan(
        (demand(quantity="600"),),
        (supply("stock", "100"), supply("wip", "500", TODAY + timedelta(days=9))),
        (rule(),),
        today=TODAY,
    )
    assert not result.batches
    assert result.positions[0].shortfall == 0
    unavailable = build_plan(
        (demand(quantity="600"),),
        (supply("late-wip", "600", TODAY + timedelta(days=11)),),
        (rule(),),
        today=TODAY,
    )
    assert unavailable.positions[0].shortfall == Decimal(600)


def test_first_expiring_supply_is_consumed_first():
    result = build_plan(
        (demand("first", "3", due=TODAY + timedelta(days=1)), demand("second", "3")),
        (supply("long-life", "3"), supply("expires", "3", expires=TODAY + timedelta(days=2))),
        (),
        today=TODAY,
    )
    assert [row.shortfall for row in result.positions] == [Decimal(0), Decimal(0)]


@pytest.mark.parametrize(
    "different_key",
    [
        StockKey(KEY.product_id, KEY.unit, "warehouse"),
        StockKey(KEY.product_id, KEY.unit, KEY.site_id, "customer-a"),
        StockKey(KEY.product_id, "cases", KEY.site_id),
        StockKey("other-product", KEY.unit, KEY.site_id),
    ],
)
def test_incompatible_stock_never_substitutes(different_key):
    result = build_plan((demand(quantity="5"),), (supply(key=different_key),), (), today=TODAY)
    assert result.positions[0].unplanned_quantity == Decimal(5)


def test_expired_supply_never_used_even_for_an_overdue_order():
    result = build_plan(
        (demand(quantity="5", due=TODAY - timedelta(days=1)),),
        (supply(ready=TODAY - timedelta(days=3), expires=TODAY - timedelta(days=1)),),
        (),
        today=TODAY,
    )
    assert result.positions[0].unplanned_quantity == Decimal(5)


def test_planned_surplus_available_only_after_ready_date():
    result = build_plan(
        (
            demand("first", "3", due=TODAY),
            demand("early", "2", due=TODAY + timedelta(days=1)),
            demand("later", "2", due=TODAY + timedelta(days=10)),
        ),
        (),
        (rule(quantity="5", days=7),),
        today=TODAY,
    )
    assert [row.shortfall for row in result.positions] == [Decimal(3), Decimal(2), Decimal(0)]
    assert len(result.batches) == 2


def test_subday_workflow_rounds_up_not_down():
    short = BatchRule(KEY, "workflow", Decimal(1), timedelta(seconds=1))
    result = build_plan((demand(quantity="1", due=TODAY),), (), (short,), today=TODAY)
    assert result.batches[0].ready_date == TODAY + timedelta(days=1)


def test_parallel_workflow_duration_is_critical_path_including_wait():
    steps = (
        StepTiming("start", timedelta(hours=2)),
        StepTiming("short", timedelta(hours=1), predecessors=("start",)),
        StepTiming("long", timedelta(hours=3), timedelta(days=7), ("start",)),
        StepTiming("join", timedelta(hours=1), predecessors=("short", "long")),
    )
    assert workflow_duration(steps) == timedelta(days=7, hours=6)
    assert workflow_duration(tuple(reversed(steps))) == workflow_duration(steps)


@pytest.mark.parametrize(
    "steps",
    [
        (StepTiming("a", timedelta(), predecessors=("missing",)),),
        (StepTiming("a", timedelta(), predecessors=("a",)),),
        (StepTiming("a", timedelta()), StepTiming("a", timedelta())),
        (StepTiming("a", timedelta(days=-1)),),
    ],
)
def test_invalid_workflows_fail_explicitly(steps):
    with pytest.raises(ValueError):
        workflow_duration(steps)


@pytest.mark.parametrize("bad", ["NaN", "Infinity", "-1", "0"])
def test_invalid_demand_or_batch_sizes_fail_explicitly(bad):
    with pytest.raises(ValueError):
        build_plan((demand(quantity=bad),), (), (rule(),), today=TODAY)
    with pytest.raises(ValueError):
        build_plan((demand(),), (), (rule(quantity=bad),), today=TODAY)


def test_duplicate_input_ids_cannot_double_count_stock_or_demand():
    with pytest.raises(ValueError):
        build_plan((demand(), demand()), (), (), today=TODAY)
    with pytest.raises(ValueError):
        build_plan((demand(),), (supply(), supply()), (), today=TODAY)
    with pytest.raises(ValueError):
        build_plan((demand(),), (), (rule(), rule()), today=TODAY)


def test_planning_does_not_mutate_input_supply():
    stock = supply(quantity="5")
    first = build_plan((demand(quantity="3"),), (stock,), (), today=TODAY)
    second = build_plan((demand(quantity="3"),), (stock,), (), today=TODAY)
    assert first == second
    assert stock.quantity == Decimal(5)
