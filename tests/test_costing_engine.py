"""Live-cogs 8.1a: the cost roll-up (spec .agents/specs/live-cogs.md, "Cost roll-up").

Written before the implementation. Each test names the acceptance criterion it proves.
"""

from datetime import date
from decimal import Decimal

import pytest

from app.core.db.models.inventory_item import InventoryType
from tests.costing_helpers import (
    D,
    by_name,
    complete,
    execution_cost,
    flows,
    lot,
    lot_cost,
    new_org,
    price,
    produced_lots,
    purge,
    set_last_known_price,
    user_client,
    workflow,
)
from tests.test_compliant_routes import flask_app  # noqa: F401 -- fixture re-export

FINAL = InventoryType.FINAL_PRODUCT.value
WIP = InventoryType.WORK_IN_PROGRESS.value


@pytest.fixture
def world(db, flask_app):  # noqa: F811
    org = new_org(db)
    client = user_client(db, flask_app, org)
    yield org, client
    purge(db, org)


def _created_flow(db, org_id, item):
    rows = flows(db, org_id, item.id, kind="created")
    assert len(rows) == 1, rows
    return rows[0]


# --- lot pricing -----------------------------------------------------------------------


def test_ac22_last_known_price_from_same_material(world, db):
    org, _ = world
    source = lot(db, org.id, "Juniper  Berries", 1, "kg", purchase_date=date(2026, 10, 1))
    price(db, org.id, source.id, 45, 1)
    target = lot(db, org.id, "juniper berries", 500, "g", purchase_date=date(2026, 10, 20))

    cost = lot_cost(db, org.id, target.id)
    assert cost["status"] == "estimated"
    assert D(cost["unit_cost"]) == D("0.045000")
    assert cost["estimate_from"]["inventory_item_id"] == str(source.id)

    set_last_known_price(db, org.id, False)
    off = lot_cost(db, org.id, target.id)
    assert off["status"] == "unknown" and off["unit_cost"] is None
    assert [m["inventory_item_id"] for m in off["missing"]] == [str(target.id)]


def test_ac22_unknown_without_any_costed_material(world, db):
    org, _ = world
    target = lot(db, org.id, "Orris Root", 1, "kg")
    cost = lot_cost(db, org.id, target.id)
    assert cost["status"] == "unknown" and cost["unit_cost"] is None and cost["known_unit_cost"] is None
    assert cost["missing"][0]["name"] == "Orris Root"


def test_ac22_produced_lot_is_never_an_estimate_source(world, db):
    org, client = world
    spirit = lot(db, org.id, "Neutral Spirit", 10, "L")
    price(db, org.id, spirit.id, 50, 10)
    execution, (step,) = workflow(db, org.id, [[{"name": "Coriander", "unit": "kg"}]])
    complete(client, execution, step, [(spirit, 10, "L")], [{"name": "Coriander", "quantity": 2, "unit": "kg"}])
    raw = lot(db, org.id, "Coriander", 1, "kg")
    cost = lot_cost(db, org.id, raw.id)
    assert cost["status"] == "unknown", "a production cost must not become a material's price"


def test_ac23_free_and_customer_owned(world, db):
    org, _ = world
    gift = lot(db, org.id, "Foraged Kawakawa", 300, "g")
    price(db, org.id, gift.id, 0, 300, kind="free")
    cost = lot_cost(db, org.id, gift.id)
    assert (D(cost["unit_cost"]), cost["status"], cost["source"]) == (D("0"), "actual", "free")


def test_ac23_customer_owned_is_zero_and_not_priceable(world, db):
    org, _ = world
    from app.features.contract_manufacturing.models.orders import ContractCustomer
    from app.features.costing.service import CostingError

    customer = ContractCustomer(org_id=org.id, name="Client Distilling")
    db.add(customer)
    db.commit()
    theirs = lot(db, org.id, "Client Botanicals", 2, "kg", contract_customer_id=customer.id)
    cost = lot_cost(db, org.id, theirs.id)
    assert (D(cost["unit_cost"]), cost["status"], cost["source"]) == (D("0"), "actual", "customer_owned")
    assert cost["editable"] is False
    with pytest.raises(CostingError):
        price(db, org.id, theirs.id, 10, 2)
    db.rollback()


