"""GL-P08: goods leaving the CCA are either transferred to another CCA or entered for duty.

A sale to a customer linked to another business's CCA (a duty free shop, a contract customer's
licensed area) is a transfer: it is left out of the duty lines and listed with its movement
register status. The register holds what Customs' policy asks for (when it moved, who carried
it, the receipt), and a transfer missing its register row is called out on the entry.
"""

from datetime import date, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest

from app.features.compliant.models.cca_transfers import CcaDeparture, CcaDestination
from app.features.compliant.modules.nz_alcohol import cca_transfers, excise
from app.features.crm.models.xero_contact import XeroContact
from tests.test_compliant_routes import _admin_client, flask_app  # noqa: F401 -- fixture re-export
from tests.test_excise import world  # noqa: F401 -- fixture re-export

PERIOD = date(2026, 8, 1)


@pytest.fixture
def shop(world):  # noqa: F811
    """A duty free shop's CCA, linked to its customer record, plus an ordinary customer."""
    db, org = world["db"], world["org"]
    duty_free = XeroContact(org_id=org.id, xero_contact_id=f"c-{uuid4()}", name="Airport Duty Free Ltd")
    bottle_store = XeroContact(org_id=org.id, xero_contact_id=f"c-{uuid4()}", name="Corner Bottle Store")
    db.add_all([duty_free, bottle_store])
    db.commit()
    resp = world["client"].post(
        "/api/compliant/nz-alcohol/cca-destinations",
        json={
            "name": "Auckland Airport duty free store",
            "cca_code": "DF-AKL-01",
            "address": "Ray Emery Drive, Auckland Airport",
            "kind": "duty_free",
            "contact_id": str(duty_free.id),
        },
    )
    assert resp.status_code == 201, resp.get_json()

    def sell_to(contact, item, qty, day):
        inv = world["sell"](item, qty, day)
        inv.contact_id = contact.id
        db.commit()
        return inv

    yield {**world, "duty_free": duty_free, "bottle_store": bottle_store, "dest": resp.get_json(), "sell_to": sell_to}
    db.rollback()
    for model in (CcaDeparture, CcaDestination):
        db.query(model).filter(model.org_id == org.id).delete(synchronize_session=False)
    db.commit()
    db.query(XeroContact).filter(XeroContact.org_id == org.id).delete(synchronize_session=False)
    db.commit()


def _draft(w):
    return excise.draft(w["db"], w["org"].id, PERIOD, "monthly", today=date(2026, 10, 1))


def test_a_sale_to_a_linked_cca_is_left_out_of_duty_and_listed_as_a_transfer(shop):
    lot = shop["lot"]("B1", 60)
    shop["sell_to"](shop["bottle_store"], lot, "6", date(2026, 8, 5))
    shop["sell_to"](shop["duty_free"], lot, "24", date(2026, 8, 12))

    d = _draft(shop)
    # Only the bottle store's 6 bottles are entered for duty: 6 x 0.7 L x 44% = 1.848 LAL.
    assert Decimal(d["total_lal"]) == Decimal("1.848")
    (moved,) = d["cca_transfers"]
    assert moved["destination"]["cca_code"] == "DF-AKL-01"
    assert moved["quantity"] == "24" and moved["customer"] == "Airport Duty Free Ltd"
    assert Decimal(moved["lal"]) == Decimal("7.392")  # 24 x 0.7 x 44%, kept for the register, not taxed
    assert moved["status"] == "needs_details"
    # With no register row yet, the entry says so rather than staying quiet.
    (problem,) = [p for p in d["problems"] if p.get("link") == "transfers"]
    assert problem["removals"] == 1


def test_recording_the_movement_and_the_receipt_completes_the_register(shop):
    lot = shop["lot"]("B1", 60)
    inv = shop["sell_to"](shop["duty_free"], lot, "24", date(2026, 8, 12))
    client = shop["client"]

    resp = client.post(
        "/api/compliant/nz-alcohol/cca-transfers",
        json={
            "xero_invoice_id": inv.xero_invoice_id,
            "destination_id": shop["dest"]["id"],
            "moved_at": "2026-08-13T09:30",
            "carrier": "Mainfreight",
            "consignment_note": "MF-88231",
        },
    )
    assert resp.status_code == 201, resp.get_json()
    departure = resp.get_json()
    assert departure["moved_at"].startswith("2026-08-13T09:30:00+12:00")  # entered in NZ time
    assert not [p for p in _draft(shop)["problems"] if p.get("link") == "transfers"]

    reg = client.get("/api/compliant/nz-alcohol/cca-transfers?since=2026-08-01").get_json()
    (row,) = reg["transfers"]
    assert row["status"] in ("awaiting_receipt", "receipt_overdue")
    assert row["goods"] == [{"product": "Gin - final product", "unit": "bottles", "quantity": "24"}]

    bad = client.put(
        f"/api/compliant/nz-alcohol/cca-transfers/{departure['id']}/receipt",
        json={"received_on": "2026-08-12", "receipt_reference": "Signed delivery docket"},
    )
    assert bad.status_code == 400 and "before they left" in bad.get_json()["error"]
    ok = client.put(
        f"/api/compliant/nz-alcohol/cca-transfers/{departure['id']}/receipt",
        json={"received_on": "2026-08-14", "receipt_reference": "Signed delivery docket DF-4471"},
    )
    assert ok.status_code == 200, ok.get_json()
    (row,) = client.get("/api/compliant/nz-alcohol/cca-transfers?since=2026-08-01").get_json()["transfers"]
    assert row["status"] == "received" and row["departure"]["receipt_reference"] == "Signed delivery docket DF-4471"


