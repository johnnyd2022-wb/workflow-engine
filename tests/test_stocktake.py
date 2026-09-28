"""Plan item 2.6: stock position, counts, and a reason for every difference."""

import csv
import io
from datetime import date, timedelta
from decimal import Decimal

import pytest

from app.core.backend import stocktake
from app.core.db.models.inventory_item import InventoryItem
from app.core.db.models.inventory_wastage import InventoryWastage
from app.core.db.models.stock_location import StockLocation
from app.core.db.models.stocktake import Stocktake, StocktakeLine, StocktakeResolution
from app.core.domain.inventory_quantity_guard import InventoryQuantityWriteReason, allow_inventory_quantity_write
from app.features.compliant.models.excise import ExciseLodgement
from app.features.compliant.modules.nz_alcohol import excise
from app.features.compliant.modules.nz_alcohol.module import stocktake_alerts
from tests.test_compliant_routes import flask_app  # noqa: F401 -- fixture re-export
from tests.test_excise import GIN, world  # noqa: F401 -- fixture re-export

TODAY = date.today()


@pytest.fixture
def st(world):  # noqa: F811
    db, org = world["db"], world["org"]
    car = StockLocation(org_id=org.id, name="Sam's car", inside_licensed_area=False)
    db.add(car)
    db.commit()
    yield {**world, "car": car}
    db.rollback()
    for model in (StocktakeResolution, StocktakeLine, Stocktake):
        db.query(model).filter(model.org_id == org.id).delete(synchronize_session=False)
    db.query(InventoryWastage).filter(InventoryWastage.org_id == org.id).delete(synchronize_session=False)
    db.commit()


def _start(client, kind="scheduled"):
    resp = client.post("/api/core/stocktakes", json={"kind": kind})
    assert resp.status_code == 201, resp.get_json()
    return resp.get_json()


def _count(client, body, name_batch_counts):
    for line in body["lines"]:
        key = (line["place"], line["batch"])
        if key in name_batch_counts:
            resp = client.put(
                f"/api/core/stocktakes/{body['id']}/lines/{line['id']}", json={"counted": name_batch_counts[key]}
            )
            assert resp.status_code == 200, resp.get_json()
            body = resp.get_json()
    return body


def _line(body, batch, place="Licensed area (main)"):
    return next(ln for ln in body["lines"] if ln["batch"] == batch and ln["place"] == place)


MAIN = "Licensed area (main)"


def _set_qty(db, item_id, qty):
    with allow_inventory_quantity_write(InventoryQuantityWriteReason.MANUAL_API_UPDATE):
        db.get(InventoryItem, item_id).quantity = Decimal(qty)
        db.commit()


def test_stock_position_by_place_with_lal_and_lodged_entries(st):
    db, org, client = st["db"], st["org"], st["client"]
    vat44 = st["lot"]("VAT44", 50)
    st["repo"].move_lot(org.id, vat44.id, "6", st["car"].id, TODAY)
    db.add(
        ExciseLodgement(
            org_id=org.id,
            period_start=date(2026, 7, 1),
            period_end=date(2026, 7, 31),
            lodged_on=date(2026, 8, 10),
            entry_reference="=HYPERLINK()",
            snapshot={"lines": [], "total_lal": "1.5", "total_duty": "96.15"},
        )
    )
    db.commit()

    pos = client.get("/api/core/stock-position").get_json()
    main, car = pos["places"]
    assert main["name"] == MAIN and main["inside_licensed_area"] is True
    assert main["lots"][0]["quantity"] == "44" and main["lots"][0]["measure"] == "13.552"  # 44 x 0.7 x 44%
    assert car["name"] == "Sam's car" and car["inside_licensed_area"] is False and car["total_measure"] == "1.848"
    assert pos["declared"][0]["measure"] == "1.5" and pos["labels"]["measure"] == "LAL"
    assert main["lots"][0]["detail"] == "30.8 L at 44%"

    resp = client.get("/api/core/stock-position?format=csv")
    assert resp.status_code == 200 and resp.mimetype == "text/csv"
    rows = list(csv.reader(io.StringIO(resp.get_data(as_text=True))))
    assert [MAIN, "yes", "Finished", GIN, "VAT44", "44", "bottles", "30.8 L at 44%", "13.552"] in rows
    assert any(r[:4] == ["2026-07-01", "2026-07-31", "2026-08-10", "'=HYPERLINK()"] for r in rows)  # no formula


