"""Demand from contract orders and from sales history, and planning only what isn't covered
(GL-P07 B3)."""

from datetime import timedelta
from decimal import Decimal
from uuid import uuid4

import pytest

from app.core.db.models.step import Step
from app.core.db.repositories.inventory_repo import InventoryRepository
from app.features.contract_manufacturing.models.orders import ContractCustomer, ContractOrder, ContractOrderLine
from app.features.crm.services import sales_sources
from app.features.planning import batch_service, demand_service
from app.features.planning import forecast_service as service
from app.features.planning.batch_models import PlanningBatch
from app.features.planning.models import PlanningDemand
from tests.features.planning import test_batches as fixtures

demand_world = fixtures.demand_world
base_demand_world = fixtures.base_demand_world
TODAY = fixtures.TODAY


@pytest.fixture
def gin(db, demand_world):
    """The 'Gin' output of the Bottle workflow, 250 bottles a batch, two days to make."""
    org_id, _, outputs = demand_world
    step = db.query(Step).filter(Step.org_id == org_id).one()
    fixtures.native_recipe(db, org_id, step.process_id)
    batch_service.save_setting(db, org_id, step.process_id, fixtures.setting_payload(db, org_id, outputs[org_id]))
    return org_id, outputs[org_id], step


def _sales(monkeypatch, weekly, *, name="Gin", first=None):
    """`weekly[i]` bottles sold in week i before today (0 = this past week)."""
    lines = [
        sales_sources.SaleLine("xero", TODAY - timedelta(days=7 * index + 3), f"INV-{index}", name, Decimal(units))
        for index, units in enumerate(weekly)
        if units
    ]
    since = first or (TODAY - timedelta(weeks=len(weekly)))
    monkeypatch.setattr(sales_sources, "sale_lines", lambda db, org_id, start, end: (lines, []))
    monkeypatch.setattr(sales_sources, "first_sale", lambda db, org_id: since)


def _stock(db, org_id, output_id, quantity, **changes):
    return InventoryRepository(db).create_inventory_item(
        org_id,
        name=changes.pop("name", "Gin"),
        quantity=Decimal(quantity),
        unit="bottles",
        inventory_type="final_product",
        # Opening stock: known by the product's name, no workflow output recorded.
        commit=False,
        **changes,
    )


def _row(db, org_id, output_id, **kwargs):
    return next(r for r in service.forecast(db, org_id, today=TODAY, **kwargs) if r["output_id"] == str(output_id))


def test_the_weekly_rate_is_the_windows_sales_averaged(db, gin, monkeypatch):
    org_id, output_id, _ = gin
    _sales(monkeypatch, [30] * 12 + [300] * 8)  # a big run 13-20 weeks ago doesn't count
    row = _row(db, org_id, output_id)
    assert (row["weekly_rate"], row["window_weeks"], row["seasonal_factor"]) == ("30", 12, None)
    assert _row(db, org_id, output_id, window_weeks=20)["weekly_rate"] == "138"  # (12*30 + 8*300) / 20


def test_a_short_history_averages_over_what_there_is(db, gin, monkeypatch):
    org_id, output_id, _ = gin
    _sales(monkeypatch, [40, 40, 40, 40])  # four weeks of history
    row = _row(db, org_id, output_id)
    assert (row["weekly_rate"], row["window_weeks"], row["history_weeks"]) == ("40", 4, 4)


def test_a_year_of_history_scales_the_rate_by_the_season(db, gin, monkeypatch):
    org_id, output_id, _ = gin
    weekly = [20] * 104
    for week in range(48, 52):  # the coming four weeks, last year: twice the year's pace
        weekly[week] = 40
    _sales(monkeypatch, weekly)
    row = _row(db, org_id, output_id)
    # Last year's average was (48*20 + 4*40) / 52; the coming weeks sold 40.
    assert Decimal(row["seasonal_factor"]) == (Decimal(40) / (Decimal(48 * 20 + 4 * 40) / 52)).quantize(Decimal("0.01"))
    assert Decimal(row["weekly_rate"]) > 20


def test_it_runs_out_later_for_each_batch_already_planned(db, gin, monkeypatch):
    org_id, output_id, _ = gin
    _sales(monkeypatch, [70] * 12)  # 10 a day
    _stock(db, org_id, output_id, "100")
    assert _row(db, org_id, output_id)["runs_out"] == (TODAY + timedelta(days=10)).isoformat()
    demand = demand_service.create_demand(
        db, org_id, fixtures.payload(output_id, quantity="250", due_date=(TODAY + timedelta(days=5)).isoformat())
    )
    batch_service.plan_demand(db, org_id, demand.id, {}, today=TODAY)
    # 250 more arrive in two days: 100 + 250 lasts 35 days.
    assert _row(db, org_id, output_id)["runs_out"] == (TODAY + timedelta(days=35)).isoformat()


