"""Material forecasts from explicit snapshots; no database or reservations."""

from dataclasses import replace
from datetime import date, datetime, timedelta
from decimal import Decimal, localcontext

import pytest

from app.features.planning.engine import BatchRule, Demand, PlannedBatch, StockKey, Supply, build_plan
from app.features.planning.materials import (
    MAX_BATCHES,
    MaterialRecipe,
    MaterialRequirement,
    MaterialSource,
    MaterialStatus,
    MaterialSupply,
    assess_materials,
)

TODAY = date(2026, 9, 28)
ORG = "producer-a"
OUTPUT = StockKey("gin-output", "bottles", "distillery")
INPUT = StockKey("juniper", "kg", "distillery")
OTHER_INPUT = StockKey("ethanol", "litres", "distillery")


def batch(identity="order-1", count=1, start=TODAY, days=2, key=OUTPUT, workflow="gin-workflow"):
    return PlannedBatch(
        identity, key, workflow, count, Decimal(250 * count), start, start + timedelta(days=days), False, ""
    )


def recipe(inputs=None, org=ORG, output=OUTPUT, workflow="gin-workflow"):
    return MaterialRecipe(
        org, workflow, output, tuple(inputs) if inputs is not None else (MaterialRequirement(INPUT, Decimal(5)),)
    )


def supply(identity="lot-1", quantity="5", ready=TODAY, expiry=None, key=INPUT, source=MaterialSource.ON_HAND, org=ORG):
    return MaterialSupply(org, Supply(identity, key, Decimal(quantity), ready, expiry), source)


def assess(batches=None, recipes=None, supplies=()):
    return assess_materials(
        (batch(),) if batches is None else tuple(batches),
        (recipe(),) if recipes is None else tuple(recipes),
        tuple(supplies),
        org_id=ORG,
        today=TODAY,
    )


def test_second_physical_batch_waits_for_known_receipt_without_overallocating():
    incoming = supply("delivery", "5", TODAY + timedelta(days=3), source=MaterialSource.INCOMING)
    stock = supply()
    result = assess(batches=(batch(count=2),), supplies=(stock, incoming))
    first, second = result.batches
    assert [row.batch_number for row in result.batches] == [1, 2]
    assert first.status is MaterialStatus.ON_TIME
    assert first.earliest_start_date == TODAY
    assert first.forecast_ready_date == TODAY + timedelta(days=2)
    assert second.status is MaterialStatus.DELAYED
    assert second.earliest_start_date == TODAY + timedelta(days=3)
    assert second.forecast_ready_date == TODAY + timedelta(days=5)
    assert second.shortages_at_start[0].quantity == 5
    assert second.allocations[0].source is MaterialSource.INCOMING
    assert any("juniper" in reason and "incoming" in reason and "delivery" in reason for reason in second.reasons)
    assert [row.quantity for row in result.balances] == [0, 0]
    assert stock.supply.quantity == incoming.supply.quantity == 5


def test_unknown_replenishment_blocks_second_batch_and_leaves_forecast_unknown():
    result = assess(batches=(batch(count=2),), supplies=(supply(quantity="7"),))
    first, second = result.batches
    assert first.status is MaterialStatus.ON_TIME
    assert second.status is MaterialStatus.BLOCKED
    assert second.earliest_start_date is None
    assert second.forecast_ready_date is None
    assert second.allocations == ()
    assert second.shortages_at_start[0].quantity == 3
    assert result.balances[0].quantity == 2
    assert "No common start date" in second.reasons[-1]


def test_build_plan_group_is_consumed_as_individual_batches():
    plan = build_plan(
        (Demand("order", OUTPUT, Decimal(500), TODAY + timedelta(days=2)),),
        (),
        (BatchRule(OUTPUT, "gin-workflow", Decimal(250), timedelta(days=2)),),
        today=TODAY,
    )
    result = assess(batches=plan.batches, supplies=(supply(),))
    assert len(result.batches) == 2
    assert [row.status for row in result.batches] == [MaterialStatus.ON_TIME, MaterialStatus.BLOCKED]


def test_preserves_caller_priority_order_even_when_ids_or_dates_sort_differently():
    result = assess(
        batches=(batch("z-high-priority", start=TODAY + timedelta(days=1)), batch("a-low-priority")),
        supplies=(supply(),),
    )
    assert [row.demand_id for row in result.batches] == ["z-high-priority", "a-low-priority"]
    assert result.batches[0].status is MaterialStatus.ON_TIME
    assert result.batches[1].status is MaterialStatus.BLOCKED


