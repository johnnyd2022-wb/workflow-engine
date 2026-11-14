"""Multipacks are used by steps in the step's own units, and costed by the right share.

A lot of tonic held in ``cases`` of 24 × 200 mL: a step that uses 12 bottles takes half a case
and half a case's cost; one that uses 2.4 L takes the same. Packs live on the lot
(``extra_data["pack"]``) and are set through the inventory API.
"""

from decimal import Decimal
from uuid import UUID

import pytest

from tests.costing_helpers import (
    D,
    complete,
    execution_cost,
    flows,
    lot,
    lot_cost,
    new_org,
    price,
    purge,
    user_client,
    workflow,
)
from tests.test_compliant_routes import flask_app  # noqa: F401 -- fixture re-export

CASE = {"count": 24, "size": "200", "size_unit": "ml"}


@pytest.fixture
def world(db, flask_app):  # noqa: F811
    org = new_org(db)
    client = user_client(db, flask_app, org)
    yield org, client
    purge(db, org)


def _cases(db, org, quantity=2, pack=CASE):
    tonic = lot(db, org.id, "Tonic 24 x 200 mL", quantity, "cases", extra_data={"pack": pack} if pack else None)
    db.commit()
    return tonic


def _quantity(db, item):
    db.expire_all()
    db.refresh(item)
    return D(str(item.quantity))


def test_create_stores_a_pack_from_text_and_returns_it(world, db):
    org, client = world
    response = client.post(
        "/api/core/inventory",
        json={"name": "Tonic", "quantity": "2", "unit": "cases", "pack": "24 x 200 mL"},
    )
    assert response.status_code == 201, response.get_json()
    assert response.get_json()["pack"] == CASE
    from app.core.db.models.inventory_item import InventoryItem

    item = db.get(InventoryItem, UUID(response.get_json()["id"]))
    assert item.extra_data["pack"] == CASE


def test_create_rejects_an_unreadable_pack_and_creates_nothing(world, db):
    org, client = world
    from app.core.db.models.inventory_item import InventoryItem

    response = client.post(
        "/api/core/inventory", json={"name": "Tonic", "quantity": "2", "unit": "cases", "pack": "a few"}
    )
    assert response.status_code == 400
    assert "Pack size" in response.get_json()["error"]
    assert db.query(InventoryItem).filter(InventoryItem.org_id == org.id).count() == 0


def test_metadata_cannot_smuggle_an_unchecked_pack(world, db):
    org, client = world
    response = client.post(
        "/api/core/inventory",
        json={"name": "Tonic", "quantity": "2", "unit": "cases", "metadata": {"pack": "6 x 700ml"}},
    )
    assert response.status_code == 201
    # metadata's pack is read through the same parser, never stored raw
    assert response.get_json()["pack"] == {"count": 6, "size": "700", "size_unit": "ml"}
    bad = client.post(
        "/api/core/inventory",
        json={"name": "Tonic", "quantity": "2", "unit": "cases", "metadata": {"pack": {"count": -1}}},
    )
    assert bad.status_code == 400


def test_update_sets_and_clears_the_pack_and_records_it(world, db):
    org, client = world
    tonic = _cases(db, org, pack=None)
    body = {"name": tonic.name, "quantity": "2", "unit": "cases"}
    set_response = client.put(f"/api/core/inventory/{tonic.id}", json={**body, "pack": "24 x 200 mL"})
    assert set_response.status_code == 200 and set_response.get_json()["pack"] == CASE
    from app.core.db.models.entity_event import EntityEvent

    db.expire_all()
    event = (
        db.query(EntityEvent)
        .filter(EntityEvent.entity_id == tonic.id, EntityEvent.event_type == "inventory_item.updated")
        .one()
    )
    assert event.diff["pack"] == {"before": None, "after": "24 × 200 mL"}
    # an edit that doesn't mention the pack keeps it, even when it sends metadata
    keep = client.put(f"/api/core/inventory/{tonic.id}", json={**body, "metadata": {"notes": "x"}})
    assert keep.get_json()["pack"] == CASE
    cleared = client.put(f"/api/core/inventory/{tonic.id}", json={**body, "pack": None})
    assert cleared.get_json()["pack"] is None
    assert client.put(f"/api/core/inventory/{tonic.id}", json={**body, "pack": "lots"}).status_code == 400


