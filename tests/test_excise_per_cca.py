"""An excise entry per CCA licence once a business works at several sites (GL-P07 A5).

Each removal belongs to the licence that covered the stock's place on the day it left, from
the Customs register (premises.licence_for_area); stock outside any licence was duty-paid
already. Each licence is lodged, reminded and listed on its own.
"""

from datetime import date
from uuid import uuid4

import pytest

from app.core.db.models.site import Site
from app.core.db.models.stock_location import StockLocation
from app.features.compliant.models.customs_premises import CustomsCoverage, CustomsLicence
from app.features.compliant.models.excise import ExciseLodgement
from app.features.compliant.modules.nz_alcohol import excise, premises
from app.features.compliant.service import ComplianceService
from tests.factories import grant_multi_site
from tests.test_compliant_routes import flask_app  # noqa: F401 -- shared fixture
from tests.test_customs_premises import coverage_data, licence_data
from tests.test_excise import GIN, world  # noqa: F401 -- shared fixture

AUG = date(2026, 8, 1)
TODAY = date(2026, 9, 5)


@pytest.fixture
def two_ccas(world):  # noqa: F811
    """A distillery under one licence (with a duty-paid shop) and a bond store under another."""
    db, org, client = world["db"], world["org"], world["client"]
    grant_multi_site(db, org.id)
    assert client.put("/api/core/sites/settings", json={"enabled": True}).status_code == 200
    main = db.query(Site).filter(Site.org_id == org.id, Site.is_default.is_(True)).one()
    bond = Site(id=uuid4(), org_id=org.id, name="Bond store", kind="storage", is_active=True)
    db.add(bond)
    db.flush()
    shop = StockLocation(id=uuid4(), org_id=org.id, site_id=main.id, name="Cellar door shop")
    db.add(shop)
    db.flush()
    lma = premises.add_licence(db, org.id, licence_data(number="CCA-1"))
    oss = premises.add_licence(db, org.id, licence_data(number="CCA-2", kind="oss"))
    premises.add_coverage(db, org.id, coverage_data(lma, main))
    premises.add_coverage(db, org.id, coverage_data(oss, bond))
    db.commit()

    def lot(batch, qty, site, location=None):
        return world["repo"].create_inventory_item(
            org_id=org.id,
            name=GIN,
            quantity=str(qty),
            unit="bottles",
            inventory_type="final_product",
            supplier_batch_number=batch,
            extra_data={"abv_percent": "44"},
            site_id=site.id,
            location_id=location.id if location else None,
        )

    at_main, at_bond, in_shop = lot("MAIN", 100, main), lot("BOND", 50, bond), lot("SHOP", 20, main, shop)
    db.commit()
    world["sell"](at_main, "10", date(2026, 8, 10), "INV-MAIN")
    world["sell"](at_bond, "5", date(2026, 8, 11), "INV-BOND")
    world["sell"](in_shop, "3", date(2026, 8, 12), "INV-SHOP")
    yield {**world, "lma": lma, "oss": oss}
    db.rollback()
    from sqlalchemy import text

    from app.core.db.models.inventory_movement import InventoryMovement
    from app.core.db.models.site_transfer import SiteStockReceipt, SiteStockTransfer

    # Test-only evidence purge, as tests/test_site_transfers.py does: receipt proof is immutable.
    db.execute(text("SELECT set_config('app.migration_mode','1',true)"))
    db.query(InventoryMovement).filter(InventoryMovement.org_id == org.id).delete(synchronize_session=False)
    db.execute(text("UPDATE inventory_items SET transfer_receipt_id = NULL WHERE org_id = :org"), {"org": org.id})
    for model in (SiteStockReceipt, SiteStockTransfer):
        db.query(model).filter(model.org_id == org.id).delete(synchronize_session=False)
    db.query(ExciseLodgement).filter(ExciseLodgement.org_id == org.id).delete(synchronize_session=False)
    for model in (CustomsCoverage, CustomsLicence):
        db.query(model).filter(model.org_id == org.id).delete(synchronize_session=False)
    db.commit()


def _references(d):
    return sorted(r["reference"] for line in d["lines"] for r in line["removals"])


def test_each_licence_has_its_own_entry_and_duty_paid_stock_is_in_neither(two_ccas):
    db, org, lma, oss = two_ccas["db"], two_ccas["org"], two_ccas["lma"], two_ccas["oss"]
    first = excise.draft(db, org.id, AUG, "monthly", today=TODAY)
    assert first["per_cca"] is True
    assert [c["number"] for c in first["ccas"]] == ["CCA-1", "CCA-2"]
    assert first["cca"]["id"] == str(lma.id)  # the first by number unless one is asked for
    assert _references(first) == ["INV-MAIN"]
    bond = excise.draft(db, org.id, AUG, "monthly", today=TODAY, licence_id=oss.id)
    assert _references(bond) == ["INV-BOND"]
    # The cellar door shop has no licence of its own: its sale was duty-paid stock.
    assert "INV-SHOP" not in _references(first) + _references(bond)
    assert first["entry"]["complete"] is True and first["total_lal"] == "3.08"  # 10 x 0.7 L x 44%


