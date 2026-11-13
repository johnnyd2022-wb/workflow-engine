"""Live-cogs 8.1e-2: costing with no Xero bank feed — cost on every Add Inventory path.

Spec .agents/specs/live-cogs.md, "8.1e-2 build contract". Written before the implementation.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

import pytest

from app.core.db.models.inventory_item import InventoryItem
from app.core.db.models.user import UserRole
from app.features.costing.models import CostFlow, LotCostEntry
from tests.costing_helpers import (
    complete,
    execution_cost,
    lot_cost,
    new_org,
    output_defs,
    purge,
    user_client,
    workflow,
)
from tests.test_compliant_routes import flask_app  # noqa: F401 -- fixture re-export

API = "/api/core/costing"
D = Decimal


@pytest.fixture
def world(db, flask_app):  # noqa: F811
    org = new_org(db)
    client = user_client(db, flask_app, org)
    yield org, client
    purge(db, org)


def _add(client, key=True, **body):
    payload = {"name": "Kawakawa", "quantity": "5", "unit": "kg", "inventory_type": "raw_material", **body}
    headers = {"Idempotency-Key": str(uuid4())} if key else {}
    return client.post("/api/core/inventory", json=payload, headers=headers)


def _entries(db, item_id):
    db.expire_all()
    return db.query(LotCostEntry).filter(LotCostEntry.inventory_item_id == item_id, LotCostEntry.is_active).all()


# --- AC93: who sees cost -------------------------------------------------------------------------------


def test_ac93_me_for_a_manager_without_xero(world, db):
    org, client = world
    response = client.get(f"{API}/me")
    assert response.status_code == 200
    body = response.get_json()
    assert (body["enabled"], body["can_view"], body["can_manage"], body["xero_connected"]) == (True, True, True, False)
    assert body["purchases_to_record"] == 0


def test_ac93_me_without_costs_view_is_200_and_reveals_nothing(world, db, flask_app):  # noqa: F811
    org, _ = world
    production = user_client(db, flask_app, org, role=UserRole.PRODUCTION)
    response = production.get(f"{API}/me")
    assert response.status_code == 200
    body = response.get_json()
    assert body["enabled"] is False and body["can_view"] is False and body["can_manage"] is False
    assert body.get("purchases_to_record") is None and body.get("xero_connected") is None


def test_ac93_me_without_the_feature_is_200_disabled(db, flask_app):  # noqa: F811
    org = new_org(db, grant=False)
    try:
        body = user_client(db, flask_app, org).get(f"{API}/me").get_json()
        assert body["enabled"] is False and body["can_view"] is False and body["can_manage"] is False
    finally:
        purge(db, org)


def test_ac93_me_with_xero_connected(world, db):
    from tests.test_costing_purchases import connect

    org, client = world
    connect(db, org.id)
    assert client.get(f"{API}/me").get_json()["xero_connected"] is True


# --- AC91: barcode add-quantity carries a price -----------------------------------------------------------


def test_ac91_barcode_add_quantity_prices_the_added_flow(world, db):
    org, client = world
    first = _add(client, barcode="9400000000024", total_paid="50")
    assert first.status_code == 201, first.get_json()
    item_id = first.get_json()["id"]
    (original,) = _entries(db, item_id)

    again = _add(client, barcode="9400000000024", quantity="3", total_paid="30")
    assert again.status_code == 200, again.get_json()
    assert again.get_json()["quantity_added"] is True
    entries = _entries(db, item_id)
    assert len(entries) == 2
    new = next(e for e in entries if e.id != original.id)
    flow = db.get(CostFlow, new.cost_flow_id)
    assert flow.kind == "added" and D(str(flow.quantity)) == D("3")
    assert (D(str(new.amount)), D(str(new.quantity))) == (D("30"), D("3"))
    assert (D(str(original.amount)), D(str(original.quantity))) == (D("50"), D("5")), "earlier price untouched"
    assert D(lot_cost(db, org.id, item_id)["unit_cost"]) == D("10")


def test_ac91_barcode_add_quantity_pricing_failure_adds_nothing(world, db, monkeypatch):
    from app.features.costing import service

    org, client = world
    item_id = _add(client, barcode="9400000000031").get_json()["id"]

    def broken(*_a, **_k):
        raise service.CostingError("no price for you")

    monkeypatch.setattr(service, "set_lot_price", broken)
    response = _add(client, barcode="9400000000031", quantity="3", total_paid="30")
    assert response.status_code == 400
    db.expire_all()
    assert D(str(db.get(InventoryItem, item_id).quantity)) == D("5")
    assert db.query(CostFlow).filter(CostFlow.inventory_item_id == item_id, CostFlow.kind == "added").count() == 0


def test_ac91_barcode_add_quantity_bad_total_paid_is_400_before_adding(world, db):
    org, client = world
    item_id = _add(client, barcode="9400000000048").get_json()["id"]
    assert _add(client, barcode="9400000000048", quantity="3", total_paid="-1").status_code == 400
    db.expire_all()
    assert D(str(db.get(InventoryItem, item_id).quantity)) == D("5")


def test_ac97_barcode_add_quantity_ignores_total_paid_without_costs_manage(world, db, flask_app):  # noqa: F811
    org, client = world
    item_id = _add(client, barcode="9400000000055").get_json()["id"]
    production = user_client(db, flask_app, org, role=UserRole.PRODUCTION)
    response = _add(production, barcode="9400000000055", quantity="3", total_paid="30")
    assert response.status_code == 200
    assert _entries(db, item_id) == []


# --- AC92: CSV upload carries a price ---------------------------------------------------------------------


CSV = "Item Name,Quantity,Total Paid,Unit\nOrris root,2,40,kg\nAngelica,4,,kg\n"


def _validate(client, text):
    return client.post("/api/core/inventory/csv-validate", data=text, content_type="text/csv")


def test_ac92_csv_template_has_total_paid_after_quantity(world, db):
    _, client = world
    header = client.get("/api/core/inventory/csv-template").get_data(as_text=True).splitlines()[0]
    columns = [c.strip() for c in header.split(",")]
    assert columns.index("Total Paid") == columns.index("Quantity") + 1


def test_ac92_csv_rows_with_total_paid_are_priced(world, db):
    org, client = world
    body = _validate(client, CSV).get_json()
    assert body["summary"]["problems"] == 0, body
    assert body.get("total_paid_ignored") is not True
    rows = body["rows"]
    assert [r.get("total_paid") for r in rows] == ["40", None]
    committed = client.post("/api/core/inventory/csv-commit", json={"rows": rows})
    assert committed.status_code == 200, committed.get_json()
    by_name = {c["name"]: c["id"] for c in committed.get_json()["created"]}
    (entry,) = _entries(db, by_name["Orris root"])
    assert (D(str(entry.amount)), D(str(entry.quantity))) == (D("40"), D("2"))
    assert entry.cost_flow_id is not None
    assert _entries(db, by_name["Angelica"]) == []
    assert D(lot_cost(db, org.id, by_name["Orris root"])["unit_cost"]) == D("20")


@pytest.mark.parametrize("bad", ["-5", "abc", "1.00001"])
def test_ac92_csv_bad_total_paid_is_a_row_problem(world, db, bad):
    _, client = world
    body = _validate(client, f"Item Name,Quantity,Total Paid,Unit\nOrris root,2,{bad},kg\n").get_json()
    (problem,) = body["validation"]
    assert problem["status"] == "error" and "total paid" in problem["message"].lower()


def test_ac92_csv_commit_rejects_a_bad_total_paid_even_if_posted_directly(world, db):
    org, client = world
    rows = [{"row_index": 2, "name": "Orris root", "quantity": "2", "unit": "kg", "total_paid": "-5"}]
    response = client.post("/api/core/inventory/csv-commit", json={"rows": rows})
    assert response.status_code == 400
    db.expire_all()
    assert (
        db.query(InventoryItem).filter(InventoryItem.org_id == org.id, InventoryItem.name == "Orris root").count() == 0
    )


def test_ac92_csv_total_paid_ignored_without_costs_manage(world, db, flask_app):  # noqa: F811
    org, _ = world
    production = user_client(db, flask_app, org, role=UserRole.PRODUCTION)
    body = _validate(production, CSV).get_json()
    assert body["total_paid_ignored"] is True and body["summary"]["problems"] == 0
    committed = production.post("/api/core/inventory/csv-commit", json={"rows": body["rows"]})
    assert committed.status_code == 200
    for created in committed.get_json()["created"]:
        assert _entries(db, created["id"]) == []


def test_ac92_csv_pricing_failure_commits_no_rows(world, db, monkeypatch):
    from app.features.costing import service

    org, client = world
    rows = _validate(client, CSV).get_json()["rows"]

    def broken(*_a, **_k):
        raise RuntimeError("boom")

    monkeypatch.setattr(service, "set_lot_price", broken)
    response = client.post("/api/core/inventory/csv-commit", json={"rows": rows})
    assert response.status_code == 500
    db.expire_all()
    names = {"Orris root", "Angelica"}
    assert db.query(InventoryItem).filter(InventoryItem.org_id == org.id, InventoryItem.name.in_(names)).count() == 0


# --- AC94: the whole loop with no Xero at all ---------------------------------------------------------------


def test_ac94_no_xero_org_gets_an_actual_bottle_cost(world, db):
    org, client = world
    made = _add(client, name="Neutral spirit", quantity="10", unit="L", total_paid="80")
    assert made.status_code == 201
    spirit = db.get(InventoryItem, made.get_json()["id"])
    execution, (step,) = workflow(db, org.id, [[{"name": "Gin", "unit": "bottles"}]])
    complete(client, execution, step, [(spirit, 10, "L")], [{"name": "Gin", "quantity": 20, "unit": "bottles"}])
    cost = execution_cost(db, org.id, execution.id)
    assert cost["status"] == "actual" and D(cost["known_input_cost"]) == D("80")
    (gin,) = cost["outputs"]
    assert D(gin["unit_cost"]) == D("4"), "80 / 20 bottles"
    key = f"output:{output_defs(step)[0]['id']}"
    assert client.get(f"{API}/readiness/{key}").get_json()["ready"] is True
    assert client.get(f"{API}/me").get_json()["xero_connected"] is False


# --- 8.1e-2 review round 1 regressions -------------------------------------------------------------------


def test_r1_changing_what_was_paid_replaces_the_flow_price(world, db):
    org, client = world
    item_id = _add(client, total_paid="50").get_json()["id"]  # $10/kg on the created flow
    changed = client.put(
        f"{API}/lots/{item_id}/cost",
        json={"kind": "manual", "amount": "100", "quantity": "5", "replace": "all"},
        headers={"Idempotency-Key": str(uuid4())},
    )
    assert changed.status_code == 200, changed.get_json()
    assert D(changed.get_json()["unit_cost"]) == D("20")
    assert len(_entries(db, item_id)) == 1
    free = client.put(
        f"{API}/lots/{item_id}/cost", json={"kind": "free", "replace": "all"}, headers={"Idempotency-Key": str(uuid4())}
    )
    assert (D(free.get_json()["unit_cost"]), free.get_json()["status"]) == (D("0"), "actual")


def test_r1_lot_panel_says_which_batch_made_it(world, db):
    from tests.costing_helpers import produced_lots

    org, client = world
    spirit = db.get(
        InventoryItem, _add(client, name="Neutral spirit", quantity="10", unit="L", total_paid="80").get_json()["id"]
    )
    execution, (step,) = workflow(db, org.id, [[{"name": "Gin", "unit": "bottles"}]])
    complete(client, execution, step, [(spirit, 10, "L")], [{"name": "Gin", "quantity": 20, "unit": "bottles"}])
    (gin,) = produced_lots(db, org.id, step.id)
    provenance = client.get(f"{API}/lots/{gin.id}/cost").get_json()["provenance"]
    assert provenance["kind"] == "batch" and provenance["href"].startswith("/core/")
    assert provenance["href"].endswith(f"?execution={gin.source_execution_id}"), "links to that batch, not the board"
    assert client.get(f"{API}/lots/{spirit.id}/cost").get_json()["provenance"] is None, "typed by hand"


def test_r1_csv_commit_lost_reply_replays_and_adds_once(world, db):
    org, client = world
    rows = _validate(client, CSV).get_json()["rows"]
    key = {"Idempotency-Key": str(uuid4())}
    first = client.post("/api/core/inventory/csv-commit", json={"rows": rows}, headers=key)
    again = client.post("/api/core/inventory/csv-commit", json={"rows": rows}, headers=key)
    assert first.status_code == again.status_code == 200
    assert again.headers.get("Idempotent-Replay") == "true"
    db.expire_all()
    assert (
        db.query(InventoryItem).filter(InventoryItem.org_id == org.id, InventoryItem.name == "Orris root").count() == 1
    )


def test_r1_rule_and_cost_writes_replay_on_retry(world, db):
    org, client = world
    key = {"Idempotency-Key": str(uuid4())}
    body = {"payee_pattern": "Retry Co", "match_type": "exact", "treatment": "not_stock"}
    first = client.post(f"{API}/rules", json=body, headers=key)
    again = client.post(f"{API}/rules", json=body, headers=key)
    assert first.status_code == again.status_code == 201 and first.get_json()["id"] == again.get_json()["id"]
    item_id = _add(client).get_json()["id"]
    put_key = {"Idempotency-Key": str(uuid4())}
    price = {"kind": "manual", "amount": "25", "quantity": "5", "replace": "all"}
    client.put(f"{API}/lots/{item_id}/cost", json=price, headers=put_key)
    client.put(f"{API}/lots/{item_id}/cost", json=price, headers=put_key)
    from app.features.costing.models import LotCostEntry as Entry

    db.expire_all()
    assert db.query(Entry).filter(Entry.inventory_item_id == item_id).count() == 1, "no second (inactive) entry"


def test_r1_csv_escape_encodes_quotes_for_attributes():
    from pathlib import Path

    html = (Path(__file__).resolve().parents[1] / "app/core/frontend/inventory/add_csv.html").read_text()
    body = html[html.index("function escapeHtml") : html.index("function escapeHtml") + 400]
    assert "&quot;" in body and "&#39;" in body
