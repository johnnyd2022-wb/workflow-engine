"""Live-cogs 8.1h: the margins report shows materials and overheads apart (AC-OV15).

Written before the implementation. Reuses the margins world (sales, mapping, alcohol profile).
"""

# ruff: noqa: F811 -- world / flask_app are re-exported fixtures used as test arguments

from __future__ import annotations

from tests.costing_helpers import D, complete, output_defs, price, produced_lots, workflow
from tests.test_compliant_routes import flask_app  # noqa: F401 -- fixture re-export
from tests.test_costing_margins import GIN, _row, world  # noqa: F401 -- fixture re-export

API = "/api/core/costing"


def _bottled_batch(world, db):
    """10 x 700 mL bottles of the mapped product from $90 of spirit (7 L of finished product)."""
    from tests.costing_helpers import lot

    org, client = world["org"], world["client"]
    spirit = lot(db, org.id, "Neutral spirit", 10, "L")
    price(db, org.id, spirit.id, 90, 10)
    execution, (step,) = workflow(db, org.id, [[{"name": GIN, "unit": "bottles"}]])
    complete(
        client,
        execution,
        step,
        [(spirit, 10, "L")],
        [{"name": GIN, "quantity": 10, "unit": "bottles", "output_id": output_defs(step)[0]["id"]}],
    )
    (bottles,) = produced_lots(db, org.id, step.id)
    return bottles


def _settings(client, **body):
    response = client.put(f"{API}/settings", json=body)
    assert response.status_code == 200, response.get_json()


def _rate(client, name, basis, amount):
    response = client.post(
        f"{API}/overhead-rates",
        json={"name": name, "basis": basis, "amount": amount, "effective_from": "2026-01-01"},
    )
    assert response.status_code == 201, response.get_json()


def test_ac_ov15_margins_show_the_split(world, db):
    client = world["client"]
    bottles = _bottled_batch(world, db)
    inv = world["sell"]([("Wildflower Gin 700ml", 4, "200", "0")])
    world["allocate"](inv, "l1", bottles, 4)

    # Off: the row is exactly what it was, with no split.
    off = _row(world)
    assert D(off["cost"]) == D("36.00") and "materials_cost" not in off and "overhead_cost" not in off

    _rate(client, "Rent", "per_litre", "0.50")  # 7 L x 0.50 = 3.50
    _rate(client, "Labour", "per_batch", "40")
    _settings(client, include_overheads=True)

    row = _row(world)
    # 10 bottles cost 90 + 43.50 = 133.50: 13.35 each, of which 4.35 is overhead. 4 sold.
    assert D(row["cost"]) == D("53.40") and row["cost_status"] == "actual"
    assert D(row["materials_cost"]) == D("36.00") and D(row["overhead_cost"]) == D("17.40")
    assert D(row["materials_cost"]) + D(row["overhead_cost"]) == D(row["cost"])
    assert D(row["margin"]) == D("200") - D("53.40")
    assert D(row["average_cost_per_unit"]) == D("13.35")