def test_failed_multi_material_batch_allocates_nothing_so_later_batch_can_use_stock():
    multi = recipe(inputs=(MaterialRequirement(INPUT, Decimal(5)), MaterialRequirement(OTHER_INPUT, Decimal(1))))
    simple = recipe(workflow="simple")
    result = assess(
        batches=(batch("blocked"), batch("later", workflow="simple")),
        recipes=(multi, simple),
        supplies=(supply(),),
    )
    assert result.batches[0].status is MaterialStatus.BLOCKED
    assert result.batches[0].allocations == ()
    assert result.batches[0].shortages_at_start[0].key == OTHER_INPUT
    assert result.batches[1].status is MaterialStatus.ON_TIME
    assert result.batches[1].allocations[0].quantity == 5
    assert result.balances[0].quantity == 0


def test_infeasible_trials_do_not_use_stock_before_final_common_start():
    multi = recipe(inputs=(MaterialRequirement(INPUT, Decimal(5)), MaterialRequirement(OTHER_INPUT, Decimal(1))))
    arrival = TODAY + timedelta(days=2)
    result = assess(
        recipes=(multi,),
        supplies=(supply(), supply("ethanol", "1", arrival, key=OTHER_INPUT, source=MaterialSource.INCOMING)),
    )
    assert result.batches[0].earliest_start_date == arrival
    assert [row.quantity for row in result.batches[0].allocations] == [5, 1]
    assert [row.quantity for row in result.balances] == [0, 0]


def test_no_common_material_window_blocks_instead_of_guessing_latest_arrival():
    multi = recipe(inputs=(MaterialRequirement(INPUT, Decimal(5)), MaterialRequirement(OTHER_INPUT, Decimal(1))))
    result = assess(
        recipes=(multi,),
        supplies=(
            supply(expiry=TODAY),
            supply("ethanol", "1", TODAY + timedelta(days=1), key=OTHER_INPUT, source=MaterialSource.INCOMING),
        ),
    )
    assert result.batches[0].status is MaterialStatus.BLOCKED
    assert result.batches[0].forecast_ready_date is None
    assert [row.quantity for row in result.balances] == [5, 1]


@pytest.mark.parametrize(
    "ready_offset,expiry_offset,expected",
    [(0, 0, MaterialStatus.ON_TIME), (1, 1, MaterialStatus.DELAYED), (-2, -1, MaterialStatus.BLOCKED)],
)
def test_ready_and_expiry_days_are_inclusive(ready_offset, expiry_offset, expected):
    result = assess(
        supplies=(supply(ready=TODAY + timedelta(days=ready_offset), expiry=TODAY + timedelta(days=expiry_offset)),)
    )
    assert result.batches[0].status is expected
    if expected is not MaterialStatus.BLOCKED:
        assert result.batches[0].earliest_start_date == TODAY + timedelta(days=ready_offset)


def test_fefo_filters_future_and_expired_lots_before_ordering_eligible_lots():
    result = assess(
        supplies=(
            supply("never-expires"),
            supply("future", ready=TODAY + timedelta(days=1), expiry=TODAY + timedelta(days=1)),
            supply("expires-today", quantity="2", expiry=TODAY),
            supply("expired", ready=TODAY - timedelta(days=2), expiry=TODAY - timedelta(days=1)),
            supply("expires-later", quantity="4", expiry=TODAY + timedelta(days=2)),
        )
    )
    assert [(row.supply_id, row.quantity) for row in result.batches[0].allocations] == [
        ("expires-today", 2),
        ("expires-later", 3),
    ]
    assert [row.quantity for row in result.balances] == [5, 5, 0, 5, 1]


def test_equal_expiry_breaks_ties_by_readiness_then_identity_independent_of_input_order():
    lots = (
        supply("z", expiry=TODAY),
        supply("a", expiry=TODAY),
        supply("older", ready=TODAY - timedelta(days=1), expiry=TODAY),
    )
    assert assess(supplies=lots).batches[0].allocations == assess(supplies=tuple(reversed(lots))).batches[0].allocations
    assert assess(supplies=lots).batches[0].allocations[0].supply_id == "older"
    assert assess(supplies=lots[:2]).batches[0].allocations[0].supply_id == "a"