def test_a_licence_from_another_business_or_period_is_refused(two_ccas):
    db, org = two_ccas["db"], two_ccas["org"]
    with pytest.raises(ValueError, match="in force in this period"):
        excise.draft(db, org.id, AUG, "monthly", today=TODAY, licence_id=uuid4())


def test_each_licence_is_lodged_on_its_own(two_ccas):
    db, org, lma, oss = two_ccas["db"], two_ccas["org"], two_ccas["lma"], two_ccas["oss"]
    with pytest.raises(ValueError, match="choose the licence"):
        excise.lodge(db, org.id, AUG, "monthly", date(2026, 9, 5), None, None, today=TODAY)
    record = excise.lodge(db, org.id, AUG, "monthly", date(2026, 9, 5), "E-1", None, today=TODAY, licence_id=lma.id)
    db.commit()
    assert record.licence_id == lma.id and record.snapshot["cca"]["number"] == "CCA-1"
    assert excise.draft(db, org.id, AUG, "monthly", today=TODAY, licence_id=lma.id)["status"] == "lodged"
    bond = excise.draft(db, org.id, AUG, "monthly", today=TODAY, licence_id=oss.id)
    assert bond["status"] == "draft"
    assert [c["lodged"] for c in bond["ccas"]] == [True, False]
    with pytest.raises(ValueError, match="already recorded"):
        excise.lodge(db, org.id, AUG, "monthly", date(2026, 9, 5), None, None, today=TODAY, licence_id=lma.id)
    excise.lodge(db, org.id, AUG, "monthly", date(2026, 9, 6), "E-2", None, today=TODAY, licence_id=oss.id)
    db.commit()
    assert db.query(ExciseLodgement).filter_by(org_id=org.id, period_start=AUG).count() == 2


def test_a_late_sale_is_carried_by_its_own_licence_only(two_ccas):
    db, org, lma, oss = two_ccas["db"], two_ccas["org"], two_ccas["lma"], two_ccas["oss"]
    for licence in (lma, oss):
        excise.lodge(db, org.id, AUG, "monthly", date(2026, 9, 5), None, None, today=TODAY, licence_id=licence.id)
    db.commit()
    bond_lot = next(i for i in two_ccas["repo"].list_inventory_items(org.id) if i.supplier_batch_number == "BOND")
    two_ccas["sell"](bond_lot, "1", date(2026, 8, 30), "INV-LATE")
    sept_bond = excise.draft(db, org.id, date(2026, 9, 1), "monthly", today=date(2026, 10, 5), licence_id=oss.id)
    sept_main = excise.draft(db, org.id, date(2026, 9, 1), "monthly", today=date(2026, 10, 5), licence_id=lma.id)
    assert [a["reference"] for a in sept_bond["adjustments"]] == ["INV-LATE"]
    assert sept_main["adjustments"] == []


def test_the_reminder_and_api_name_the_licence(two_ccas):
    db, org, client, lma, oss = (two_ccas[k] for k in ("db", "org", "client", "lma", "oss"))
    profile = ComplianceService(db).get_profile(org.id)
    profile.settings = {**profile.settings, "excise_tracking_from": "2026-08-01"}
    db.commit()
    alert = excise.reminder(db, org.id, profile, today=TODAY)
    assert "(CCA-1)" in alert["title"] and "1 other CCA entry is also due" in alert["description"]
    assert alert["href"].endswith(f"&cca={lma.id}")

    got = client.get(f"/api/compliant/nz-alcohol/excise?period=2026-08-01&cca={oss.id}").get_json()["draft"]
    assert got["cca"]["number"] == "CCA-2" and _references(got) == ["INV-BOND"]
    assert client.get("/api/compliant/nz-alcohol/excise?period=2026-08-01&cca=nope").status_code == 400
    # Lodging needs the licence; the API records it.
    refused = client.post("/api/compliant/nz-alcohol/excise/lodge", json={"period_start": "2026-08-01"})
    assert refused.status_code == 400
    made = client.post(
        "/api/compliant/nz-alcohol/excise/lodge",
        json={"period_start": "2026-08-01", "lodged_on": "2026-09-05", "cca": str(oss.id)},
    )
    assert made.status_code == 201, made.get_json()
    assert made.get_json()["draft"]["status"] == "lodged" and made.get_json()["draft"]["cca"]["number"] == "CCA-2"
    periods = client.get(f"/api/compliant/nz-alcohol/excise/periods?cca={oss.id}").get_json()["periods"]
    assert next(p for p in periods if p["period_start"] == "2026-08-01")["status"] == "lodged"
    periods = client.get(f"/api/compliant/nz-alcohol/excise/periods?cca={lma.id}").get_json()["periods"]
    assert next(p for p in periods if p["period_start"] == "2026-08-01")["status"] == "not lodged"
    # The reminder moves on to the licence still to lodge.
    alert = excise.reminder(db, org.id, profile, today=TODAY)
    assert "(CCA-1)" in alert["title"] and "also due" not in alert["description"]