def test_a_receipt_needs_its_evidence(shop):
    lot = shop["lot"]("B1", 60)
    inv = shop["sell_to"](shop["duty_free"], lot, "24", date(2026, 8, 12))
    row = cca_transfers.record_departure(
        shop["db"],
        shop["org"].id,
        {
            "xero_invoice_id": inv.xero_invoice_id,
            "destination_id": shop["dest"]["id"],
            "moved_at": "2026-08-13T09:30",
            "carrier": "Own van",
        },
        None,
    )
    shop["db"].commit()
    resp = shop["client"].put(
        f"/api/compliant/nz-alcohol/cca-transfers/{row.id}/receipt", json={"received_on": "2026-08-14"}
    )
    assert resp.status_code == 400 and "receipt" in resp.get_json()["error"]


def test_any_sale_can_be_marked_as_a_transfer_by_hand_and_unmarked(shop):
    lot = shop["lot"]("B1", 60)
    inv = shop["sell_to"](shop["bottle_store"], lot, "12", date(2026, 8, 5))
    client = shop["client"]
    found = client.get("/api/compliant/nz-alcohol/cca-transfers/sales?q=Corner").get_json()["sales"]
    assert [s["xero_invoice_id"] for s in found] == [inv.xero_invoice_id]

    resp = client.post(
        "/api/compliant/nz-alcohol/cca-transfers",
        json={
            "xero_invoice_id": inv.xero_invoice_id,
            "destination_id": shop["dest"]["id"],
            "moved_at": "2026-08-05T15:00",
            "carrier": "Own van",
        },
    )
    assert resp.status_code == 201
    assert Decimal(_draft(shop)["total_lal"]) == 0
    assert client.get("/api/compliant/nz-alcohol/cca-transfers/sales?q=Corner").get_json()["sales"] == []

    assert client.delete(f"/api/compliant/nz-alcohol/cca-transfers/{resp.get_json()['id']}").status_code == 204
    assert Decimal(_draft(shop)["total_lal"]) == Decimal("3.696")  # back to a duty removal: 12 x 0.7 x 44%


def test_a_transfer_recorded_after_lodging_is_not_carried_as_a_late_removal(shop):
    lot = shop["lot"]("B1", 60)
    excise.lodge(shop["db"], shop["org"].id, PERIOD, "monthly", date(2026, 9, 10), "E1", None, today=date(2026, 10, 1))
    shop["db"].commit()
    shop["sell_to"](shop["duty_free"], lot, "24", date(2026, 8, 20))  # a late invoice into a lodged month
    later = excise.draft(shop["db"], shop["org"].id, date(2026, 9, 1), "monthly", today=date(2026, 10, 1))
    assert later["adjustments"] == []


def test_destinations_are_validated_and_one_customer_maps_to_one_cca(shop):
    client = shop["client"]
    base = {"name": "Other", "address": "1 Road", "kind": "duty_free"}
    assert client.post("/api/compliant/nz-alcohol/cca-destinations", json={**base, "cca_code": ""}).status_code == 400
    assert (
        client.post("/api/compliant/nz-alcohol/cca-destinations", json={**base, "cca_code": "X", "kind": "pub"})
    ).status_code == 400
    dup = client.post("/api/compliant/nz-alcohol/cca-destinations", json={**base, "cca_code": "DF-AKL-01"})
    assert dup.status_code == 400 and "already recorded" in dup.get_json()["error"]
    taken = client.post(
        "/api/compliant/nz-alcohol/cca-destinations",
        json={**base, "cca_code": "DF-WLG", "contact_id": str(shop["duty_free"].id)},
    )
    assert taken.status_code == 400 and "already linked" in taken.get_json()["error"]


def test_another_orgs_sale_and_destination_cannot_be_used(shop, db, flask_app):  # noqa: F811
    other_org, other = _admin_client(db, flask_app)
    try:
        lot = shop["lot"]("B1", 60)
        inv = shop["sell_to"](shop["duty_free"], lot, "24", date(2026, 8, 12))
        resp = other.post(
            "/api/compliant/nz-alcohol/cca-transfers",
            json={
                "xero_invoice_id": inv.xero_invoice_id,
                "destination_id": shop["dest"]["id"],
                "moved_at": "2026-08-13T09:30",
                "carrier": "x",
            },
        )
        assert resp.status_code == 400
        assert other.get("/api/compliant/nz-alcohol/cca-transfers").get_json()["transfers"] == []
        assert other.get("/api/compliant/nz-alcohol/cca-destinations").get_json()["destinations"] == []
    finally:
        from tests.dag_traversal_helpers import clear_org_synthetic_data

        clear_org_synthetic_data(db, other_org.id)


def test_a_receipt_still_missing_after_two_weeks_is_overdue(shop):
    lot = shop["lot"]("B1", 60)
    inv = shop["sell_to"](shop["duty_free"], lot, "24", date(2026, 8, 12))
    cca_transfers.record_departure(
        shop["db"],
        shop["org"].id,
        {
            "xero_invoice_id": inv.xero_invoice_id,
            "destination_id": shop["dest"]["id"],
            "moved_at": "2026-08-13T09:30",
            "carrier": "Own van",
        },
        None,
    )
    shop["db"].commit()
    early = cca_transfers.register(shop["db"], shop["org"].id, since=PERIOD, today=date(2026, 8, 20))
    late = cca_transfers.register(
        shop["db"], shop["org"].id, since=PERIOD, today=date(2026, 8, 13) + timedelta(days=15)
    )
    assert early["transfers"][0]["status"] == "awaiting_receipt"
    assert late["transfers"][0]["status"] == "receipt_overdue"