def test_past_start_checks_current_eligibility_and_preserves_duration():
    result = assess(batches=(batch(start=TODAY - timedelta(days=5), days=3),), supplies=(supply(),))
    row = result.batches[0]
    assert row.status is MaterialStatus.DELAYED
    assert row.checked_start_date == row.earliest_start_date == TODAY
    assert row.forecast_ready_date == TODAY + timedelta(days=3)
    assert any("Requested start has passed" in reason for reason in row.reasons)
    expired = assess(
        batches=(batch(start=TODAY - timedelta(days=5)),),
        supplies=(supply(ready=TODAY - timedelta(days=5), expiry=TODAY - timedelta(days=1)),),
    )
    assert expired.batches[0].status is MaterialStatus.BLOCKED


@pytest.mark.parametrize(
    "different_key",
    [
        replace(INPUT, product_id="other"),
        replace(INPUT, unit="grams"),
        replace(INPUT, site_id="warehouse"),
        replace(INPUT, owner_id="customer-a"),
        replace(INPUT, site_id=None),
    ],
)
def test_exact_product_owner_site_and_unit_required(different_key):
    result = assess(supplies=(supply(key=different_key),))
    assert result.batches[0].status is MaterialStatus.BLOCKED
    assert result.balances[0].quantity == 5


def test_customer_owned_input_cannot_use_producer_or_other_customer_stock():
    owned = replace(INPUT, owner_id="customer-a")
    required = recipe(inputs=(MaterialRequirement(owned, Decimal(5)),))
    result = assess(
        recipes=(required,), supplies=(supply(), supply("other", key=replace(INPUT, owner_id="customer-b")))
    )
    assert result.batches[0].status is MaterialStatus.BLOCKED
    assert all(row.quantity == 5 for row in result.balances)


@pytest.mark.parametrize("source", list(MaterialSource))
def test_only_explicit_supply_types_are_used_and_provenance_is_retained(source):
    result = assess(supplies=(supply(ready=TODAY + timedelta(days=1), source=source),))
    assert result.batches[0].status is MaterialStatus.DELAYED
    assert result.batches[0].allocations[0].source is source
    assert source.value in result.batches[0].reasons[-1]


def test_planned_output_never_becomes_implicit_supply_for_another_batch():
    downstream = recipe(workflow="downstream", inputs=(MaterialRequirement(OUTPUT, Decimal(1)),))
    result = assess(
        batches=(batch(), batch("dependent", workflow="downstream")),
        recipes=(recipe(), downstream),
        supplies=(supply(),),
    )
    assert result.batches[0].status is MaterialStatus.ON_TIME
    assert result.batches[1].status is MaterialStatus.BLOCKED
    assert result.batches[1].forecast_ready_date is None


def test_missing_recipe_blocks_but_explicit_empty_recipe_needs_no_materials():
    unknown = assess(recipes=())
    assert unknown.batches[0].status is MaterialStatus.BLOCKED
    assert unknown.batches[0].forecast_ready_date is None
    assert "recipe is unknown" in unknown.batches[0].reasons[0]
    assert assess(recipes=(recipe(inputs=()),)).batches[0].status is MaterialStatus.ON_TIME
    wrong_workflow = assess(recipes=(recipe(workflow="other"),), supplies=(supply(),))
    wrong_output = assess(recipes=(recipe(output=replace(OUTPUT, owner_id="customer")),), supplies=(supply(),))
    assert wrong_workflow.batches[0].status is wrong_output.batches[0].status is MaterialStatus.BLOCKED


def test_duplicate_input_rows_are_aggregated_without_overallocation():
    required = recipe(inputs=(MaterialRequirement(INPUT, Decimal(3)), MaterialRequirement(INPUT, Decimal(4))))
    result = assess(recipes=(required,), supplies=(supply(quantity="6"),))
    assert result.batches[0].shortages_at_start[0].quantity == 1
    assert result.batches[0].status is MaterialStatus.BLOCKED
    assert result.balances[0].quantity == 6


def test_decimal_arithmetic_is_exact_even_under_low_caller_precision():
    qty = Decimal("99999999999999.9999")
    required = recipe(inputs=(MaterialRequirement(INPUT, qty), MaterialRequirement(INPUT, Decimal("0.0001"))))
    lots = (supply(quantity="100000000000000.0001"),)
    with localcontext() as context:
        context.prec = 3
        result = assess(recipes=(required,), supplies=lots)
        assert context.prec == 3
    assert result.batches[0].allocations[0].quantity == Decimal("100000000000000.0000")
    assert result.balances[0].quantity == Decimal("0.0001")


