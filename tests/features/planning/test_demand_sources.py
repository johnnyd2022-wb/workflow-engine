"""GL-P07 B3: contract demand sync, stock-cover forecast, stock targets and netting."""

from datetime import date, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest

from app.core.db.models.audit_log import AuditLog
from app.core.db.models.execution_step import ExecutionStep
from app.core.db.models.feature_subscription import FeatureSubscription
from app.core.db.models.organisation import Organisation
from app.core.db.models.process_version import ProcessVersion
from app.core.db.models.site import Site
from app.core.db.models.step import Step
from app.core.db.models.user import UserRole
from app.core.db.repositories.execution_repo import ExecutionRepository
from app.core.db.repositories.inventory_repo import InventoryRepository
from app.core.db.repositories.user_repo import UserRepository
from app.core.security.access_policy import requirement_for
from app.core.security.auth_service import AuthService
from app.features.contract_manufacturing.models import ContractCustomer, ContractOrder, ContractOrderLine
from app.features.crm.models.product_mapping import ProductMapping
from app.features.crm.services import sales_sources
from app.features.crm.services.sales_sources import SaleLine
from app.features.planning import batch_service, contract_sync, demand_service, forecast_service
from app.features.planning.batch_models import PlanningBatch
from app.features.planning.engine import BatchRule, Demand, StockKey, Supply, build_plan
from app.features.planning.models import PlanningDemand, PlanningStockTarget
from tests.factories import DEFAULT_TEST_PASSWORD
from tests.features.planning import test_batches as batch_fixtures
from tests.features.planning import test_demand as demand_fixtures

flask_app = demand_fixtures.flask_app
base_demand_world = demand_fixtures.demand_world
demand_world = batch_fixtures.demand_world
demand_clients = demand_fixtures.demand_clients
payload = demand_fixtures.payload

TODAY = date.today()


def _day(value):
    return f"{value.day} {value:%b}" + (f" {value.year}" if value.year != TODAY.year else "")


def _setup(db, world, org_index=0):
    """A 250-bottle batch setting taking 2 days (60 min work + 2820 min wait)."""
    org_id = world[org_index]
    output_id = world[2][org_id]
    step = db.query(Step).filter(Step.org_id == org_id).first()
    batch_fixtures.native_recipe(db, org_id, step.process_id)
    batch_service.save_setting(db, org_id, step.process_id, batch_fixtures.setting_payload(db, org_id, output_id))
    return org_id, output_id, step


def _stock(db, org_id, output_id, quantity, **extra):
    """A finished lot made by a real execution step of the org's workflow. `forged_output`
    then stamps another output id on it (a hostile row, written past the repository's check)."""
    forged = extra.pop("forged_output", None)
    step = db.query(Step).filter(Step.org_id == org_id).first()
    execution = ExecutionRepository(db).create_execution(
        org_id, step.process_id, commit=False, site_id=extra.get("site_id")
    )
    execution_step = (
        db.query(ExecutionStep)
        .filter(ExecutionStep.org_id == org_id, ExecutionStep.execution_id == execution.id)
        .first()
    )
    item = InventoryRepository(db).create_inventory_item(
        org_id=org_id,
        name="Gin",
        quantity=str(quantity),
        unit="bottles",
        inventory_type="final_product",
        source_execution_id=execution.id,
        source_execution_step_id=execution_step.id,
        source_output_id=output_id,
        commit=False,
        **extra,
    )
    if forged is not None:
        item.source_output_id = forged
    db.flush()
    return item


def _demand(db, org_id, output_id, quantity, due_in_days, reference="ORDER"):
    return demand_service.create_demand(
        db,
        org_id,
        payload(
            output_id,
            reference=reference,
            quantity=str(quantity),
            due_date=(TODAY + timedelta(days=due_in_days)).isoformat(),
            priority=0,
        ),
    )


# --- engine -------------------------------------------------------------------------------


def test_engine_plan_for_nets_others_first_but_plans_only_the_chosen_demand():
    key = StockKey("gin", "bottles")
    rule = BatchRule(key, "wf", Decimal(250), timedelta(days=2))
    demands = (
        Demand("early", key, Decimal(300), TODAY + timedelta(days=5)),
        Demand("late", key, Decimal(300), TODAY + timedelta(days=9)),
    )
    stock = (Supply("lot", key, Decimal(200), TODAY),)
    plan = build_plan(demands, stock, (rule,), today=TODAY, plan_for=frozenset({"late"}))
    # The earlier demand took the stock and, unplanned, left no surplus: the later one is
    # planned for all of its 300.
    assert [(row.demand_id, row.quantity) for row in plan.batches] == [("late", Decimal(500))]
    early = next(row for row in plan.positions if row.demand_id == "early")
    assert early.supplied_quantity == Decimal(200) and early.planned_quantity == 0


# --- netting ------------------------------------------------------------------------------