def test_a_stock_target_suggests_whole_batches_and_when_to_plan_them(db, gin, monkeypatch):
    org_id, output_id, _ = gin
    _sales(monkeypatch, [70] * 12)
    _stock(db, org_id, output_id, "100")
    assert _row(db, org_id, output_id)["suggestion"] is None  # no target, no suggestion
    service.set_target(db, org_id, output_id, "8")
    row = _row(db, org_id, output_id)
    # Eight weeks is 560; 100 in stock leaves 460, which is two 250-bottle batches.
    assert row["suggestion"] == {
        "quantity": "500",
        "batches": 2,
        "need_by": (TODAY + timedelta(days=10)).isoformat(),
        "plan_by": (TODAY + timedelta(days=8)).isoformat(),  # two days to make
        "late": False,
    }
    assert row["sentence"].startswith("Gin runs out") and "plan 2 batches by" in row["sentence"]


def test_planning_the_suggestion_makes_forecast_demand_and_its_batches(db, gin, monkeypatch):
    org_id, output_id, _ = gin
    _sales(monkeypatch, [70] * 12)
    _stock(db, org_id, output_id, "100")
    service.set_target(db, org_id, output_id, "8")
    demand = service.accept_suggestion(db, org_id, output_id, today=TODAY)
    assert (demand.source, demand.quantity, demand.reference) == (
        "forecast",
        Decimal(500),
        "Forecast · 8 weeks' cover of Gin",
    )
    # Waiting to be planned, it already counts: no second suggestion for the same need.
    assert _row(db, org_id, output_id)["suggestion"] is None
    with pytest.raises(ValueError, match="nothing to plan"):
        service.accept_suggestion(db, org_id, output_id, today=TODAY)


def test_no_sales_says_so(db, gin, monkeypatch):
    org_id, output_id, _ = gin
    _sales(monkeypatch, [], first=None)
    monkeypatch.setattr(sales_sources, "first_sale", lambda db, org_id: None)
    row = _row(db, org_id, output_id)
    assert (row["weekly_rate"], row["runs_out"], row["sentence"]) == (
        "0",
        None,
        "No sales of Gin yet, so there's no forecast.",
    )


@pytest.mark.parametrize("weeks", ["0", "105", "-1", "lots"])
def test_a_stock_target_is_half_a_week_to_two_years(db, gin, weeks):
    org_id, output_id, _ = gin
    with pytest.raises(ValueError, match="Weeks of cover"):
        service.set_target(db, org_id, output_id, weeks)


def test_another_businesss_product_cant_have_a_target(db, gin, demand_world):
    org_id, _, _ = gin
    other_output = demand_world[2][demand_world[1]]
    with pytest.raises(ValueError, match="this business makes"):
        service.set_target(db, org_id, other_output, "4")


def _contract_line(db, org_id, output_id, quantity="120", status="confirmed", due=None):
    customer = ContractCustomer(org_id=org_id, name=f"Brand {uuid4().hex[:4]}")
    db.add(customer)
    db.flush()
    order = ContractOrder(
        org_id=org_id,
        customer_id=customer.id,
        reference=f"PO-{uuid4().hex[:6]}",
        due_date=due or TODAY + timedelta(days=14),
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
        unit="bottles",
        materials_source="producer",
        source_output_id=output_id,
    )
    db.add(line)
    db.flush()
    return customer, order, line


def _contract_demand(db, org_id):
    return db.query(PlanningDemand).filter(PlanningDemand.org_id == org_id, PlanningDemand.source == "contract").all()


def test_a_confirmed_contract_line_becomes_demand_once(db, gin):
    org_id, output_id, _ = gin
    customer, order, line = _contract_line(db, org_id, output_id)
    _contract_line(db, org_id, output_id, status="draft")  # not confirmed: not demand
    assert service.sync_contract_demand(db, org_id) == {"added": 1, "updated": 0, "cancelled": 0}
    assert service.sync_contract_demand(db, org_id) == {"added": 0, "updated": 0, "cancelled": 0}
    (demand,) = _contract_demand(db, org_id)
    assert (demand.reference, demand.quantity, demand.due_date, demand.source_ref) == (
        f"{customer.name} · {order.reference}",
        Decimal(120),
        order.due_date,
        str(line.id),
    )