def test_barcode_readd_keeps_the_products_pack(world, db):
    org, client = world
    first = {"name": "Tonic", "quantity": "1", "unit": "cases", "barcode": "9400000000017", "pack": "24 x 200 mL"}
    assert client.post("/api/core/inventory", json=first).status_code == 201
    again = client.post("/api/core/inventory", json={**first, "pack": "24 x 200 mL"})
    assert again.status_code == 200
    clash = client.post("/api/core/inventory", json={**first, "pack": "6 x 700 mL"})
    assert clash.status_code == 409 and "24 × 200 mL" in clash.get_json()["error"]


def test_step_using_bottles_takes_half_a_case_and_half_its_cost(world, db):
    org, client = world
    tonic = _cases(db, org)
    (created,) = flows(db, org.id, tonic.id, kind="created")
    price(db, org.id, tonic.id, 96, 2, cost_flow_id=created.id)  # $48 a case = $2 a bottle
    execution, (step,) = workflow(db, org.id, [[{"name": "G&T", "unit": "cans"}]])
    complete(client, execution, step, [(tonic, 12, "bottles")], [{"name": "G&T", "quantity": 12, "unit": "cans"}])

    assert _quantity(db, tonic) == D("1.5")
    (consumed,) = flows(db, org.id, tonic.id, kind="consumed")
    assert D(str(consumed.quantity)) == D("0.5")
    cost = execution_cost(db, org.id, execution.id)
    assert D(cost["known_input_cost"]) == D("24"), "12 bottles × $2"
    assert D(cost["outputs"][0]["unit_cost"]) == D("2")


def test_step_using_litres_reads_the_pack_volume(world, db):
    org, client = world
    tonic = _cases(db, org)
    execution, (step,) = workflow(db, org.id, [[{"name": "Mix", "unit": "L"}]])
    complete(client, execution, step, [(tonic, Decimal("2.4"), "L")], [{"name": "Mix", "quantity": 2, "unit": "L"}])
    assert _quantity(db, tonic) == D("1.5"), "2.4 L of 4.8 L cases is half a case"


def test_without_a_pack_bottles_from_cases_is_still_refused(world, db):
    org, client = world
    tonic = _cases(db, org, pack=None)
    execution, (step,) = workflow(db, org.id, [[{"name": "G&T", "unit": "cans"}]])
    response = complete(
        client,
        execution,
        step,
        [(tonic, 12, "bottles")],
        [{"name": "G&T", "quantity": 12, "unit": "cans"}],
        expect=400,
    )
    assert any("units are incompatible" in d for d in response.get_json()["details"])
    assert _quantity(db, tonic) == D("2")


def test_using_more_bottles_than_the_cases_hold_is_refused(world, db):
    org, client = world
    tonic = _cases(db, org)
    execution, (step,) = workflow(db, org.id, [[{"name": "G&T", "unit": "cans"}]])
    response = complete(
        client, execution, step, [(tonic, 49, "bottles")], [{"name": "G&T", "quantity": 1, "unit": "cans"}], expect=400
    )
    assert any("exceeds available" in d for d in response.get_json()["details"])


def test_stock_check_reads_consumption_through_the_pack(world, db):
    org, client = world
    tonic = _cases(db, org)
    execution, (step,) = workflow(db, org.id, [[{"name": "G&T", "unit": "cans"}]])
    complete(client, execution, step, [(tonic, 12, "bottles")], [{"name": "G&T", "quantity": 12, "unit": "cans"}])
    from app.features.inventory.checks import stock_integrity

    db.expire_all()
    result = stock_integrity.run_stock_integrity_check(org.id, db)
    mine = [a for a in result.data["system_alerts"] if a["id"].startswith(f"stock:{tonic.id}:")]
    assert mine == [], mine