def test_a_demand_covered_by_stock_on_hand_plans_no_batches(db, demand_world):
    org_id, output_id, _ = _setup(db, demand_world)
    _stock(db, org_id, output_id, 600)
    demand = _demand(db, org_id, output_id, 600, 5)
    rows, changed = batch_service.plan_demand(db, org_id, demand.id, {}, today=TODAY)
    assert rows == [] and not changed
    assert db.query(PlanningBatch).filter(PlanningBatch.org_id == org_id).count() == 0


@pytest.mark.parametrize(("on_hand", "batches", "covered"), [(100, 2, "100"), (0, 3, "0")])
def test_a_demand_only_plans_its_shortfall(db, demand_world, on_hand, batches, covered):
    org_id, output_id, _ = _setup(db, demand_world)
    if on_hand:
        _stock(db, org_id, output_id, on_hand)
    demand = _demand(db, org_id, output_id, 600, 5)
    rows, changed = batch_service.plan_demand(db, org_id, demand.id, {}, today=TODAY)
    assert changed and len(rows) == batches
    assert Decimal(rows[0].snapshot["covered_quantity"]) == Decimal(covered)
    assert Decimal(rows[0].snapshot["shortfall_quantity"]) == Decimal(600 - on_hand)


def test_held_expired_and_other_org_stock_is_never_counted(db, demand_world):
    org_id, output_id, _ = _setup(db, demand_world)
    other_org = demand_world[1]
    _stock(db, org_id, output_id, 600, extra_data={"on_hold": True})
    _stock(db, org_id, output_id, 600, expiry_date=TODAY - timedelta(days=1))
    # A hostile row in another org naming this org's output id.
    _stock(db, other_org, demand_world[2][other_org], 600, forged_output=output_id)
    demand = _demand(db, org_id, output_id, 600, 5)
    rows, _ = batch_service.plan_demand(db, org_id, demand.id, {}, today=TODAY)
    assert len(rows) == 3


def test_a_lot_under_a_quality_hold_is_not_stock_until_released(db, demand_world):
    from app.core.services.lot_holds import place_hold, release_hold

    org_id, output_id, _ = _setup(db, demand_world)
    lot = _stock(db, org_id, output_id, 600)
    (hold,) = place_hold(db, org_id, lot.id, "Off taste in QC", None)
    db.flush()
    demand = _demand(db, org_id, output_id, 600, 5)
    rows, _ = batch_service.plan_demand(db, org_id, demand.id, {}, today=TODAY)
    assert len(rows) == 3
    for row in rows:
        row.status = "cancelled"
    release_hold(db, org_id, hold.id, "Retested fine", None)
    db.flush()
    rows, changed = batch_service.plan_demand(db, org_id, demand.id, {}, today=TODAY)
    assert rows == [] and not changed


def test_earlier_due_demand_takes_the_stock_first(db, demand_world):
    org_id, output_id, _ = _setup(db, demand_world)
    _stock(db, org_id, output_id, 300)
    early = _demand(db, org_id, output_id, 300, 10, "EARLY")
    late = _demand(db, org_id, output_id, 300, 20, "LATE")
    rows, _ = batch_service.plan_demand(db, org_id, late.id, {}, today=TODAY)
    assert len(rows) == 2  # the 300 on hand is the earlier order's
    rows, changed = batch_service.plan_demand(db, org_id, early.id, {}, today=TODAY)
    assert rows == [] and not changed


def test_batches_already_planned_for_another_demand_count_as_supply(db, demand_world):
    org_id, output_id, _ = _setup(db, demand_world)
    first = _demand(db, org_id, output_id, 300, 10, "FIRST")
    rows, _ = batch_service.plan_demand(db, org_id, first.id, {}, today=TODAY)
    assert sum(row.quantity for row in rows) == Decimal(500)
    second = _demand(db, org_id, output_id, 200, 20, "SECOND")
    rows, changed = batch_service.plan_demand(db, org_id, second.id, {}, today=TODAY)
    assert rows == [] and not changed  # the first plan's 200 surplus covers it


def test_contract_demand_is_not_met_from_the_producers_own_stock(db, demand_world):
    org_id, output_id, _ = _setup(db, demand_world)
    _stock(db, org_id, output_id, 600)
    customer, _order, _line = _contract(db, org_id, output_id, 600)
    contract_sync.sync_contract_demand(db, org_id)
    demand = db.query(PlanningDemand).filter(PlanningDemand.org_id == org_id, PlanningDemand.source == "contract").one()
    rows, _ = batch_service.plan_demand(db, org_id, demand.id, {}, today=TODAY)
    assert len(rows) == 3
    # The same customer's other line nets against this line's planned surplus (750 - 600).
    line2 = ContractOrderLine(
        org_id=org_id,
        order_id=_order.id,
        product_name="Gin",
        quantity=Decimal(150),
        unit="bottles",
        materials_source="producer",
        source_output_id=output_id,
    )
    db.add(line2)
    db.flush()
    db.expire(_order)  # a new request would load the order's lines afresh
    # The producer's own order, due the same day and more urgent, is no rival for that surplus.
    demand_service.create_demand(
        db, org_id, payload(output_id, quantity="150", due_date=_order.due_date.isoformat(), priority=90)
    )
    contract_sync.sync_contract_demand(db, org_id)
    second = (
        db.query(PlanningDemand)
        .filter(PlanningDemand.org_id == org_id, PlanningDemand.source_ref == str(line2.id))
        .one()
    )
    rows, changed = batch_service.plan_demand(db, org_id, second.id, {}, today=TODAY)
    assert rows == [] and not changed
    # Another customer's order gets nothing from it.
    _, _, line3 = _contract(db, org_id, output_id, 100)
    contract_sync.sync_contract_demand(db, org_id)
    third = (
        db.query(PlanningDemand)
        .filter(PlanningDemand.org_id == org_id, PlanningDemand.source_ref == str(line3.id))
        .one()
    )
    rows, _ = batch_service.plan_demand(db, org_id, third.id, {}, today=TODAY)
    assert len(rows) == 1