def test_ac24_weighted_pool_over_two_inflows(world, db):
    org, _ = world
    from app.core.db.repositories.inventory_repo import InventoryRepository

    item = lot(db, org.id, "Cardamom", 2, "kg")
    price(db, org.id, item.id, 90, 2, cost_flow_id=_created_flow(db, org.id, item).id)
    InventoryRepository(db).add_quantity_to_inventory_item(item.id, org.id, "3")
    db.commit()

    unpriced = lot_cost(db, org.id, item.id)
    assert (D(unpriced["unit_cost"]), unpriced["status"]) == (D("45"), "estimated")
    assert D(unpriced["unpriced_quantity"]) == D("3")

    added = flows(db, org.id, item.id, kind="added")
    assert len(added) == 1 and D(str(added[0].quantity)) == D("3")
    price(db, org.id, item.id, 120, 3, cost_flow_id=added[0].id)
    priced = lot_cost(db, org.id, item.id)
    assert (D(priced["unit_cost"]), priced["status"]) == (D("42"), "actual")


def test_ac54_flow_price_cannot_exceed_flow_and_residual_is_estimated(world, db):
    org, _ = world
    from app.features.costing.service import CostingError

    item = lot(db, org.id, "Angelica", 5, "kg")
    flow = _created_flow(db, org.id, item)
    with pytest.raises(CostingError):
        price(db, org.id, item.id, 60, 6, cost_flow_id=flow.id)
    db.rollback()

    price(db, org.id, item.id, 20, 2, cost_flow_id=flow.id)
    part = lot_cost(db, org.id, item.id)
    assert D(part["priced_quantity"]) == 2 and D(part["unpriced_quantity"]) == 3
    assert (D(part["unit_cost"]), part["status"]) == (D("10"), "estimated")

    with pytest.raises(CostingError):  # a flow price on another lot's flow
        other = lot(db, org.id, "Other", 1, "kg")
        price(db, org.id, other.id, 1, 1, cost_flow_id=flow.id)
    db.rollback()
    with pytest.raises(CostingError):  # zero / negative quantity
        price(db, org.id, item.id, 1, 0)
    db.rollback()
    with pytest.raises(CostingError):  # negative manual amount
        price(db, org.id, item.id, -5, 1)
    db.rollback()


def test_ac54_second_flow_price_replaces_first(world, db):
    """At most one active entry per (lot, flow): a new flow price supersedes the old one, so
    pricing the full 5 kg at $50 after a 2 kg entry is allowed and gives an actual cost."""
    org, _ = world
    item = lot(db, org.id, "Liquorice", 5, "kg")
    flow = _created_flow(db, org.id, item)
    price(db, org.id, item.id, 20, 2, cost_flow_id=flow.id)
    price(db, org.id, item.id, 50, 5, cost_flow_id=flow.id)
    cost = lot_cost(db, org.id, item.id)
    assert (D(cost["unit_cost"]), cost["status"]) == (D("10"), "actual")
    assert len([e for e in cost["entries"]]) == 1


def test_ac55_whole_lot_price_never_double_counts(world, db):
    org, _ = world
    from app.core.db.repositories.inventory_repo import InventoryRepository

    item = lot(db, org.id, "Cubeb", 2, "kg")
    price(db, org.id, item.id, 80, 2)  # whole-lot
    assert D(lot_cost(db, org.id, item.id)["unit_cost"]) == D("40")
    price(db, org.id, item.id, 90, 2, cost_flow_id=_created_flow(db, org.id, item).id)
    assert D(lot_cost(db, org.id, item.id)["unit_cost"]) == D("45"), "flow price wins; whole-lot prices nothing"

    other = lot(db, org.id, "Grains of Paradise", 2, "kg")
    price(db, org.id, other.id, 90, 2, cost_flow_id=_created_flow(db, org.id, other).id)
    InventoryRepository(db).add_quantity_to_inventory_item(other.id, org.id, "3")
    db.commit()
    price(db, org.id, other.id, 60, 3)  # whole-lot price $20/kg covers the unpriced 3 kg
    cost = lot_cost(db, org.id, other.id)
    assert (D(cost["unit_cost"]), cost["status"]) == (D("30"), "actual")