def test_backfill_converts_bottles_through_the_pack(world, db):
    org, client = world
    tonic = _cases(db, org)
    execution, (step,) = workflow(db, org.id, [[{"name": "G&T", "unit": "cans"}]])
    complete(client, execution, step, [(tonic, 12, "bottles")], [{"name": "G&T", "quantity": 12, "unit": "cans"}])
    from app.features.costing.backfill import backfill_flows
    from app.features.costing.models import CostFlow

    db.query(CostFlow).filter(CostFlow.org_id == org.id).delete()
    db.commit()
    result = backfill_flows(db, org.id)
    db.commit()
    (consumed,) = flows(db, org.id, tonic.id, kind="consumed")
    assert D(str(consumed.quantity)) == D("0.5") and result["skipped_inputs"] == 0


def test_wastage_in_bottles_from_a_lot_of_cases(world, db):
    org, client = world
    tonic = _cases(db, org)
    response = client.post(
        "/api/core/inventory/wastage",
        json={
            "entries": [
                {
                    "inventory_item_id": str(tonic.id),
                    "quantity_wasted": "6",
                    "quantity_unit": "bottles",
                    "reason": "damaged",
                }
            ]
        },
    )
    assert response.status_code in (200, 201), response.get_json()
    assert _quantity(db, tonic) == D("1.75")


def test_a_case_used_one_bottle_at_a_time_runs_out_exactly(world, db):
    """1/24 of a case is 0.0417 at storage precision; 24 single bottles must still empty one case,
    and the stock check must see the lot as balanced and whole all the way down."""
    org, client = world
    tonic = _cases(db, org, quantity=1)
    from app.features.inventory.checks import stock_integrity

    for n in range(24):
        execution, (step,) = workflow(db, org.id, [[{"name": "G&T", "unit": "cans"}]])
        complete(client, execution, step, [(tonic, 1, "bottles")], [{"name": "G&T", "quantity": 1, "unit": "cans"}])
        if n in (0, 11, 22):
            db.expire_all()
            alerts = stock_integrity.run_stock_integrity_check(org.id, db).data["system_alerts"]
            assert [a for a in alerts if a["id"].startswith(f"stock:{tonic.id}:")] == [], (n, alerts)
    assert _quantity(db, tonic) == D("0")
    consumed = flows(db, org.id, tonic.id, kind="consumed")
    assert sum(D(str(f.quantity)) for f in consumed) == D("1"), "the flows add up to the case they emptied"
    execution, (step,) = workflow(db, org.id, [[{"name": "G&T", "unit": "cans"}]])
    complete(
        client, execution, step, [(tonic, 1, "bottles")], [{"name": "G&T", "quantity": 1, "unit": "cans"}], expect=400
    )


def test_stock_check_flags_a_part_bottle(world, db):
    org, client = world
    tonic = _cases(db, org)
    execution, (step,) = workflow(db, org.id, [[{"name": "Mix", "unit": "L"}]])
    complete(client, execution, step, [(tonic, Decimal("0.1"), "L")], [{"name": "Mix", "quantity": 1, "unit": "L"}])
    from app.features.inventory.checks import stock_integrity

    db.expire_all()
    alerts = stock_integrity.run_stock_integrity_check(org.id, db).data["system_alerts"]
    codes = [a["id"].rsplit(":", 1)[1] for a in alerts if a["id"].startswith(f"stock:{tonic.id}:")]
    assert codes == ["fractional_count"], "100 mL leaves half a bottle open"