# --- contract sync ------------------------------------------------------------------------


def _contract(db, org_id, output_id, quantity, *, status="confirmed", unit="bottles", due_in_days=14):
    customer = ContractCustomer(org_id=org_id, name=f"Brand {uuid4()}")
    db.add(customer)
    db.flush()
    order = ContractOrder(
        org_id=org_id,
        customer_id=customer.id,
        reference=f"PO-{uuid4().hex[:6]}",
        due_date=TODAY + timedelta(days=due_in_days),
        status=status,
        duty_responsibility="producer_licensee",
    )
    db.add(order)
    db.flush()
    line = ContractOrderLine(
        org_id=org_id,
        order_id=order.id,
        product_name="Gin",
        quantity=Decimal(quantity),
        unit=unit,
        materials_source="producer",
        source_output_id=output_id,
    )
    db.add(line)
    db.flush()
    return customer, order, line


def _synced(db, org_id):
    return db.query(PlanningDemand).filter(PlanningDemand.org_id == org_id, PlanningDemand.source == "contract").all()


def test_a_confirmed_line_becomes_one_demand_and_a_resync_changes_nothing(db, demand_world):
    org_id, output_id, _ = _setup(db, demand_world)
    _, order, line = _contract(db, org_id, output_id, 600)
    _contract(db, org_id, output_id, 50, status="draft")
    result = contract_sync.sync_contract_demand(db, org_id)
    assert contract_sync.summary(result)["changes"] == {"created": 1}
    (row,) = _synced(db, org_id)
    assert (row.source_ref, row.quantity, row.unit, row.due_date, row.status) == (
        str(line.id),
        Decimal(600),
        "bottles",
        order.due_date,
        "open",
    )
    assert row.reference == f"{order.reference} · Gin"
    assert contract_sync.sync_contract_demand(db, org_id)["changes"] == []
    assert len(_synced(db, org_id)) == 1


def test_lines_without_a_workflow_output_are_listed_never_matched_by_name(db, demand_world):
    org_id, output_id, _ = _setup(db, demand_world)
    _contract(db, org_id, None, 10)
    _contract(db, org_id, output_id, 10, unit="kg")
    result = contract_sync.sync_contract_demand(db, org_id)
    assert _synced(db, org_id) == []
    reasons = sorted(row["reason"] for row in result["unmapped"])
    assert reasons == [
        "Choose the workflow output this product is made by",
        "Ordered in kg, which can't be counted as bottles",
    ]


def test_a_changed_line_updates_its_demand_and_drops_unstarted_batches(db, demand_world):
    org_id, output_id, _ = _setup(db, demand_world)
    _, order, line = _contract(db, org_id, output_id, 600)
    contract_sync.sync_contract_demand(db, org_id)
    (demand,) = _synced(db, org_id)
    rows, _ = batch_service.plan_demand(db, org_id, demand.id, {}, today=TODAY)
    line.quantity = Decimal(200)
    order.due_date = TODAY + timedelta(days=30)
    db.flush()
    result = contract_sync.sync_contract_demand(db, org_id)
    assert contract_sync.summary(result)["changes"] == {"updated": 1}
    assert demand.quantity == Decimal(200) and demand.due_date == TODAY + timedelta(days=30)
    assert {row.status for row in rows} == {"cancelled"}


def test_a_changed_line_leaves_a_started_demand_alone_and_says_why(db, demand_world):
    org_id, output_id, step = _setup(db, demand_world)
    _, _, line = _contract(db, org_id, output_id, 600)
    contract_sync.sync_contract_demand(db, org_id)
    (demand,) = _synced(db, org_id)
    rows, _ = batch_service.plan_demand(db, org_id, demand.id, {}, today=TODAY)
    execution = ExecutionRepository(db).create_execution(org_id, step.process_id, commit=False)
    rows[0].execution_id, rows[0].status = execution.id, "started"
    line.quantity = Decimal(900)
    db.flush()
    result = contract_sync.sync_contract_demand(db, org_id)
    assert result["changes"] == []
    assert demand.quantity == Decimal(600)
    assert "batch has started" in demand.source_note
    assert result["held"][0]["demand_id"] == str(demand.id)
    assert {row.status for row in rows[1:]} == {"blocked"}