def test_a_changed_or_withdrawn_line_follows_until_it_is_planned(db, gin):
    org_id, output_id, _ = gin
    _, order, line = _contract_line(db, org_id, output_id)
    service.sync_contract_demand(db, org_id)
    line.quantity = Decimal(240)
    db.flush()
    assert service.sync_contract_demand(db, org_id)["updated"] == 1
    (demand,) = _contract_demand(db, org_id)
    assert demand.quantity == 240
    batch_service.plan_demand(db, org_id, demand.id, {}, today=TODAY)
    order.status = "cancelled"
    db.flush()
    # Planned: someone has to review it, so it stays.
    assert service.sync_contract_demand(db, org_id)["cancelled"] == 0 and demand.status == "open"
    for batch in db.query(PlanningBatch).filter(PlanningBatch.demand_id == demand.id):
        batch.status = "cancelled"
    db.flush()
    assert service.sync_contract_demand(db, org_id)["cancelled"] == 1 and demand.status == "cancelled"


def test_planning_nets_stock_on_hand(db, gin):
    org_id, output_id, _ = gin
    _stock(db, org_id, output_id, "300")
    demand = demand_service.create_demand(
        db, org_id, fixtures.payload(output_id, quantity="600", due_date=(TODAY + timedelta(days=5)).isoformat())
    )
    rows, _ = batch_service.plan_demand(db, org_id, demand.id, {}, today=TODAY)
    assert len(rows) == 2  # 600 - 300 on hand = 300, two batches of 250


def test_planning_nets_batches_for_earlier_demand_and_refuses_when_covered(db, gin):
    org_id, output_id, _ = gin
    first = demand_service.create_demand(
        db, org_id, fixtures.payload(output_id, quantity="100", due_date=(TODAY + timedelta(days=3)).isoformat())
    )
    batch_service.plan_demand(db, org_id, first.id, {}, today=TODAY)  # one batch of 250: 150 spare
    second = demand_service.create_demand(
        db, org_id, fixtures.payload(output_id, quantity="100", due_date=(TODAY + timedelta(days=6)).isoformat())
    )
    with pytest.raises(batch_service.PlanningConflictError, match="already planned cover"):
        batch_service.plan_demand(db, org_id, second.id, {}, today=TODAY)
    third = demand_service.create_demand(
        db, org_id, fixtures.payload(output_id, quantity="200", due_date=(TODAY + timedelta(days=9)).isoformat())
    )
    rows, _ = batch_service.plan_demand(db, org_id, third.id, {}, today=TODAY)
    assert len(rows) == 1  # 150 spare - 100 for the second = 50; 150 more is one batch


def test_out_of_date_stock_covers_nothing(db, gin):
    org_id, output_id, _ = gin
    _stock(db, org_id, output_id, "600", expiry_date=TODAY - timedelta(days=1))
    demand = demand_service.create_demand(
        db, org_id, fixtures.payload(output_id, quantity="250", due_date=(TODAY + timedelta(days=5)).isoformat())
    )
    rows, _ = batch_service.plan_demand(db, org_id, demand.id, {}, today=TODAY)
    assert len(rows) == 1


def test_planning_a_suggestion_plans_all_of_it_and_the_suggestion_goes(db, gin, monkeypatch):
    """The forecast already counted stock on hand: planning its demand doesn't net it again."""
    org_id, output_id, _ = gin
    _sales(monkeypatch, [70] * 12)
    _stock(db, org_id, output_id, "100")
    service.set_target(db, org_id, output_id, "8")
    demand = service.accept_suggestion(db, org_id, output_id, today=TODAY)
    rows, _ = batch_service.plan_demand(db, org_id, demand.id, {}, today=TODAY)
    assert len(rows) == 2  # all 500, not 500 less the 100 in stock
    assert _row(db, org_id, output_id)["suggestion"] is None


def test_a_customer_order_isnt_counted_as_cover(db, gin, monkeypatch):
    """Orders are part of what sells, which the rate already counts; only batches add stock."""
    org_id, output_id, _ = gin
    _sales(monkeypatch, [70] * 12)
    _stock(db, org_id, output_id, "100")
    service.set_target(db, org_id, output_id, "8")
    before = _row(db, org_id, output_id)["suggestion"]
    demand_service.create_demand(
        db, org_id, fixtures.payload(output_id, quantity="400", due_date=(TODAY + timedelta(days=20)).isoformat())
    )
    assert _row(db, org_id, output_id)["suggestion"] == before


def test_only_finished_products_are_forecast(db, gin):
    org_id, output_id, step = gin
    intermediate = str(uuid4())
    step.outputs = [*step.outputs, {"id": intermediate, "name": "Gin base", "unit": "L"}]
    db.add(
        Step(
            org_id=org_id,
            process_id=step.process_id,
            step_number=2,
            position=2000,
            name="Label",
            inputs=[{"name": "Gin base", "unit": "L", "quantity": "1", "source_output_id": intermediate}],
            outputs=[],
            execution_prompts=[],
        )
    )
    db.flush()
    assert intermediate not in service.finished_products(db, org_id)
