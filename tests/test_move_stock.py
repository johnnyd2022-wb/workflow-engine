"""What the Move dialog needs from the server (GL-P07 A4).

- site choices say whether each area is inside the licensed area, so a move across that
  boundary at one site is sent as a dispatch and receipt before anyone presses Move;
- a transfer keeps the site names it was sent with, so an archived site still reads right;
- a compliance question can say which answer it belongs to, and is only asked then.
"""

from app.features.compliant.modules.nz_alcohol.stock_movements import NZAlcoholMovementPolicy
from tests.test_site_operations import released  # noqa: F401 -- shared fixture
from tests.test_site_transfers import transfers  # noqa: F401 -- shared fixture
from tests.test_sites import flask_app, world  # noqa: F401 -- shared fixtures


def test_choices_say_which_areas_are_licensed(world):  # noqa: F811
    _, admin, _, _ = world
    admin.put("/api/core/sites/settings", json={"enabled": True})
    admin.post("/api/core/sites", json={"name": "Bond store", "kind": "storage"})
    admin.post("/api/core/stock-locations", json={"name": "Tank bay", "inside_licensed_area": True})
    admin.post("/api/core/stock-locations", json={"name": "Shop"})
    main = admin.get("/api/core/sites/choices").get_json()["sites"][0]
    assert {a["name"]: a["inside_licensed_area"] for a in main["areas"]} == {"Shop": False, "Tank bay": True}


def test_a_transfer_keeps_the_names_it_was_sent_with(transfers):  # noqa: F811
    _, admin, _, _, default, additional, stock_id, _ = transfers
    made = admin.post(
        "/api/core/site-transfers",
        json={
            "source_item_id": str(stock_id),
            "destination_site_id": additional["id"],
            "quantity": "2",
            "carrier": "Own van",
            "consignment_reference": "MV-1",
            "occurred_on": "2026-10-01",
        },
        headers={"Idempotency-Key": "names-1"},
    )
    assert made.status_code == 201, made.get_json()
    admin.patch(f"/api/core/sites/{additional['id']}", json={"name": "Renamed later"})
    row = admin.get("/api/core/site-transfers").get_json()["transfers"][0]
    assert row["source_site_name"] == default["name"]
    assert row["destination_site_name"] == additional["name"]


def test_nz_alcohol_asks_approval_and_strength_questions_only_for_their_authority():
    fields = {f["name"]: f for f in NZAlcoholMovementPolicy().requirements()["fields"]}
    assert "show_when" not in fields["authority"] and "show_when" not in fields["evidence_reference"]
    assert fields["reference"]["show_when"] == {"authority": ["prior_customs_approval"]}
    assert fields["approved_on"]["show_when"] == {"authority": ["prior_customs_approval"]}
    for name in (
        "measured_abv_percent",
        "measurement_method",
        "measured_on",
        "measurement_reference",
        "volume_reference",
    ):
        assert fields[name]["show_when"] == {"authority": ["home_consumption"]}