def test_an_order_that_is_no_longer_confirmed_cancels_and_reconfirming_reopens(db, demand_world):
    org_id, output_id, _ = _setup(db, demand_world)
    _, order, _ = _contract(db, org_id, output_id, 600)
    contract_sync.sync_contract_demand(db, org_id)
    (demand,) = _synced(db, org_id)
    rows, _ = batch_service.plan_demand(db, org_id, demand.id, {}, today=TODAY)
    order.status = "draft"
    db.flush()
    assert contract_sync.summary(contract_sync.sync_contract_demand(db, org_id))["changes"] == {"cancelled": 1}
    assert demand.status == "cancelled" and demand.source_note == contract_sync.NOT_CONFIRMED
    assert {row.status for row in rows} == {"cancelled"}
    order.status = "confirmed"
    db.flush()
    assert contract_sync.summary(contract_sync.sync_contract_demand(db, org_id))["changes"] == {"reopened": 1}
    assert demand.status == "open" and demand.source_note is None


def test_a_demand_cancelled_in_the_planner_stays_cancelled(db, demand_world):
    org_id, output_id, _ = _setup(db, demand_world)
    _contract(db, org_id, output_id, 600)
    contract_sync.sync_contract_demand(db, org_id)
    (demand,) = _synced(db, org_id)
    demand_service.cancel_demand(db, org_id, demand.id)
    assert contract_sync.sync_contract_demand(db, org_id)["changes"] == []
    assert demand.status == "cancelled"


def test_a_completed_order_fulfils_its_demand(db, demand_world):
    org_id, output_id, _ = _setup(db, demand_world)
    _, order, _ = _contract(db, org_id, output_id, 600)
    contract_sync.sync_contract_demand(db, org_id)
    order.status = "completed"
    db.flush()
    assert contract_sync.summary(contract_sync.sync_contract_demand(db, org_id))["changes"] == {"fulfilled": 1}
    assert _synced(db, org_id)[0].status == "fulfilled"


def test_contract_sync_never_reads_another_orgs_orders(db, demand_world):
    org_id, output_id, _ = _setup(db, demand_world)
    other = demand_world[1]
    _contract(db, other, demand_world[2][other], 600)
    contract_sync.sync_contract_demand(db, org_id)
    assert _synced(db, org_id) == []


# --- forecast and stock targets -----------------------------------------------------------


class FakeSource:
    """A sales source keyed by org, the shape SALES_SOURCES expects."""

    name = "fake"
    label = "Fake"

    def __init__(self, lines, first):
        self.by_org, self.first = lines, first

    def connected(self, session, org_id):
        return org_id in self.by_org

    def lines(self, session, org_id, start, end):
        return [row for row in self.by_org.get(org_id, []) if start <= row.sold_on < end], []

    def first_sale(self, session, org_id):
        return self.first.get(org_id)


def _sale(days_ago, units, product="Navy Gin"):
    return SaleLine("fake", TODAY - timedelta(days=days_ago), f"INV-{uuid4()}", product, Decimal(units))


def _mapping(db, org_id, output_id, product="Navy Gin"):
    db.add(
        ProductMapping(
            org_id=org_id,
            biz_e_product_name=product,
            xero_description_pattern=product,
            biz_e_source_output_id=output_id,
        )
    )
    db.flush()


@pytest.fixture
def sales(monkeypatch):
    def install(lines_by_org, first_by_org):
        monkeypatch.setattr(sales_sources, "SALES_SOURCES", {"fake": FakeSource(lines_by_org, first_by_org)})

    return install


def _cover(db, org_id, weeks=12):
    return forecast_service.cover(db, org_id, None, today=TODAY, weeks=weeks)


def test_rate_runs_out_and_a_target_suggests_whole_batches_with_a_plan_by_date(db, demand_world, sales):
    org_id, output_id, _ = _setup(db, demand_world)
    _mapping(db, org_id, output_id)
    # 10 a week over the 12-week window; a big old sale outside it doesn't count.
    sales(
        {org_id: [_sale(7 * k + 1, 10) for k in range(12)] + [_sale(100, 1000)]}, {org_id: TODAY - timedelta(days=100)}
    )
    _stock(db, org_id, output_id, 50)
    forecast_service.save_target(db, org_id, None, {"source_output_id": str(output_id), "weeks_of_cover": 8})
    (row,) = _cover(db, org_id)["products"]
    assert row["weekly_rate"] == "10"
    assert row["seasonality"] == "Less than 12 months of its sales, so no seasonal adjustment"
    runs_out = TODAY + timedelta(days=35)  # 50 / (10 / 7)
    assert row["runs_out_on"] == runs_out.isoformat()
    # 8 weeks' cover plus the 2 days making it = 82.9, less 50 available: one 250-bottle batch.
    assert row["suggestion"] == {
        "batches": 1,
        "quantity": "250",
        "plan_by": (runs_out - timedelta(days=2)).isoformat(),
        "due_date": runs_out.isoformat(),
    }
    assert row["sentence"] == (
        f"Gin runs out {_day(runs_out)} at 10 bottles a week; plan 1 batch by {_day(runs_out - timedelta(days=2))}."
    )