def test_matching_count_finishes_and_a_difference_blocks_finishing(st):
    client = st["client"]
    st["lot"]("VAT44", 50)
    st["lot"]("VAT45", 20)
    body = _start(client)
    assert body["summary"]["not_counted"] == 2
    assert client.post(f"/api/core/stocktakes/{body['id']}/complete").status_code == 409

    bad = client.put(f"/api/core/stocktakes/{body['id']}/lines/{_line(body, 'VAT44')['id']}", json={"counted": "1.5"})
    assert bad.status_code == 400 and "whole" in bad.get_json()["error"]

    body = _count(client, body, {(MAIN, "VAT44"): "50", (MAIN, "VAT45"): "18"})
    assert _line(body, "VAT44")["status"] == "matched"
    short = _line(body, "VAT45")
    assert short["status"] == "open" and short["variance"] == "-2" and short["variance_measure"] == "-0.616"
    assert short["variance_cost"] == "-39.49"  # 0.616 LAL x $64.10
    assert client.post(f"/api/core/stocktakes/{body['id']}/complete").status_code == 409


def test_expected_is_taken_at_count_time_so_sales_during_the_count_are_not_variances(st):
    client = st["client"]
    vat44 = st["lot"]("VAT44", 50)
    body = _start(client)
    st["sell"](vat44, "5", TODAY)
    _set_qty(st["db"], vat44.id, "45")  # what the sale allocation leaves on hand
    body = _count(client, body, {(MAIN, "VAT44"): "45"})
    assert _line(body, "VAT44")["status"] == "matched" and _line(body, "VAT44")["expected"] == "45"


def test_a_shortfall_split_across_a_rep_and_breakage(st):
    db, org, client = st["db"], st["org"], st["client"]
    vat44 = st["lot"]("VAT44", 50)
    body = _count(client, _start(client), {(MAIN, "VAT44"): "43"})
    line = _line(body, "VAT44")
    url = f"/api/core/stocktakes/{body['id']}/lines/{line['id']}/resolve"

    wrong_sum = client.post(url, json={"reasons": [{"reason": "broken", "quantity": "3"}]})
    assert wrong_sum.status_code == 400 and "add up to 7" in wrong_sum.get_json()["error"]
    wrong_kind = client.post(url, json={"reasons": [{"reason": "returned", "quantity": "7"}]})
    assert wrong_kind.status_code == 400
    no_place = client.post(url, json={"reasons": [{"reason": "found_elsewhere", "quantity": "7"}]})
    assert no_place.status_code == 400 and "where" in no_place.get_json()["error"]

    resp = client.post(
        url,
        json={
            "reasons": [
                {"reason": "found_elsewhere", "quantity": "4", "location_id": str(st["car"].id)},
                {"reason": "broken", "quantity": "3", "note": "Dropped case"},
            ]
        },
    )
    assert resp.status_code == 200, resp.get_json()
    body = resp.get_json()
    line = _line(body, "VAT44")
    assert line["status"] == "resolved"
    found, broken = line["resolutions"]
    assert found["place"] == "Sam's car" and found["dutiable"] is True
    assert broken["raise_with_customs"] is True and broken["note"] == "Dropped case"

    db.expire_all()
    assert db.get(InventoryItem, vat44.id).quantity == Decimal("43")
    in_car = db.query(InventoryItem).filter(InventoryItem.location_id == st["car"].id).one()
    assert in_car.quantity == Decimal("4") and in_car.supplier_batch_number == "VAT44"
    assert db.query(InventoryWastage).filter(InventoryWastage.inventory_item_id == vat44.id).count() == 1

    # The 4 in the car are a removal this month; the broken 3 aren't (remission).
    d = excise.draft(db, org.id, TODAY.replace(day=1), "monthly", today=TODAY)
    assert [(r["kind"], r["quantity"]) for r in d["lines"][0]["removals"]] == [("moved_out", "4")]

    assert client.post(url, json={"reasons": [{"reason": "broken", "quantity": "7"}]}).status_code == 400
    (gin,) = client.get(f"/api/core/stocktakes/{body['id']}/reconciliation").get_json()["products"]
    assert gin["variance"] == "-7" and gin["explained"] == "-7"
    assert client.post(f"/api/core/stocktakes/{body['id']}/complete").status_code == 200