def test_ac56_one_active_whole_lot_price(world, db):
    org, _ = world
    from sqlalchemy.exc import IntegrityError

    from app.features.costing.models import LotCostEntry

    item = lot(db, org.id, "Lemon Peel", 1, "kg")
    first = price(db, org.id, item.id, 10, 1)
    price(db, org.id, item.id, 12, 1)
    db.expire_all()
    active = db.query(LotCostEntry).filter(LotCostEntry.inventory_item_id == item.id, LotCostEntry.is_active).all()
    assert len(active) == 1 and active[0].id != first.id
    assert D(lot_cost(db, org.id, item.id)["unit_cost"]) == D("12")

    db.add(
        LotCostEntry(
            org_id=org.id, inventory_item_id=item.id, kind="manual", amount=D("1"), quantity=D("1"), is_active=True
        )
    )
    with pytest.raises(IntegrityError):
        db.flush()
    db.rollback()


def test_ac57_production_lot_is_not_editable(world, db):
    org, client = world
    from app.features.costing.service import CostingError

    spirit = lot(db, org.id, "Spirit", 10, "L")
    execution, (step,) = workflow(db, org.id, [[{"name": "Gin", "unit": "bottles"}]])
    complete(client, execution, step, [(spirit, 10, "L")], [{"name": "Gin", "quantity": 10, "unit": "bottles"}])
    (gin,) = produced_lots(db, org.id, step.id)
    with pytest.raises(CostingError):
        price(db, org.id, gin.id, 100, 10)
    db.rollback()
    assert lot_cost(db, org.id, gin.id)["editable"] is False
    assert lot_cost(db, org.id, spirit.id)["editable"] is True


def test_ac58_last_known_price_picks_by_date_and_updates(world, db):
    org, _ = world
    oct1 = lot(db, org.id, "Coriander Seed", 1, "kg", purchase_date=date(2026, 10, 1))
    price(db, org.id, oct1.id, 40, 1)
    nov1 = lot(db, org.id, "Coriander Seed", 1, "kg", purchase_date=date(2026, 11, 1))
    price(db, org.id, nov1.id, 50, 1)
    mid_oct = lot(db, org.id, "Coriander Seed", 1, "kg", purchase_date=date(2026, 10, 15))
    early_nov = lot(db, org.id, "Coriander Seed", 1, "kg", purchase_date=date(2026, 11, 5))
    sept = lot(db, org.id, "Coriander Seed", 1, "kg", purchase_date=date(2026, 9, 1))

    assert D(lot_cost(db, org.id, mid_oct.id)["unit_cost"]) == 40
    assert D(lot_cost(db, org.id, early_nov.id)["unit_cost"]) == 50
    assert D(lot_cost(db, org.id, sept.id)["unit_cost"]) == 40  # earliest after

    oct10 = lot(db, org.id, "Coriander Seed", 1, "kg", purchase_date=date(2026, 10, 10))
    price(db, org.id, oct10.id, 44, 1)
    assert D(lot_cost(db, org.id, mid_oct.id)["unit_cost"]) == 44, "a newly costed nearer lot wins on the next read"

    set_last_known_price(db, org.id, False)
    for item in (mid_oct, early_nov, sept):
        assert lot_cost(db, org.id, item.id)["status"] == "unknown"


def test_ac59_estimates_do_not_chain(world, db):
    org, _ = world
    a = lot(db, org.id, "Cassia Bark", 1, "kg", purchase_date=date(2026, 11, 1))
    price(db, org.id, a.id, 50, 1)
    b = lot(db, org.id, "Cassia Bark", 1, "kg", purchase_date=date(2026, 10, 15))
    c = lot(db, org.id, "Cassia Bark", 1, "kg", purchase_date=date(2026, 10, 20))
    assert lot_cost(db, org.id, b.id)["estimate_from"]["inventory_item_id"] == str(a.id)
    assert lot_cost(db, org.id, c.id)["estimate_from"]["inventory_item_id"] == str(a.id), "B is an estimate"


def test_ac63_deleting_an_entry_falls_back(world, db):
    org, _ = world
    from app.features.costing import service
    from app.features.costing.models import LotCostEntry

    item = lot(db, org.id, "Pink Peppercorn", 1, "kg")
    entry = price(db, org.id, item.id, 30, 1)
    service.deactivate_entry(db, org.id, item.id, entry.id)
    db.commit()
    db.expire_all()
    row = db.get(LotCostEntry, entry.id)
    assert row is not None and row.is_active is False and row.deactivated_at is not None
    assert lot_cost(db, org.id, item.id)["status"] == "unknown"


# --- batch roll-up ---------------------------------------------------------------------