def test_a_target_already_covered_suggests_nothing(db, demand_world, sales):
    org_id, output_id, _ = _setup(db, demand_world)
    _mapping(db, org_id, output_id)
    sales({org_id: [_sale(7 * k + 1, 10) for k in range(12)]}, {org_id: TODAY - timedelta(days=90)})
    _stock(db, org_id, output_id, 50)
    forecast_service.save_target(db, org_id, None, {"source_output_id": str(output_id), "weeks_of_cover": 4})
    (row,) = _cover(db, org_id)["products"]
    assert row["suggestion"] is None
    assert row["sentence"].endswith("that covers your 4-week target.")


def test_with_a_years_sales_the_coming_weeks_are_scaled_by_last_years_season(db, demand_world, sales):
    org_id, output_id, _ = _setup(db, demand_world)
    _mapping(db, org_id, output_id)
    trailing = [_sale(7 * k + 1, 10) for k in range(12)]  # 120 in the last 12 weeks
    year_ago = [_sale(364 - 7 * k - 1, 20) for k in range(12)]  # 240 in the same 12 weeks ahead, last year
    first = [_sale(400, 5)]  # its first sale, over a year ago: outside every window used below
    sales({org_id: trailing + year_ago + first}, {org_id: TODAY - timedelta(days=400)})
    (row,) = _cover(db, org_id)["products"]
    # Last year's average week: 360 / 52 = 6.92; those weeks sold 20 a week = x2.89.
    assert row["seasonality_factor"] == "2.89"
    assert row["weekly_rate"] == "28.89"
    assert row["seasonality"] == "Last year the next 12 weeks sold 289% of an average week"


def test_available_counts_planned_batches_and_takes_off_open_orders(db, demand_world, sales):
    org_id, output_id, _ = _setup(db, demand_world)
    _mapping(db, org_id, output_id)
    sales({org_id: [_sale(3, 70)]}, {org_id: TODAY - timedelta(days=3)})
    _stock(db, org_id, output_id, 100)
    order = _demand(db, org_id, output_id, 300, 10)
    batch_service.plan_demand(db, org_id, order.id, {}, today=TODAY)  # 200 short -> 1 batch of 250
    (row,) = _cover(db, org_id)["products"]
    assert (row["on_hand"], row["planned"], row["ordered"], row["available"]) == ("100", "250", "300", "50")


def test_unknowns_stay_unknown_with_a_reason(db, demand_world, sales):
    org_id, output_id, _ = _setup(db, demand_world)
    forecast_service.save_target(db, org_id, None, {"source_output_id": str(output_id), "weeks_of_cover": 4})
    (row,) = _cover(db, org_id)["products"]  # no sales source connected
    assert row["weekly_rate"] is None and row["runs_out_on"] is None and row["suggestion"] is None
    assert "No sales source is connected, so there is no sales rate" in row["unknowns"]
    # A source, a product sold with no workflow output on its mapping.
    db.add(ProductMapping(org_id=org_id, biz_e_product_name="Mystery", xero_description_pattern="Mystery"))
    db.flush()
    sales({org_id: [_sale(2, 5, product="Mystery")]}, {org_id: TODAY - timedelta(days=2)})
    result = _cover(db, org_id)
    assert result["unmapped_products"] == [
        {"product_name": "Mystery", "reason": "Sold, but its product mapping has no workflow output"}
    ]
    assert "No product mapping sells this output, so there is no sales rate" in result["products"][0]["unknowns"]


def test_another_orgs_sales_targets_and_stock_never_count(db, demand_world, sales):
    org_id, output_id, _ = _setup(db, demand_world)
    other = demand_world[1]
    _mapping(db, org_id, output_id)
    _mapping(db, other, output_id)  # hostile: the other org maps its sales to this org's output id
    sales({org_id: [_sale(1, 12)], other: [_sale(1, 9999)]}, {org_id: TODAY - timedelta(days=1)})
    _stock(db, other, demand_world[2][other], 9999, forged_output=output_id)
    db.add(PlanningStockTarget(org_id=other, source_output_id=output_id, weeks_of_cover=Decimal(50)))
    db.flush()
    (row,) = _cover(db, org_id)["products"]
    assert row["weekly_rate"] == "1" and row["on_hand"] == "0" and row["target_weeks"] is None


@pytest.mark.parametrize("weeks", [0, -1, 105, "1.234", True, "NaN", "Infinity", "lots"])
def test_invalid_targets_are_refused(db, demand_world, weeks):
    org_id, output_id, _ = _setup(db, demand_world)
    with pytest.raises(ValueError):
        forecast_service.save_target(db, org_id, None, {"source_output_id": str(output_id), "weeks_of_cover": weeks})
    assert db.query(PlanningStockTarget).filter(PlanningStockTarget.org_id == org_id).count() == 0