def test_repeated_assessment_does_not_mutate_snapshots_or_reserve_stock():
    rows = (supply(),)
    batches = (batch(),)
    required = (recipe(),)
    first = assess(batches, required, rows)
    assert first == assess(batches, required, rows)
    assert rows[0].supply.quantity == 5
    assert batches[0].start_date == TODAY
    assert required[0].inputs[0].quantity == 5
    assert assess(batches=(), supplies=rows).balances[0].quantity == 5


def test_calendar_overflow_is_blocked_and_allocates_nothing():
    arrival = supply(ready=date.max, source=MaterialSource.INCOMING)
    result = assess(supplies=(arrival,))
    assert result.batches[0].status is MaterialStatus.BLOCKED
    assert result.batches[0].forecast_ready_date is None
    assert "supported calendar" in result.batches[0].reasons[-1]
    assert result.balances[0].quantity == 5


@pytest.mark.parametrize("bad_quantity", [Decimal("NaN"), Decimal("sNaN"), Decimal("Infinity"), Decimal("-1"), 5.0])
def test_invalid_supply_quantity_fails_closed(bad_quantity):
    invalid = replace(supply(), supply=replace(supply().supply, quantity=bad_quantity))
    with pytest.raises(ValueError):
        assess(supplies=(invalid,))


@pytest.mark.parametrize("bad_quantity", [Decimal(0), Decimal(-1), Decimal("NaN"), Decimal("Infinity"), "5"])
def test_invalid_per_batch_recipe_quantity_fails_closed(bad_quantity):
    with pytest.raises(ValueError):
        assess(recipes=(recipe(inputs=(MaterialRequirement(INPUT, bad_quantity),)),))


@pytest.mark.parametrize(
    "invalid_batch",
    [
        replace(batch(), batch_count=True),
        replace(batch(), batch_count=0),
        replace(batch(), batch_count=-1),
        replace(batch(), batch_count=1.5),
        replace(batch(), batch_count=MAX_BATCHES + 1),
        replace(batch(), quantity=Decimal(0)),
        replace(batch(), ready_date=TODAY - timedelta(days=1)),
        replace(batch(), start_date=datetime(2026, 9, 28)),
        replace(batch(), key=replace(OUTPUT, unit=" ")),
        replace(batch(), key="gin-output"),
        replace(batch(), demand_id=""),
        replace(batch(), workflow_id=" gin-workflow"),
    ],
)
def test_invalid_batch_snapshot_is_rejected(invalid_batch):
    with pytest.raises(ValueError):
        assess(batches=(invalid_batch,))


@pytest.mark.parametrize(
    "invalid_supply",
    [
        supply(org="producer-b"),
        supply(source="incoming"),
        supply(ready=None),
        supply(ready=TODAY, expiry=TODAY - timedelta(days=1)),
        supply(key=replace(INPUT, owner_id="")),
        supply(key=replace(INPUT, site_id=" ")),
        supply(identity=""),
    ],
)
def test_invalid_or_cross_tenant_supply_snapshot_is_rejected(invalid_supply):
    with pytest.raises(ValueError):
        assess(supplies=(invalid_supply,))


def test_ambiguous_duplicate_identities_and_cross_tenant_recipe_fail_closed():
    with pytest.raises(ValueError, match="another organisation"):
        assess(recipes=(recipe(org="producer-b"),))
    with pytest.raises(ValueError, match="Ambiguous"):
        assess(recipes=(recipe(), recipe()))
    with pytest.raises(ValueError, match="Duplicate material supply"):
        assess(supplies=(supply(), supply(source=MaterialSource.INCOMING)))
    with pytest.raises(ValueError, match="Duplicate planned demand"):
        assess(batches=(batch(), batch()))
    with pytest.raises(ValueError, match="Too many"):
        assess(batches=(batch("first", count=MAX_BATCHES), batch("second")))
    with pytest.raises(ValueError, match="normalized"):
        assess_materials((), (), (), org_id="", today=TODAY)
    with pytest.raises(ValueError, match="day-level"):
        assess_materials((), (), (), org_id=ORG, today=datetime(2026, 9, 28))


def test_zero_balance_supply_cannot_satisfy_an_input_or_create_an_allocation():
    result = assess(supplies=(supply(quantity="0"),))
    assert result.batches[0].status is MaterialStatus.BLOCKED
    assert result.batches[0].allocations == ()
    assert result.balances[0].quantity == 0
