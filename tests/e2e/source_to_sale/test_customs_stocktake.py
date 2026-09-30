"""A phone count explains a shortfall and changes the excise draft once."""

from datetime import date
from decimal import Decimal

import pytest
from playwright.sync_api import expect

from app.core.db.models.inventory_item import InventoryItem
from app.core.db.models.stock_location import StockLocation
from app.features.compliant.modules.nz_alcohol import excise
from tests.e2e.conftest import csrf_headers
from tests.e2e.source_to_sale.conftest import BATCH, PRODUCT

pytestmark = pytest.mark.e2e


def test_customs_visit_count_split_and_reconciliation_on_phone(alcohol_scenario):
    world = alcohol_scenario
    page, db, org_id = world["page"], world["db"], world["org_id"]
    car = StockLocation(org_id=org_id, name="Rep car", inside_licensed_area=False)
    db.add(car)
    db.commit()
    page.set_viewport_size({"width": 390, "height": 844})
    page.goto("/core/stocktake")
    page.get_by_role("button", name="Customs is here").click()
    line = page.locator(".st-line", has_text=BATCH)
    expect(line).to_be_visible()
    line.get_by_role("spinbutton", name=f"Counted {PRODUCT} {BATCH}").fill("43")
    line.get_by_role("button", name="Save", exact=True).click()
    expect(line).to_contain_text("Difference to resolve")
    expect(page.get_by_role("button", name="Finish stocktake")).to_be_hidden()
    line.get_by_role("combobox", name="Reason").select_option("found_elsewhere")
    line.get_by_role("spinbutton", name="Quantity").fill("4")
    line.get_by_role("combobox", name="Place").select_option(str(car.id))
    line.get_by_role("button", name="Split across another reason").click()
    line.get_by_role("combobox", name="Reason").nth(1).select_option("broken")
    line.get_by_role("spinbutton", name="Quantity").nth(1).fill("3")
    line.get_by_role("textbox", name="Note").nth(1).fill("Dropped three bottles during count")
    line.get_by_role("button", name="Resolve", exact=True).click()
    expect(line).to_contain_text("Resolved")
    expect(line).to_contain_text("Rep car")
    expect(line).to_contain_text("claim remission")
    page.get_by_role("button", name="Finish stocktake").click()
    expect(page.locator("[data-st-count-summary]")).to_contain_text("Finished")

    listing = page.request.get("/api/core/stocktakes").json()
    counted = listing["stocktakes"][0]
    reconciliation = page.request.get(f"/api/core/stocktakes/{counted['id']}/reconciliation")
    assert reconciliation.status == 200
    (product,) = reconciliation.json()["products"]
    assert product["variance"] == "-7" and product["explained"] == "-7"
    snapshot = page.request.get(f"/api/core/stocktakes/{counted['id']}").json()
    finished_line = next(row for row in snapshot["lines"] if row["batch"] == BATCH)
    repeated = page.request.post(
        f"/api/core/stocktakes/{counted['id']}/lines/{finished_line['id']}/resolve",
        data={"reasons": [{"reason": "broken", "quantity": "7"}]},
        headers=csrf_headers(page),
    )
    assert repeated.status == 400

    db.expire_all()
    assert db.get(InventoryItem, world["final"].id).quantity == Decimal("43")
    moved = db.query(InventoryItem).filter(InventoryItem.org_id == org_id, InventoryItem.location_id == car.id).one()
    assert moved.quantity == Decimal("4")
    draft = excise.draft(db, org_id, date.today().replace(day=1), "monthly", today=date.today())
    assert draft["total_lal"] == "1.232"  # four x 700mL x 44%; breakage pending remission excluded
    assert draft["total_duty"] == "78.97"
    assert [(r["kind"], r["quantity"]) for r in draft["lines"][0]["removals"]] == [("moved_out", "4")]
    # A completed count remains an audit record, rather than allowing another resolution.
    response = page.request.get("/api/core/stock-position")
    assert response.status == 200
    assert sum(
        Decimal(lot["quantity"])
        for place in response.json()["places"]
        for lot in place["lots"]
        if lot["name"] == PRODUCT
    ) == Decimal("47")