def _two_input_batch(db, org, client, outputs_def, produce):
    juniper = lot(db, org.id, "Juniper", 1, "kg")
    price(db, org.id, juniper.id, 45, 1)
    spirit = lot(db, org.id, "Spirit", 10, "L")
    price(db, org.id, spirit.id, 50, 10)
    execution, (step,) = workflow(db, org.id, [outputs_def])
    complete(client, execution, step, [(juniper, 1, "kg"), (spirit, 10, "L")], produce)
    return execution, step


def test_ac25_ac26_batch_cost_live_then_absorbed(world, db):
    org, client = world
    juniper = lot(db, org.id, "Juniper", 1, "kg")
    price(db, org.id, juniper.id, 45, 1)
    spirit = lot(db, org.id, "Spirit", 10, "L")
    price(db, org.id, spirit.id, 50, 10)
    execution, (macerate, bottle) = workflow(db, org.id, [[], [{"name": "Gin", "unit": "bottles"}]])

    complete(client, execution, macerate, [(juniper, 1, "kg"), (spirit, 10, "L")], [])
    live = execution_cost(db, org.id, execution.id)
    assert D(live["cost_so_far"]) == D("95") and live["outputs"] == []
    assert D(live["known_input_cost"]) == D("95")

    complete(client, execution, bottle, [], [{"name": "Gin", "quantity": 20, "unit": "bottles"}])
    done = execution_cost(db, org.id, execution.id)
    assert D(done["cost_so_far"]) == 0 and done["status"] == "actual"
    (out,) = done["outputs"]
    assert (D(out["unit_cost"]), out["status"], out["kind"]) == (D("4.75"), "actual", "produced")
    (gin,) = produced_lots(db, org.id, bottle.id)
    assert D(lot_cost(db, org.id, gin.id)["unit_cost"]) == D("4.75")


def test_ac25_input_in_a_different_unit(world, db):
    org, client = world
    juniper = lot(db, org.id, "Juniper", 1, "kg")
    price(db, org.id, juniper.id, 45, 1)
    execution, (step,) = workflow(db, org.id, [[{"name": "Gin", "unit": "bottles"}]])
    complete(client, execution, step, [(juniper, 500, "g")], [{"name": "Gin", "quantity": 9, "unit": "bottles"}])
    cost = execution_cost(db, org.id, execution.id)
    assert D(cost["known_input_cost"]) == D("22.5")
    assert D(cost["outputs"][0]["unit_cost"]) == D("2.5")


