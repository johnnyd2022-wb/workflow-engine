"""What the Sites page says is at each place (GL-P07 A2).

Each site's card carries its stock lines, batches under way, stock areas, and whatever the
installed compliance module wants said about it. Core asks through
``platform/site_notes.py`` and never names the module.
"""

from datetime import date
from uuid import UUID, uuid4

from app.core.db.models.execution import ExecutionStatus
from app.core.db.models.stock_location import StockLocation
from app.core.security.tenant_scope import unscoped
from app.features.compliant.modules.nz_alcohol import premises
from app.features.compliant.modules.nz_alcohol.site_notes import NZAlcoholSiteNotes
from app.features.compliant.platform.site_notes import site_notes
from tests.factories import ExecutionFactory, InventoryItemFactory, ProcessFactory
from tests.test_customs_premises import coverage_data, licence_data
from tests.test_customs_premises import world as premises_world  # noqa: F401 -- shared fixture
from tests.test_sites import _add, _enable, flask_app, world  # noqa: F401 -- shared fixtures

ON = date(2026, 9, 29)


def _card(client, site_id):
    sites = client.get("/api/core/sites").get_json()["sites"]
    return next(site for site in sites if site["id"] == site_id)


def test_each_site_card_counts_what_is_there(world, db):  # noqa: F811
    org, admin, _, neighbour = world
    default = _enable(admin)
    bond = _add(admin)
    area = admin.post("/api/core/stock-locations", json={"name": "Tank bay", "site_id": bond["id"]})
    assert area.status_code == 201, area.get_json()
    with unscoped():
        bond_id = UUID(bond["id"])
        InventoryItemFactory(org_id=org.id, name="Gin", quantity="10", unit="L", site_id=bond_id)
        InventoryItemFactory(org_id=org.id, name="Empty drum", quantity="0", unit="L", site_id=bond_id)
        process = ProcessFactory(org_id=org.id)
        for status in (ExecutionStatus.IN_PROGRESS, ExecutionStatus.COMPLETED):
            ExecutionFactory(org_id=org.id, process_id=process.id, site_id=bond_id).status = status
        db.commit()

    card = _card(admin, bond["id"])
    assert card["stock_lines"] == 1  # the empty drum is not stock
    assert card["batches_under_way"] == 1  # the finished batch is not under way
    assert [a["name"] for a in card["areas"]] == ["Tank bay"]
    assert card["notes"] == []  # no compliance module, nothing to say
    assert admin.get("/api/core/sites").get_json()["compliance"] is None
    home = _card(admin, default["id"])
    assert (home["stock_lines"], home["batches_under_way"], home["areas"]) == (0, 0, [])
    # Another organisation never sees these sites.
    _enable(neighbour)
    assert bond["id"] not in {s["id"] for s in neighbour.get("/api/core/sites").get_json()["sites"]}


def test_no_cards_while_multiple_sites_are_off(world):  # noqa: F811
    _, admin, _, _ = world
    overview = admin.get("/api/core/sites").get_json()
    assert overview["sites"] == [] and overview["compliance"] is None


def test_nz_alcohol_says_which_sites_and_areas_are_licensed(db, premises_world):  # noqa: F811
    orgs, sites, extra, shop = premises_world
    still = StockLocation(id=uuid4(), org_id=orgs[0].id, site_id=sites[0].id, name="Still house")
    db.add(still)
    db.flush()
    areas = [shop, still]
    licence = premises.add_licence(db, orgs[0].id, licence_data())
    premises.add_coverage(db, orgs[0].id, coverage_data(licence, extra))

    notes = NZAlcoholSiteNotes().notes(db, orgs[0].id, [sites[0], extra], areas, ON)
    licensed = notes["sites"][str(extra.id)][0]
    assert licensed["tone"] == "ok" and "CCA-123" in licensed["text"] and licensed["short"] == "Licensed"
    assert licensed["href"] == "/compliant/nz-alcohol/premises"
    unlicensed = notes["sites"][str(sites[0].id)][0]
    assert unlicensed["tone"] == "neutral" and unlicensed["short"] == "Duty-paid"
    assert notes["areas"][str(shop.id)]["text"] == "Duty-paid"
    assert notes["label"] == "Customs"
    assert notes["step"]["done"] is True and notes["step"]["detail"].startswith("Bond store is in")

    # Licensing one of the main site's two areas makes it partly licensed.
    second = premises.add_licence(db, orgs[0].id, licence_data(number="CCA-456", kind="oss"))
    premises.add_coverage(db, orgs[0].id, coverage_data(second, sites[0], location_id=str(still.id)))
    notes = NZAlcoholSiteNotes().notes(db, orgs[0].id, [sites[0], extra], areas, ON)
    partial = notes["sites"][str(sites[0].id)][0]
    assert partial["text"] == "Customs-licensed: 1 of its 2 areas" and partial["short"] == "1 of 2 areas licensed"
    assert "CCA-456" in notes["areas"][str(still.id)]["text"]
    assert notes["areas"][str(shop.id)]["text"] == "Duty-paid"

    # Licensing the other area too reads as a licensed site, naming the licence.
    premises.add_coverage(db, orgs[0].id, coverage_data(second, sites[0], location_id=str(shop.id)))
    notes = NZAlcoholSiteNotes().notes(db, orgs[0].id, [sites[0]], areas, ON)
    whole = notes["sites"][str(sites[0].id)][0]
    assert whole["short"] == "Licensed" and "CCA-456" in whole["text"]


def test_before_a_licence_starts_nothing_is_licensed(db, premises_world):  # noqa: F811
    orgs, _, extra, _ = premises_world
    licence = premises.add_licence(db, orgs[0].id, licence_data())
    premises.add_coverage(db, orgs[0].id, coverage_data(licence, extra))
    early = NZAlcoholSiteNotes().notes(db, orgs[0].id, [extra], [], date(2025, 12, 31))
    assert early["sites"][str(extra.id)][0]["tone"] == "neutral"
    assert early["step"]["done"] is False


def test_without_a_compliance_profile_core_gets_no_notes(db, premises_world):  # noqa: F811
    orgs, sites, extra, shop = premises_world
    licence = premises.add_licence(db, orgs[0].id, licence_data())
    premises.add_coverage(db, orgs[0].id, coverage_data(licence, extra))
    assert site_notes(db, orgs[0].id, [sites[0], extra], [shop]) == {
        "sites": {},
        "areas": {},
        "label": None,
        "step": None,
    }


def test_a_site_wide_licence_covers_the_main_area_not_a_named_one(db, premises_world):  # noqa: F811
    # premises.licence_for_area: a named area needs a record of its own.
    orgs, sites, _, _ = premises_world
    main = sites[0]
    bay = StockLocation(id=uuid4(), org_id=orgs[0].id, site_id=main.id, name="Bay 9")
    db.add(bay)
    db.flush()
    licence = premises.add_licence(db, orgs[0].id, licence_data())
    premises.add_coverage(db, orgs[0].id, coverage_data(licence, main))
    notes = NZAlcoholSiteNotes().notes(db, orgs[0].id, [main], [bay], ON)
    assert notes["areas"][str(bay.id)]["text"] == "Duty-paid"
    assert premises.licence_for_area(db, orgs[0].id, main.id, bay.id, ON) is None
    site = notes["sites"][str(main.id)][0]
    assert site["text"] == "Customs-licensed main area (Manufacturing area CCA-123); 0 of its 1 areas"
    assert site["short"] == "Main area, 0 of 1 areas"