def test_without_licences_nothing_can_be_lodged_or_called_nil(world):  # noqa: F811
    db, org, client = world["db"], world["org"], world["client"]
    grant_multi_site(db, org.id)
    assert client.put("/api/core/sites/settings", json={"enabled": True}).status_code == 200
    d = excise.draft(db, org.id, AUG, "monthly", today=TODAY)
    assert d["entry"] is None and d["nil_return"] is None and d["ccas"] == []
    assert d["problems"][0]["product"] == "CCA licences"
    profile = ComplianceService(db).get_profile(org.id)
    profile.settings = {**profile.settings, "excise_tracking_from": "2026-08-01"}
    db.commit()
    alert = excise.reminder(db, org.id, profile, today=TODAY)
    assert alert["href"] == "/compliant/nz-alcohol/premises" and "nil" not in alert["title"].lower()


def test_a_single_site_business_is_unchanged(world):  # noqa: F811
    db, org = world["db"], world["org"]
    vat = world["lot"]("VAT", 10)
    world["sell"](vat, "2", date(2026, 8, 3), "INV-ONE")
    d = excise.draft(db, org.id, AUG, "monthly", today=TODAY)
    assert d["per_cca"] is False and d["cca"] is None and _references(d) == ["INV-ONE"]
    record = excise.lodge(db, org.id, AUG, "monthly", TODAY, None, None, today=TODAY)
    assert record.licence_id is None


def test_a_removal_for_home_consumption_between_sites_is_in_its_source_entry(two_ccas):
    """Dispatched from the bond store to the duty-paid cellar door shop for home consumption:
    a removal from the bond's licence on the dispatch date, through the real NZ policy."""
    from app.core.db.models.user import User
    from app.features.compliant.platform.stock_movements import evaluate_stock_movement, prepare_stock_movement
    from app.features.site_transfers import service

    db, org, oss = two_ccas["db"], two_ccas["org"], two_ccas["oss"]
    shop = (
        db.query(StockLocation).filter(StockLocation.org_id == org.id, StockLocation.name == "Cellar door shop").one()
    )
    bond_lot = next(i for i in two_ccas["repo"].list_inventory_items(org.id) if i.supplier_batch_number == "BOND")
    actor = db.query(User).filter(User.org_id == org.id).first()
    transfer, _ = service.dispatch(
        db,
        org.id,
        actor.id,
        str(uuid4()),
        {
            "source_item_id": str(bond_lot.id),
            "destination_site_id": str(shop.site_id),
            "destination_location_id": str(shop.id),
            "quantity": "6",
            "carrier": "Own van",
            "consignment_reference": "MV-HOME",
            "occurred_on": "2026-08-20",
            "approval": {
                "destination_activity": "selling",
                "authority": "home_consumption",
                "evidence_reference": "Excise removal review",
                "measured_abv_percent": "44",
                "measurement_method": "hydrometric",
                "measured_on": "2026-08-20",
                "measurement_reference": "Hydrometer certificate",
                "volume_reference": "700 mL bottle record",
            },
        },
        evaluate_stock_movement,
        prepare_stock_movement,
    )
    db.commit()
    bond = excise.draft(db, org.id, AUG, "monthly", today=TODAY, licence_id=oss.id)
    assert _references(bond) == ["Dispatched to Main site (MV-HOME)", "INV-BOND"]
    moved = next(r for line in bond["lines"] for r in line["removals"] if r["reference"].startswith("Dispatched"))
    assert moved["kind"] == "moved_out" and moved["quantity"] == "6" and moved["date"] == "2026-08-20"
    main = excise.draft(db, org.id, AUG, "monthly", today=TODAY, licence_id=two_ccas["lma"].id)
    assert _references(main) == ["INV-MAIN"]  # not the destination's removal
    assert transfer.decision_snapshot["tax_status"] == "home_consumption_excise_due"


def test_licensed_status_comes_from_the_register_not_the_area_flag(two_ccas):
    """With several sites the Customs register decides what is inside the licensed area: the
    cellar door shop has no record of its own, so it is outside even if its flag says inside."""
    db, org, client = two_ccas["db"], two_ccas["org"], two_ccas["client"]
    shop = (
        db.query(StockLocation).filter(StockLocation.org_id == org.id, StockLocation.name == "Cellar door shop").one()
    )
    shop.inside_licensed_area = True  # a stale flag
    db.commit()
    main = next(s for s in client.get("/api/core/sites/choices").get_json()["sites"] if s["is_default"])
    assert main["main_area_licensed"] is True
    assert {a["name"]: a["inside_licensed_area"] for a in main["areas"]} == {"Cellar door shop": False}
    # Moving from the licensed main floor into the shop crosses the boundary: refused as one step.
    main_lot = next(i for i in two_ccas["repo"].list_inventory_items(org.id) if i.supplier_batch_number == "MAIN")
    with pytest.raises(ValueError, match="licensed area"):
        two_ccas["repo"].move_lot(org.id, main_lot.id, "1", shop.id, date(2026, 9, 1))