@pytest.mark.parametrize(
    ("case", "defs", "produce", "expected", "assumed"),
    [
        (
            "a-quantity",
            [{"name": "Hearts", "unit": "L"}, {"name": "Tails", "unit": "L"}],
            [{"name": "Hearts", "quantity": 8, "unit": "L"}, {"name": "Tails", "quantity": 2, "unit": "L"}],
            {"Hearts": "76", "Tails": "19"},
            False,
        ),
        (
            "b-byproduct",
            [{"name": "Hearts", "unit": "L"}, {"name": "Tails", "unit": "L", "cost_share": {"mode": "byproduct"}}],
            [{"name": "Hearts", "quantity": 8, "unit": "L"}, {"name": "Tails", "quantity": 2, "unit": "L"}],
            {"Hearts": "95", "Tails": "0"},
            False,
        ),
        (
            "c-incompatible",
            [{"name": "Gin", "unit": "bottles"}, {"name": "Botanical mash", "unit": "kg"}],
            [
                {"name": "Gin", "quantity": 19, "unit": "bottles"},
                {"name": "Botanical mash", "quantity": 3, "unit": "kg"},
            ],
            {"Gin": "95", "Botanical mash": "0"},
            True,
        ),
        (
            "d-percent-and-free",
            [
                {"name": "Hearts", "unit": "L", "cost_share": {"mode": "percent", "value": 30}},
                {"name": "Tails", "unit": "L"},
            ],
            [{"name": "Hearts", "quantity": 8, "unit": "L"}, {"name": "Tails", "quantity": 2, "unit": "L"}],
            {"Hearts": "28.5", "Tails": "66.5"},
            False,
        ),
        (
            "e-percents-over-100",
            [
                {"name": "Hearts", "unit": "L", "cost_share": {"mode": "percent", "value": 60}},
                {"name": "Tails", "unit": "L", "cost_share": {"mode": "percent", "value": 60}},
            ],
            [{"name": "Hearts", "quantity": 8, "unit": "L"}, {"name": "Tails", "quantity": 2, "unit": "L"}],
            {"Hearts": "47.5", "Tails": "47.5"},
            False,
        ),
        (
            "f-all-byproduct",
            [
                {"name": "Hearts", "unit": "L", "cost_share": {"mode": "byproduct"}},
                {"name": "Tails", "unit": "L", "cost_share": {"mode": "byproduct"}},
            ],
            [{"name": "Hearts", "quantity": 8, "unit": "L"}, {"name": "Tails", "quantity": 2, "unit": "L"}],
            {"Hearts": "76", "Tails": "19"},
            True,
        ),
        (
            "g-invalid-config-ignored",
            [
                {"name": "Hearts", "unit": "L", "cost_share": {"mode": "percent", "value": 150}},
                {"name": "Tails", "unit": "L", "cost_share": {"mode": "weird"}},
            ],
            [{"name": "Hearts", "quantity": 8, "unit": "L"}, {"name": "Tails", "quantity": 2, "unit": "L"}],
            {"Hearts": "76", "Tails": "19"},
            False,
        ),
        (
            "g2-zero-percent-ignored",
            [
                {"name": "Hearts", "unit": "L", "cost_share": {"mode": "percent", "value": 0}},
                {"name": "Tails", "unit": "L"},
            ],
            [{"name": "Hearts", "quantity": 8, "unit": "L"}, {"name": "Tails", "quantity": 2, "unit": "L"}],
            {"Hearts": "76", "Tails": "19"},
            False,
        ),
    ],
)
def test_ac27_split_rules(world, db, case, defs, produce, expected, assumed):
    org, client = world
    execution, _ = _two_input_batch(db, org, client, defs, produce)
    cost = execution_cost(db, org.id, execution.id)
    got = {o["name"]: D(o["known_amount"]) for o in cost["outputs"]}
    assert got == {k: D(v) for k, v in expected.items()}, case
    assert cost["split_assumed"] is assumed, case
    assert sum(got.values()) == D("95")


def test_ac27h_rounding_remainder_keeps_the_total(world, db):
    org, client = world
    item = lot(db, org.id, "Spirit", 10, "L")
    price(db, org.id, item.id, 100, 10)
    defs = [{"name": n, "unit": "L"} for n in ("A", "B", "C")]
    execution, (step,) = workflow(db, org.id, [defs])
    complete(client, execution, step, [(item, 10, "L")], [{"name": n, "quantity": 1, "unit": "L"} for n in "ABC"])
    amounts = sorted(D(o["known_amount"]) for o in execution_cost(db, org.id, execution.id)["outputs"])
    assert amounts == [D("33.3333"), D("33.3333"), D("33.3334")]


def test_ac28_unknown_input_makes_batch_partial_until_priced(world, db):
    org, client = world
    juniper = lot(db, org.id, "Juniper", 1, "kg")
    price(db, org.id, juniper.id, 45, 1)
    mystery = lot(db, org.id, "Mystery Root", 2, "kg")
    execution, (step,) = workflow(db, org.id, [[{"name": "Gin", "unit": "bottles"}]])
    complete(
        client,
        execution,
        step,
        [(juniper, 1, "kg"), (mystery, 2, "kg")],
        [{"name": "Gin", "quantity": 9, "unit": "bottles"}],
    )
    cost = execution_cost(db, org.id, execution.id)
    assert cost["status"] == "partial"
    assert [m["inventory_item_id"] for m in cost["missing"]] == [str(mystery.id)]
    assert D(cost["known_input_cost"]) == D("45")
    (out,) = cost["outputs"]
    assert out["unit_cost"] is None and D(out["known_unit_cost"]) == D("5") and out["status"] == "partial"
    (gin,) = produced_lots(db, org.id, step.id)
    assert lot_cost(db, org.id, gin.id)["unit_cost"] is None

    price(db, org.id, mystery.id, 18, 2)
    fixed = execution_cost(db, org.id, execution.id)
    assert fixed["status"] == "actual" and D(fixed["outputs"][0]["unit_cost"]) == D("7")