def test_a_target_is_set_changed_and_cleared_and_foreign_outputs_are_refused(db, demand_world):
    org_id, output_id, _ = _setup(db, demand_world)
    other_output = demand_world[2][demand_world[1]]
    save = forecast_service.save_target
    assert save(
        db, org_id, None, {"source_output_id": str(output_id), "weeks_of_cover": "6.5"}
    ).weeks_of_cover == Decimal("6.5")
    assert save(db, org_id, None, {"source_output_id": str(output_id), "weeks_of_cover": 3}).weeks_of_cover == 3
    assert db.query(PlanningStockTarget).filter(PlanningStockTarget.org_id == org_id).count() == 1
    assert save(db, org_id, None, {"source_output_id": str(output_id), "weeks_of_cover": None}) is None
    assert db.query(PlanningStockTarget).filter(PlanningStockTarget.org_id == org_id).count() == 0
    with pytest.raises(ValueError, match="this business"):
        save(db, org_id, None, {"source_output_id": str(other_output), "weeks_of_cover": 4})
    with pytest.raises(ValueError, match="window"):
        forecast_service.window_weeks("3")
    assert forecast_service.window_weeks("52") == 52


def test_plan_it_creates_a_forecast_demand_planned_in_one_go_and_a_retry_repeats_it(db, demand_world, sales):
    org_id, output_id, _ = _setup(db, demand_world)
    _mapping(db, org_id, output_id)
    sales({org_id: [_sale(7 * k + 1, 10) for k in range(12)]}, {org_id: TODAY - timedelta(days=90)})
    _stock(db, org_id, output_id, 50)
    forecast_service.save_target(db, org_id, None, {"source_output_id": str(output_id), "weeks_of_cover": 8})
    body = {"source_output_id": str(output_id)}
    demand, rows, changed = forecast_service.plan_forecast(db, org_id, body, "retry-key-1", today=TODAY)
    assert changed and demand.source == "forecast" and demand.reference == "Stock target: Gin"
    # Already net of the 50 on hand: planned as suggested, not netted a second time.
    assert demand.quantity == Decimal(250) and len(rows) == 1
    again, rows_again, changed = forecast_service.plan_forecast(db, org_id, body, "retry-key-1", today=TODAY)
    assert not changed and again.id == demand.id and [row.id for row in rows_again] == [row.id for row in rows]
    other_output = uuid4()
    with pytest.raises(ValueError):
        forecast_service.plan_forecast(db, org_id, {"source_output_id": str(other_output)}, "retry-key-1", today=TODAY)
    with pytest.raises(ValueError, match="Idempotency-Key"):
        forecast_service.plan_forecast(db, org_id, body, None, today=TODAY)


def test_plan_it_without_a_target_or_a_shortfall_is_refused(db, demand_world, sales):
    org_id, output_id, _ = _setup(db, demand_world)
    _mapping(db, org_id, output_id)
    sales({org_id: [_sale(1, 1)]}, {org_id: TODAY - timedelta(days=1)})
    body = {"source_output_id": str(output_id)}
    with pytest.raises(batch_service.PlanningConflictError, match="weeks of cover"):
        forecast_service.plan_forecast(db, org_id, body, "retry-key-2", today=TODAY)
    _stock(db, org_id, output_id, 5000)
    forecast_service.save_target(db, org_id, None, {"source_output_id": str(output_id), "weeks_of_cover": 4})
    with pytest.raises(batch_service.PlanningConflictError, match="Nothing to plan"):
        forecast_service.plan_forecast(db, org_id, body, "retry-key-3", today=TODAY)
    assert db.query(PlanningDemand).filter(PlanningDemand.org_id == org_id).count() == 0


def test_seasonality_needs_a_year_of_that_products_own_sales(db, demand_world, sales):
    """An old product's history doesn't lend a season to one first sold 11 weeks ago."""
    org_id, output_id, step = _setup(db, demand_world)
    old_output = uuid4()
    step.outputs = [*step.outputs, {"id": str(old_output), "name": "Old Gin", "unit": "bottles", "quantity": 250}]
    db.flush()
    _mapping(db, org_id, output_id, "New Gin")
    _mapping(db, org_id, old_output, "Old Gin")
    new = [_sale(7 * k + 1, 10, product="New Gin") for k in range(11)]
    old = [_sale(7 * k + 1, 10, product="Old Gin") for k in range(60)]
    sales({org_id: new + old}, {org_id: TODAY - timedelta(days=7 * 59 + 1)})
    rows = {row["name"]: row for row in _cover(db, org_id)["products"]}
    assert rows["Gin"]["seasonality_factor"] is None
    assert rows["Gin"]["weekly_rate"] == "9.17"  # 110 over 12 weeks, unadjusted
    assert rows["Gin"]["seasonality"] == "Less than 12 months of its sales, so no seasonal adjustment"
    assert rows["Old Gin"]["seasonality_factor"] is not None


def _two_sites(db, org_id):
    org = db.get(Organisation, org_id)
    # The plan includes multiple sites, and the business has switched them on (flushed only:
    # the test's rollback, or the route test's cleanup, removes it).
    db.add(FeatureSubscription(org_id=org_id, feature_key="multi_site"))
    org.multiple_sites_enabled = True
    main = Site(org_id=org_id, name="Main distillery", is_default=True)
    cellar = Site(org_id=org_id, name="Cellar door", is_default=False)
    db.add_all([main, cellar])
    db.flush()
    return main, cellar