def test_unrecorded_removals_and_unexplained_losses_are_dutiable(st):
    db, org, client = st["db"], st["org"], st["client"]
    st["lot"]("VAT44", 50)
    body = _count(client, _start(client, "customs_visit"), {(MAIN, "VAT44"): "45"})
    line = _line(body, "VAT44")
    resp = client.post(
        f"/api/core/stocktakes/{body['id']}/lines/{line['id']}/resolve",
        json={
            "reasons": [
                {"reason": "removed_unrecorded", "quantity": "2", "note": "Tasting samples"},
                {"reason": "unexplained_loss", "quantity": "3"},
            ]
        },
    )
    assert resp.status_code == 200, resp.get_json()
    samples, loss = _line(resp.get_json(), "VAT44")["resolutions"]
    assert samples["dutiable"] and not samples["raise_with_customs"]
    assert loss["dutiable"] and loss["raise_with_customs"] and loss["place"] == stocktake.LOSS_PLACE

    d = excise.draft(db, org.id, TODAY.replace(day=1), "monthly", today=TODAY)
    assert d["lines"][0]["units"] == "5"  # both are removals in this period
    refs = sorted(r["reference"] for r in d["lines"][0]["removals"])
    assert refs == [f"Moved to {stocktake.REMOVED_PLACE}", f"Moved to {stocktake.LOSS_PLACE}"]
    # The system places don't show up as places to pick.
    assert all(p["name"] not in (stocktake.REMOVED_PLACE, stocktake.LOSS_PLACE) for p in resp.get_json()["places"])


def test_surplus_came_back_from_a_rep_or_was_under_recorded(st):
    db, org, client = st["db"], st["org"], st["client"]
    vat44 = st["lot"]("VAT44", 50)
    st["repo"].move_lot(org.id, vat44.id, "6", st["car"].id, TODAY)
    db.commit()
    # Shelf holds 44 per the system; 48 counted: 3 came back from the car, 1 under-recorded.
    body = _count(client, _start(client), {(MAIN, "VAT44"): "48", ("Sam's car", "VAT44"): "3"})
    shelf = _line(body, "VAT44")
    car_line = _line(body, "VAT44", "Sam's car")
    assert shelf["variance"] == "4" and car_line["variance"] == "-3"

    resp = client.post(
        f"/api/core/stocktakes/{body['id']}/lines/{shelf['id']}/resolve",
        json={
            "reasons": [
                {"reason": "returned", "quantity": "3", "location_id": str(st["car"].id)},
                {"reason": "under_recorded", "quantity": "1"},
            ]
        },
    )
    assert resp.status_code == 200, resp.get_json()
    returned, under = _line(resp.get_json(), "VAT44")["resolutions"]
    assert returned["raise_with_customs"] is True and under["raise_with_customs"] is False
    db.expire_all()
    assert db.get(InventoryItem, vat44.id).quantity == Decimal("48")
    d = excise.draft(db, org.id, TODAY.replace(day=1), "monthly", today=TODAY)
    assert d["returns"][0]["quantity"] == "3"  # listed as a possible credit, not subtracted
    # The car's stock was removed when it left: the equation covers the licensed area only.
    (gin,) = client.get(f"/api/core/stocktakes/{body['id']}/reconciliation").get_json()["products"]
    assert gin["expected"] == "44" and gin["counted"] == "48" and gin["explained"] == "4"
    assert d["lines"][0]["units"] == "6"


def test_investigating_holds_the_line_on_the_alert_list_until_a_recount(st):
    db, org, client = st["db"], st["org"], st["client"]
    st["lot"]("VAT44", 50)
    body = _count(client, _start(client), {(MAIN, "VAT44"): "47"})
    line = _line(body, "VAT44")
    resp = client.post(
        f"/api/core/stocktakes/{body['id']}/lines/{line['id']}/resolve",
        json={"reasons": [{"reason": "investigating", "quantity": "3"}]},
    )
    body = resp.get_json()
    line = _line(body, "VAT44")
    assert line["status"] == "investigating"
    assert line["investigate_until"] == (TODAY + timedelta(days=14)).isoformat()
    assert client.post(f"/api/core/stocktakes/{body['id']}/complete").status_code == 200  # nothing blocks work

    alerts = stocktake_alerts(db, org.id, {}, TODAY)
    (variance,) = [a for a in alerts if a["id"].startswith("stocktake-variance-")]
    assert "-3 bottles" in variance["title"] and "0.924 LAL" in variance["description"]
    assert "$59.23 duty" in variance["description"]  # 0.924 x 64.10
    late = stocktake_alerts(db, org.id, {}, TODAY + timedelta(days=15))
    assert [a for a in late if a["id"].startswith("stocktake-variance-")][0]["overdue"] is True

    # Found them: recount the (finished) stocktake's line.
    resp = client.put(f"/api/core/stocktakes/{body['id']}/lines/{line['id']}", json={"counted": "50"})
    assert resp.status_code == 200 and _line(resp.get_json(), "VAT44")["status"] == "matched"
    assert not [a for a in stocktake_alerts(db, org.id, {}, TODAY) if a["id"].startswith("stocktake-variance-")]