def test_ac29_two_steps_through_wip_counted_once_and_partial_floor_propagates(world, db):
    org, client = world
    juniper = lot(db, org.id, "Juniper", 1, "kg")
    price(db, org.id, juniper.id, 45, 1)
    spirit = lot(db, org.id, "Spirit", 10, "L")
    price(db, org.id, spirit.id, 50, 10)
    bottles = lot(db, org.id, "Glass bottle", 20, "units")
    price(db, org.id, bottles.id, 30, 20)
    execution, (s1, s2) = workflow(
        db, org.id, [[{"name": "Macerate", "unit": "L"}], [{"name": "Gin", "unit": "bottles"}]]
    )
    complete(
        client,
        execution,
        s1,
        [(juniper, 1, "kg"), (spirit, 10, "L")],
        [{"name": "Macerate", "quantity": 10, "unit": "L"}],
    )
    (macerate,) = produced_lots(db, org.id, s1.id)
    complete(
        client,
        execution,
        s2,
        [(macerate, 10, "L"), (bottles, 20, "units")],
        [{"name": "Gin", "quantity": 20, "unit": "bottles"}],
    )
    cost = execution_cost(db, org.id, execution.id)
    gin = by_name(cost["outputs"])["Gin"]
    assert D(gin["unit_cost"]) == D("6.25"), "(45 + 50 + 30) / 20, the WIP counted once"
    assert D(cost["known_input_cost"]) == D("125"), "WIP consumed in step 2 is internal, not a new input"

    # Same shape, with a step-1 input unknown.
    unknown = lot(db, org.id, "Unknown Botanical", 1, "kg")
    spirit2 = lot(db, org.id, "Spirit", 10, "L")
    price(db, org.id, spirit2.id, 50, 10)
    bottles2 = lot(db, org.id, "Glass bottle", 20, "units")
    price(db, org.id, bottles2.id, 30, 20)
    ex2, (t1, t2) = workflow(db, org.id, [[{"name": "Macerate", "unit": "L"}], [{"name": "Gin", "unit": "bottles"}]])
    complete(
        client, ex2, t1, [(unknown, 1, "kg"), (spirit2, 10, "L")], [{"name": "Macerate", "quantity": 10, "unit": "L"}]
    )
    (mac2,) = produced_lots(db, org.id, t1.id)
    complete(
        client,
        ex2,
        t2,
        [(mac2, 10, "L"), (bottles2, 20, "units")],
        [{"name": "Gin", "quantity": 20, "unit": "bottles"}],
    )
    wip = lot_cost(db, org.id, mac2.id)
    assert wip["status"] == "partial" and wip["unit_cost"] is None and D(wip["known_unit_cost"]) == D("5")
    out = by_name(execution_cost(db, org.id, ex2.id)["outputs"])["Gin"]
    assert out["status"] == "partial" and out["unit_cost"] is None
    assert D(out["known_unit_cost"]) == D("4"), "(50 + 30) / 20"
    assert [m["inventory_item_id"] for m in out["missing"]] == [str(unknown.id)]


def test_ac31_reconciled_output_carries_cost_to_untracked_lot(world, db):
    org, client = world
    spirit = lot(db, org.id, "Spirit", 6, "L")
    price(db, org.id, spirit.id, 30, 6)
    untracked = lot(db, org.id, "Gin Base", 10, "L", inventory_type=WIP, extra_data={"untracked": True})
    execution, (step,) = workflow(db, org.id, [[{"name": "Gin Base", "unit": "L"}]])
    complete(
        client,
        execution,
        step,
        [(spirit, 6, "L")],
        [{"name": "Gin Base", "quantity": 6, "unit": "L", "untracked_item_id": str(untracked.id)}],
    )
    rec = flows(db, org.id, untracked.id, kind="reconciled_in")
    assert len(rec) == 1 and D(str(rec[0].quantity)) == D("6")
    cost = execution_cost(db, org.id, execution.id)
    (out,) = cost["outputs"]
    assert out["kind"] == "reconciled_in" and out["inventory_item_id"] == str(untracked.id)
    assert D(out["known_amount"]) == D("30")
    assert D(lot_cost(db, org.id, untracked.id)["known_unit_cost"]) == D("5")


def test_ac53_library_stock_takes_no_share(world, db):
    org, client = world
    spirit = lot(db, org.id, "Spirit", 39, "L")
    price(db, org.id, spirit.id, 390, 39)
    execution, (step,) = workflow(db, org.id, [[{"name": "Gin", "unit": "bottles"}]])
    complete(
        client,
        execution,
        step,
        [(spirit, 39, "L")],
        [{"name": "Gin", "quantity": 78, "unit": "bottles", "library_remainder_ml": "350"}],
    )
    outs = by_name(execution_cost(db, org.id, execution.id)["outputs"])
    assert D(outs["Gin"]["unit_cost"]) == D("5")
    library = outs["Gin - Library stock"]
    assert D(library["known_amount"]) == 0
    library_cost = lot_cost(db, org.id, library["inventory_item_id"])
    assert (D(library_cost["unit_cost"]), library_cost["status"]) == (D("0"), "actual")