def test_stock_cover_targets_and_plan_it_follow_the_chosen_site(db, demand_world, sales):
    org_id, output_id, _ = _setup(db, demand_world)
    main, cellar = _two_sites(db, org_id)
    _mapping(db, org_id, output_id)
    sales({org_id: [_sale(7 * k + 1, 10) for k in range(12)]}, {org_id: TODAY - timedelta(days=90)})
    _stock(db, org_id, output_id, 500, site_id=main.id)
    _stock(db, org_id, output_id, 30, site_id=cellar.id)
    forecast_service.save_target(db, org_id, cellar, {"source_output_id": str(output_id), "weeks_of_cover": 8})

    def row(site):
        (product,) = forecast_service.cover(db, org_id, site, today=TODAY, weeks=12)["products"]
        return product

    assert (row(main)["on_hand"], row(main)["target_weeks"], row(main)["suggestion"]) == ("500", None, None)
    assert (row(cellar)["on_hand"], row(cellar)["target_weeks"]) == ("30", "8")
    assert row(cellar)["suggestion"]["batches"] == 1
    demand, rows, _ = forecast_service.plan_forecast(
        db, org_id, {"source_output_id": str(output_id), "site_id": str(cellar.id)}, "site-retry-1", today=TODAY
    )
    assert {batch.site_id for batch in rows} == {cellar.id}
    with pytest.raises(batch_service.PlanningConflictError, match="weeks of cover"):
        forecast_service.plan_forecast(
            db, org_id, {"source_output_id": str(output_id), "site_id": str(main.id)}, "site-retry-2", today=TODAY
        )


# --- routes -------------------------------------------------------------------------------


def test_new_routes_need_the_planner_permissions():
    assert requirement_for("planning.sync_planning_demand", "POST") == "production.record"
    assert requirement_for("planning.get_stock_cover", "GET") == "production.view"
    assert requirement_for("planning.save_stock_target", "POST") == "production.record"
    assert requirement_for("planning.plan_stock_cover", "POST") == "production.record"


def test_routes_sync_cover_target_and_plan_it(db, demand_clients, flask_app):
    client, org_id, output_id = demand_clients[0]
    other, _, _ = demand_clients[1]
    auditor = demand_clients[2][0]
    assert client.post("/api/core/planner/demand/sync").get_json() == {"changes": {}, "held": [], "unmapped": []}
    assert auditor.post("/api/core/planner/demand/sync").status_code == 403
    response = client.post("/api/core/planner/targets", json={"source_output_id": str(output_id), "weeks_of_cover": 6})
    assert response.status_code == 200 and response.get_json() == {"target": {"weeks_of_cover": "6"}}
    assert (
        other.post(
            "/api/core/planner/targets", json={"source_output_id": str(output_id), "weeks_of_cover": 6}
        ).status_code
        == 400
    )
    assert (
        auditor.post(
            "/api/core/planner/targets", json={"source_output_id": str(output_id), "weeks_of_cover": 6}
        ).status_code
        == 403
    )
    cover = client.get("/api/core/planner/cover").get_json()
    assert [row["source_output_id"] for row in cover["products"]] == [str(output_id)]
    assert cover["products"][0]["target_weeks"] == "6"
    assert other.get("/api/core/planner/cover").get_json()["products"] == []
    assert auditor.get("/api/core/planner/cover").status_code == 200
    assert client.get("/api/core/planner/cover?weeks=2").status_code == 400
    response = client.post("/api/core/planner/cover/plan", json={"source_output_id": str(output_id)})
    assert response.status_code == 400 and "Idempotency-Key" in response.get_json()["error"]
    audit = (
        db.query(AuditLog).filter(AuditLog.org_id == org_id, AuditLog.action == "planning_stock_target_saved").count()
    )
    assert audit == 1
    anonymous = flask_app.test_client()
    anonymous.environ_base.update({"wsgi.url_scheme": "https", "HTTP_X_FORWARDED_PROTO": "https"})
    assert anonymous.get("/api/core/planner/cover").status_code in (302, 401)
    assert anonymous.post("/api/core/planner/demand/sync").status_code in (302, 400, 401)
    db.rollback()
    db.query(PlanningStockTarget).filter(PlanningStockTarget.org_id.in_([org_id])).delete(synchronize_session=False)
    db.commit()