def test_schedule_and_due_reminder(st):
    db, org, client = st["db"], st["org"], st["client"]
    assert stocktake.schedule(db, org.id, {}, TODAY)["next_due"] is None  # nothing to anchor on yet
    assert client.put("/api/core/stocktake-settings", json={"frequency": "weekly"}).status_code == 400
    assert client.put("/api/core/stocktake-settings", json={"bulk_tolerance_percent": "9"}).status_code == 400
    resp = client.put("/api/core/stocktake-settings", json={"frequency": "quarterly", "bulk_tolerance_percent": "1"})
    assert resp.status_code == 200, resp.get_json()

    st["lot"]("VAT44", 50)
    body = _count(client, _start(client), {(MAIN, "VAT44"): "50"})
    client.post(f"/api/core/stocktakes/{body['id']}/complete")
    listing = client.get("/api/core/stocktakes").get_json()
    assert listing["schedule"]["frequency"] == "quarterly"
    assert listing["schedule"]["next_due"] == stocktake._add_months(TODAY, 3).isoformat()

    settings = {"stocktake_frequency": "quarterly"}
    assert not stocktake_alerts(db, org.id, settings, TODAY)
    due_soon = stocktake_alerts(db, org.id, settings, stocktake._add_months(TODAY, 3) - timedelta(days=3))
    assert due_soon[0]["title"].startswith("Stocktake due") and due_soon[0]["overdue"] is False
    assert stocktake._add_months(date(2026, 1, 31), 1) == date(2026, 2, 28)

    # The profile form doesn't wipe the schedule (it doesn't send these keys).
    client.put("/api/compliant/profile", json={"enabled": True, "settings": {"alcohol_product_types": ["spirits"]}})
    assert client.get("/api/core/stocktakes").get_json()["schedule"]["frequency"] == "quarterly"


def test_bulk_liquid_within_tolerance_matches(st):
    client = st["client"]
    st["repo"].create_inventory_item(
        org_id=st["org"].id,
        name="Gin - in tank",
        quantity="1000",
        unit="L",
        inventory_type="work_in_progress",
        supplier_batch_number="VAT59",
        extra_data={"abv_percent": "60"},
    )
    body = _count(client, _start(client), {(MAIN, "VAT59"): "996"})
    assert _line(body, "VAT59")["status"] == "matched"  # 0.4% under, default tolerance 0.5%
    body = _count(client, body, {(MAIN, "VAT59"): "990"})
    tank = _line(body, "VAT59")
    assert tank["status"] == "open" and tank["bulk"] is True


def test_reconciliation_ties_opening_removals_and_losses_to_the_count(st):
    db, client = st["db"], st["client"]
    vat44 = st["lot"]("VAT44", 50)
    first = _count(client, _start(client), {(MAIN, "VAT44"): "50"})
    client.post(f"/api/core/stocktakes/{first['id']}/complete")
    db.query(Stocktake).filter(Stocktake.id == first["id"]).update({"counted_on": TODAY - timedelta(days=40)})
    db.commit()

    st["sell"](vat44, "12", TODAY - timedelta(days=20))
    _set_qty(db, vat44.id, "38")
    st["lot"]("VAT46", 24)  # bottled since
    db.commit()

    second = _count(client, _start(client), {(MAIN, "VAT44"): "36", (MAIN, "VAT46"): "24"})
    rec = client.get(f"/api/core/stocktakes/{second['id']}/reconciliation").get_json()
    (gin,) = rec["products"]
    assert gin["opening"] == "50" and gin["removed"] == "12" and gin["losses"] == "0"
    assert gin["expected"] == "62" and gin["produced_and_in"] == "24"
    assert gin["counted"] == "60" and gin["variance"] == "-2"
    assert rec["since"] == (TODAY - timedelta(days=40)).isoformat()


def test_other_tenants_cannot_see_or_touch_a_stocktake(st, db, flask_app):  # noqa: F811
    from tests.test_compliant_routes import _admin_client

    st["lot"]("VAT44", 50)
    body = _start(st["client"])
    other_org, other = _admin_client(db, flask_app)
    try:
        assert other.get(f"/api/core/stocktakes/{body['id']}").status_code == 404
        line = body["lines"][0]["id"]
        assert other.put(f"/api/core/stocktakes/{body['id']}/lines/{line}", json={"counted": "1"}).status_code == 404
    finally:
        from app.core.db.models.organisation import Organisation
        from tests.dag_traversal_helpers import clear_org_synthetic_data

        clear_org_synthetic_data(db, other_org.id)
        db.query(Organisation).filter(Organisation.id == other_org.id).delete(synchronize_session=False)
        db.commit()