def test_ac60_cycle_is_partial_not_a_crash(world, db):
    org, client = world
    from app.features.costing.models import CostFlow

    seed = lot(db, org.id, "Feints", 5, "L")
    execution, (step,) = workflow(db, org.id, [[{"name": "Gin", "unit": "L"}]])
    complete(client, execution, step, [(seed, 5, "L")], [{"name": "Gin", "quantity": 4, "unit": "L"}])
    # Forge the loop: the batch also "produced" back into the lot it consumed.
    db.add(
        CostFlow(
            org_id=org.id,
            inventory_item_id=seed.id,
            direction="in",
            kind="produced",
            quantity=D("1"),
            execution_id=execution.id,
            execution_step_id=step.id,
            step_number=1,
            source_key=f"forged:{seed.id}",
            write_reason="test",
            reconstructed=False,
        )
    )
    db.commit()
    cost = lot_cost(db, org.id, seed.id)
    assert cost["status"] == "partial" and "cycle" in cost["warnings"]
    assert execution_cost(db, org.id, execution.id)["status"] in ("partial",)


def test_ac61_no_flow_history_then_backfill(world, db):
    org, client = world
    from app.features.costing.backfill import backfill_flows
    from app.features.costing.models import CostFlow

    juniper = lot(db, org.id, "Juniper", 1, "kg")
    price(db, org.id, juniper.id, 45, 1)
    execution, (step,) = workflow(db, org.id, [[{"name": "Gin", "unit": "bottles"}]])
    complete(client, execution, step, [(juniper, 1, "kg")], [{"name": "Gin", "quantity": 9, "unit": "bottles"}])
    db.query(CostFlow).filter(CostFlow.org_id == org.id, CostFlow.kind == "consumed").delete()
    db.commit()

    before = execution_cost(db, org.id, execution.id)
    assert before["status"] == "partial" and "no_flow_history" in before["warnings"]
    assert str(juniper.id) in [m["inventory_item_id"] for m in before["missing"]]

    backfill_flows(db, org.id)
    db.commit()
    after = execution_cost(db, org.id, execution.id)
    assert after["status"] == "actual" and D(after["outputs"][0]["unit_cost"]) == D("5")


def test_ac42_forged_cross_org_flow_is_ignored(world, db):
    org, client = world
    from app.features.costing.models import CostFlow

    other = new_org(db)
    try:
        theirs = lot(db, other.id, "Spirit", 10, "L")
        price(db, other.id, theirs.id, 1000, 10)
        mine = lot(db, org.id, "Spirit", 10, "L")
        execution, (step,) = workflow(db, org.id, [[{"name": "Gin", "unit": "L"}]])
        complete(client, execution, step, [(mine, 10, "L")], [{"name": "Gin", "quantity": 10, "unit": "L"}])
        # A consumed row in MY org pointing at THEIR lot must not pull their cost in.
        db.add(
            CostFlow(
                org_id=org.id,
                inventory_item_id=theirs.id,
                direction="out",
                kind="consumed",
                quantity=D("10"),
                execution_id=execution.id,
                execution_step_id=step.id,
                step_number=1,
                source_key=f"forged:{theirs.id}",
                write_reason="test",
                reconstructed=False,
            )
        )
        try:
            db.commit()
        except Exception:  # a composite (org_id, item) FK rejecting the forgery is also a pass
            db.rollback()
        cost = execution_cost(db, org.id, execution.id)
        assert D(cost["known_input_cost"]) < D("1000")
        assert str(theirs.id) not in [i["inventory_item_id"] for i in cost["inputs"]]
    finally:
        purge(db, other)


def test_unit_payload_precision(world, db):
    org, _ = world
    item = lot(db, org.id, "Saffron", 3, "g")
    price(db, org.id, item.id, 10, 3)
    cost = lot_cost(db, org.id, item.id)
    assert cost["unit_cost"] == "3.333333"
    assert Decimal(cost["priced_quantity"]).as_tuple().exponent == -4