def test_cover_route_offers_sites_and_reads_targets_for_the_chosen_one(db, demand_clients):
    client, org_id, output_id = demand_clients[0]
    main, cellar = _two_sites(db, org_id)
    db.commit()
    try:
        body = {"source_output_id": str(output_id), "weeks_of_cover": 5, "site_id": str(cellar.id)}
        assert client.post("/api/core/planner/targets", json=body).status_code == 200
        at_cellar = client.get(f"/api/core/planner/cover?site_id={cellar.id}").get_json()
        assert at_cellar["site_id"] == str(cellar.id)
        assert [site["name"] for site in at_cellar["sites"]] == ["Main distillery", "Cellar door"]
        assert at_cellar["products"][0]["target_weeks"] == "5"
        at_main = client.get("/api/core/planner/cover").get_json()
        assert at_main["site_id"] == str(main.id)
        assert at_main["products"] == []  # no target or sales at the main site
        foreign = demand_clients[1][0].get(f"/api/core/planner/cover?site_id={cellar.id}")
        assert foreign.status_code == 400
    finally:
        db.rollback()
        db.query(PlanningStockTarget).filter(PlanningStockTarget.org_id == org_id).delete(synchronize_session=False)
        db.query(AuditLog).filter(AuditLog.org_id == org_id).delete(synchronize_session=False)
        db.query(Site).filter(Site.org_id == org_id).delete(synchronize_session=False)
        db.query(FeatureSubscription).filter(FeatureSubscription.org_id == org_id).delete(synchronize_session=False)
        db.query(Organisation).filter(Organisation.id == org_id).update({"multiple_sites_enabled": False})
        db.commit()


def test_saving_a_contract_order_syncs_the_planner(db, demand_clients, flask_app):
    _, org_id, output_id = demand_clients[0]
    email = f"contract-admin-{uuid4()}@test.com"
    UserRepository(db).create_user(
        org_id=org_id,
        email=email,
        role=UserRole.ADMIN,
        is_active=True,
        password_hash=AuthService.hash_password(DEFAULT_TEST_PASSWORD),
    )
    db.commit()
    client = flask_app.test_client()
    client.environ_base.update({"wsgi.url_scheme": "https", "HTTP_X_FORWARDED_PROTO": "https"})
    assert client.post("/auth/login", json={"email": email, "password": DEFAULT_TEST_PASSWORD}).status_code == 200
    process_id = db.query(Step.process_id).filter(Step.org_id == org_id).scalar()
    batch_fixtures.native_recipe(db, org_id, process_id)
    db.commit()
    version_id = str(batch_service.latest_version(db, org_id, process_id).id)
    customer = client.post("/api/core/contract-customers", json={"name": "Brand"}).get_json()
    assert customer, "contract customer"
    customer_id = (customer.get("customer") or customer)["id"]
    order = client.post(
        "/api/core/contract-orders",
        json={
            "customer_id": customer_id,
            "reference": "PO-9",
            "due_date": (TODAY + timedelta(days=20)).isoformat(),
            "status": "confirmed",
            "duty_responsibility": "producer_licensee",
            "lines": [
                {
                    "product_name": "Gin",
                    "quantity": "120",
                    "unit": "bottles",
                    "materials_source": "producer",
                    "source_output_id": str(output_id),
                    "process_version_id": version_id,
                }
            ],
        },
    )
    assert order.status_code == 201, order.get_json()
    demands = client.get("/api/core/planner/demands").get_json()["demands"]
    assert [(row["source"], row["quantity"], row["reference"]) for row in demands] == [
        ("contract", "120.0000", "PO-9 · Gin")
    ]
    order_id = order.get_json()["order"]["id"]
    assert client.patch(f"/api/core/contract-orders/{order_id}", json={"status": "cancelled"}).status_code == 200
    demands = client.get("/api/core/planner/demands").get_json()["demands"]
    assert [row["status"] for row in demands] == ["cancelled"]
    db.rollback()
    for model in (PlanningDemand, ContractOrderLine, ContractOrder, ContractCustomer, ProcessVersion):
        db.query(model).filter(model.org_id == org_id).delete(synchronize_session=False)
    db.query(AuditLog).filter(AuditLog.org_id == org_id).delete(synchronize_session=False)
    db.commit()


def test_a_stored_nan_contract_quantity_is_listed_not_a_crash(db, demand_world):
    """PostgreSQL NUMERIC 'NaN' passes `quantity > 0`; sync must list it, never raise (B3 review)."""
    org_id, output_id, _ = _setup(db, demand_world)
    _, order, line = _contract(db, org_id, output_id, 10)
    db.execute(
        __import__("sqlalchemy").text("UPDATE contract_order_lines SET quantity = 'NaN' WHERE id = :id"),
        {"id": line.id},
    )
    db.expire_all()
    result = contract_sync.sync_contract_demand(db, org_id)
    assert _synced(db, org_id) == []
    assert [row["reason"] for row in result["unmapped"]] == ["The ordered quantity can't be planned"]


def test_stock_that_lasts_beyond_the_horizon_has_no_runs_out_date(db, demand_world, sales):
    """15,000 bottles selling 1 every 12 weeks is far past any date timedelta can hold (B3 review)."""
    org_id, output_id, _ = _setup(db, demand_world)
    _mapping(db, org_id, output_id)
    sales({org_id: [_sale(3, 1)]}, {org_id: TODAY - timedelta(days=3)})
    _stock(db, org_id, output_id, 15000)
    forecast_service.save_target(db, org_id, None, {"source_output_id": str(output_id), "weeks_of_cover": 104})
    (row,) = _cover(db, org_id)["products"]
    assert row["runs_out_on"] is None and row["suggestion"] is None
    assert row["summary"].startswith("Lasts more than 5 years at ")