def test_csv_pack_size_column_is_checked_and_stored(world, db):
    org, client = world
    from app.core.db.models.inventory_item import InventoryItem

    text = "Item Name,Quantity,Unit,Pack Size\nTonic,2,units,24 x 200 mL\nCorks,100,units,\n"
    body = client.post("/api/core/inventory/csv-validate", data=text, content_type="text/csv").get_json()
    assert body["summary"]["problems"] == 0, body
    assert [r["pack"] for r in body["rows"]] == ["24 x 200 mL", None]
    committed = client.post("/api/core/inventory/csv-commit", json={"rows": body["rows"]})
    assert committed.status_code == 200, committed.get_json()
    db.expire_all()
    by_name = {i.name: i for i in db.query(InventoryItem).filter(InventoryItem.org_id == org.id)}
    assert by_name["Tonic"].extra_data["pack"] == CASE
    assert "pack" not in (by_name["Corks"].extra_data or {})

    bad = client.post(
        "/api/core/inventory/csv-validate",
        data="Item Name,Quantity,Unit,Pack Size\nTonic,2,units,a few\n",
        content_type="text/csv",
    ).get_json()
    (problem,) = bad["validation"]
    assert problem["status"] == "error" and "Pack size" in problem["message"]
    # a bad pack posted straight to commit is refused too
    rows = [{"row_index": 2, "name": "Lime", "quantity": "1", "unit": "units", "pack": "lots"}]
    assert client.post("/api/core/inventory/csv-commit", json={"rows": rows}).status_code == 400


def test_labels_from_a_box_of_500_take_their_share_of_the_box_price(world, db):
    org, client = world
    labels = lot(db, org.id, "Front labels", 2, "boxes", extra_data={"pack": {"count": 500}})
    db.commit()
    (created,) = flows(db, org.id, labels.id, kind="created")
    price(db, org.id, labels.id, 100, 2, cost_flow_id=created.id)  # $50 a box = 10c a label
    execution, (step,) = workflow(db, org.id, [[{"name": "Labelled", "unit": "pcs"}]])
    complete(client, execution, step, [(labels, 125, "pcs")], [{"name": "Labelled", "quantity": 125, "unit": "pcs"}])

    assert _quantity(db, labels) == D("1.75"), "125 of 500 is a quarter of a box"
    cost = execution_cost(db, org.id, execution.id)
    assert D(cost["known_input_cost"]) == D("12.5") and D(cost["outputs"][0]["unit_cost"]) == D("0.1")


def test_a_lot_cost_shows_its_price_per_bottle_and_per_litre(world, db):
    org, client = world
    tonic = _cases(db, org)
    (created,) = flows(db, org.id, tonic.id, kind="created")
    price(db, org.id, tonic.id, 96, 2, cost_flow_id=created.id)  # $48 a case of 24 × 200 mL
    cost = lot_cost(db, org.id, tonic.id)
    assert D(cost["unit_cost"]) == D("48")
    split = cost["pack_breakdown"]
    assert split["pack"] == "24 × 200 mL" and split["containers"] == 24
    assert D(split["per_container"]) == D("2") and D(split["per_litre"]) == D("10") and split["per_kg"] is None


def test_an_unpriced_pack_lot_shows_no_breakdown_and_a_plain_lot_none(world, db):
    org, client = world
    tonic = _cases(db, org)  # no price yet: unknown is never $0 per bottle
    cost = lot_cost(db, org.id, tonic.id)
    assert cost["unit_cost"] is None and cost["pack_breakdown"] is None
    plain = lot(db, org.id, "Corks", 10, "units")
    db.commit()
    (created,) = flows(db, org.id, plain.id, kind="created")
    price(db, org.id, plain.id, 5, 10, cost_flow_id=created.id)
    assert lot_cost(db, org.id, plain.id)["pack_breakdown"] is None


def test_barcode_lookup_returns_the_stored_pack(world, db):
    org, client = world
    first = {"name": "Tonic", "quantity": "1", "unit": "cases", "barcode": "9400000000024", "pack": "24 x 200 mL"}
    assert client.post("/api/core/inventory", json=first).status_code == 201
    response = client.get("/api/core/inventory/barcode/9400000000024")
    assert response.get_json()["product"]["pack"] == "24 × 200 mL"
