"""Plan item 2.1: excise per period from removals out of the licensed area."""

from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest

from app.core.db.models.inventory_item import InventoryType
from app.core.db.models.organisation import Organisation
from app.core.db.models.stock_location import StockLocation, StockTransfer
from app.core.db.repositories.inventory_repo import InventoryRepository
from app.features.compliant.models.alcohol_product_profile import AlcoholProductProfile
from app.features.compliant.models.excise import ExciseLodgement, ExciseRate
from app.features.compliant.modules.nz_alcohol import excise
from app.features.crm.models.sales_fifo_allocation import SalesFifoAllocation
from app.features.crm.models.xero_invoice import XeroInvoice
from tests.dag_traversal_helpers import clear_org_synthetic_data
from tests.test_compliant_routes import _admin_client, flask_app  # noqa: F401 -- fixture re-export

GIN = "Gin - final product"


# --- periods and due dates -----------------------------------------------------------------


@pytest.mark.parametrize(
    ("day", "frequency", "start", "end"),
    [
        (date(2026, 9, 17), "monthly", date(2026, 9, 1), date(2026, 10, 1)),
        (date(2026, 12, 31), "monthly", date(2026, 12, 1), date(2027, 1, 1)),
        (date(2026, 3, 2), "six_monthly", date(2026, 1, 1), date(2026, 7, 1)),
        (date(2026, 9, 2), "six_monthly", date(2026, 7, 1), date(2027, 1, 1)),
        (date(2026, 9, 2), "twelve_monthly", date(2026, 7, 1), date(2027, 7, 1)),
        (date(2026, 3, 2), "twelve_monthly", date(2025, 7, 1), date(2026, 7, 1)),
    ],
)
def test_periods(day, frequency, start, end):
    assert excise.period_for(day, frequency) == (start, end)


def test_entry_is_due_on_the_15th_working_day_after_the_period():
    assert excise.entry_due(date(2026, 10, 1)) == date(2026, 10, 21)  # September 2026 entry
    assert excise.period_label(date(2026, 9, 1), date(2026, 10, 1)) == "September 2026"


# --- the service against a real tenant ------------------------------------------------------


@pytest.fixture
def world(db, flask_app):  # noqa: F811
    org, client = _admin_client(db, flask_app)
    client.put("/api/compliant/profile", json={"enabled": True, "settings": {"alcohol_product_types": ["spirits"]}})
    repo = InventoryRepository(db)

    def lot(batch, qty, abv="44", name=GIN):
        return repo.create_inventory_item(
            org_id=org.id,
            name=name,
            quantity=str(qty),
            unit="bottles",
            inventory_type=InventoryType.FINAL_PRODUCT.value,
            supplier_batch_number=batch,
            extra_data={"abv_percent": abv} if abv else {},
        )

    def sell(item, qty, day, number=None):
        inv = XeroInvoice(
            org_id=org.id,
            xero_invoice_id=f"inv-{uuid4()}",
            xero_tenant_id="t",
            invoice_type="ACCREC",
            status="AUTHORISED",
            invoice_number=number or f"INV-{uuid4().hex[:4]}",
            date=day,
        )
        db.add(inv)
        db.flush()
        db.add(
            SalesFifoAllocation(
                org_id=org.id,
                xero_invoice_id=inv.xero_invoice_id,
                xero_line_key="l1",
                inventory_item_id=item.id,
                product_name=item.name,
                quantity=Decimal(qty),
                unit=item.unit,
            )
        )
        db.commit()
        return inv

    db.add(
        AlcoholProductProfile(
            org_id=org.id,
            inventory_name=GIN,
            product_type="spirits",
            pack_volume_ml=Decimal("700"),
            customs_product_code="2208.50.00",
        )
    )
    db.add(
        ExciseRate(
            org_id=org.id, tariff_item="2208.50.00", rate_per_lal=Decimal("64.10"), effective_from=date(2026, 7, 1)
        )
    )
    db.commit()
    yield {"org": org, "client": client, "lot": lot, "sell": sell, "db": db, "repo": repo}

    db.rollback()
    for model in (ExciseLodgement, ExciseRate, AlcoholProductProfile, SalesFifoAllocation, XeroInvoice, StockTransfer):
        db.query(model).filter(model.org_id == org.id).delete(synchronize_session=False)
    db.commit()
    clear_org_synthetic_data(db, org.id)
    db.query(StockLocation).filter(StockLocation.org_id == org.id).delete(synchronize_session=False)
    db.query(Organisation).filter(Organisation.id == org.id).delete(synchronize_session=False)
    db.commit()


def test_sales_from_the_licensed_area_become_lal_and_duty(world):
    vat44 = world["lot"]("VAT44", 50)
    world["sell"](vat44, "12", date(2026, 9, 10), "INV-0412")
    d = excise.draft(world["db"], world["org"].id, date(2026, 9, 1), "monthly", today=date(2026, 10, 5))
    (line,) = d["lines"]
    # 12 x 0.7 L x 44% = 3.696 LAL; x $64.10 = $236.91
    assert line["units"] == "12" and line["litres"] == "8.4" and line["lal"] == "3.696"
    assert line["duty"] == "236.91" and d["total_duty"] == "236.91"
    assert line["removals"][0]["reference"] == "INV-0412" and line["removals"][0]["batch"] == "VAT44"
    assert d["due"] == "2026-10-21" and d["status"] == "draft" and d["open"] is False


def test_moving_stock_out_is_the_removal_and_its_later_sale_isnt_counted_again(world):
    db, org = world["db"], world["org"]
    vat44 = world["lot"]("VAT44", 50)
    car = StockLocation(org_id=org.id, name="Sam's car", inside_licensed_area=False)
    db.add(car)
    db.commit()
    moved, transfer = world["repo"].move_lot(org.id, vat44.id, "6", car.id, date(2026, 9, 3))
    assert transfer.direction == "out" and moved.supplier_batch_number == "VAT44"
    with pytest.raises(ValueError, match="whole numbers"):
        world["repo"].move_lot(org.id, vat44.id, "1.5", car.id, date(2026, 9, 3))
    world["sell"](moved, "6", date(2026, 9, 12))  # sold from the car: not a second removal
    world["sell"](vat44, "2", date(2026, 9, 12))  # shipped from the licensed area

    d = excise.draft(db, org.id, date(2026, 9, 1), "monthly", today=date(2026, 10, 5))
    kinds = sorted((r["kind"], r["quantity"]) for r in d["lines"][0]["removals"])
    assert kinds == [("moved_out", "6"), ("sale", "2")]
    assert d["lines"][0]["units"] == "8"

    # Bringing some back is listed as a possible credit, never subtracted.
    merged, back = world["repo"].move_lot(org.id, moved.id, "3", None, date(2026, 9, 20))
    assert back.direction == "in" and merged.id == vat44.id  # merged back into the same batch
    d = excise.draft(db, org.id, date(2026, 9, 1), "monthly", today=date(2026, 10, 5))
    assert d["lines"][0]["units"] == "8"
    assert d["returns"] == [{"product": GIN, "quantity": "3", "unit": "bottles", "date": "2026-09-20"}]


def test_missing_setup_is_listed_not_silently_dropped(world):
    db, org = world["db"], world["org"]
    world["sell"](world["lot"]("R1", 10, name="Rum - final product"), "2", date(2026, 9, 5))  # no profile
    world["sell"](world["lot"]("V9", 10, abv=None), "1", date(2026, 9, 5))  # no ABV anywhere
    d = excise.draft(db, org.id, date(2026, 9, 1), "monthly", today=date(2026, 10, 5))
    reasons = {(p["product"], p["reason"]) for p in d["problems"]}
    assert ("Rum - final product", "Not set up as an excise product") in reasons
    assert (GIN, "No ABV recorded for this batch or product") in reasons
    assert d["lines"] == []


def test_lodging_locks_the_period_and_late_changes_carry_forward(world):
    db, org = world["db"], world["org"]
    vat44 = world["lot"]("VAT44", 50)
    world["sell"](vat44, "12", date(2026, 9, 10))
    with pytest.raises(ValueError, match="hasn't finished"):
        excise.lodge(db, org.id, date(2026, 10, 1), "monthly", date(2026, 10, 2), None, None, today=date(2026, 10, 2))
    record = excise.lodge(
        db, org.id, date(2026, 9, 1), "monthly", date(2026, 10, 15), "E123", None, today=date(2026, 10, 15)
    )
    db.commit()
    assert record.nil_return is False and record.snapshot["total_lal"] == "3.696"
    with pytest.raises(ValueError, match="already recorded"):
        excise.lodge(db, org.id, date(2026, 9, 1), "monthly", date(2026, 10, 16), None, None, today=date(2026, 10, 16))

    # A September invoice entered after September was lodged.
    world["sell"](vat44, "2", date(2026, 9, 28), "INV-LATE")
    sept = excise.draft(db, org.id, date(2026, 9, 1), "monthly", today=date(2026, 11, 5))
    assert sept["status"] == "lodged" and sept["total_lal"] == "3.696"  # unchanged
    octo = excise.draft(db, org.id, date(2026, 10, 1), "monthly", today=date(2026, 11, 5))
    (adj,) = octo["adjustments"]
    assert adj["reference"] == "INV-LATE" and adj["belongs_to"] == "2026-09-01" and adj["lal"] == "0.616"

    # Once October is lodged (carrying it), November doesn't carry it again.
    excise.lodge(db, org.id, date(2026, 10, 1), "monthly", date(2026, 11, 10), None, None, today=date(2026, 11, 10))
    db.commit()
    nov = excise.draft(db, org.id, date(2026, 11, 1), "monthly", today=date(2026, 12, 5))
    assert nov["adjustments"] == []


def test_nil_return_and_reminder(world):
    """August 2026 (already finished by the real clock, which the lodge API uses)."""
    db, org, client = world["db"], world["org"], world["client"]
    from app.features.compliant.service import ComplianceService

    profile = ComplianceService(db).get_profile(org.id)
    assert excise.reminder(db, org.id, profile, today=date(2026, 9, 5)) is None  # tracking not switched on

    ok = client.put(
        "/api/compliant/nz-alcohol/excise/settings", json={"frequency": "monthly", "tracking_from": "2026-08-01"}
    )
    assert ok.status_code == 200
    db.expire_all()
    profile = ComplianceService(db).get_profile(org.id)
    alert = excise.reminder(db, org.id, profile, today=date(2026, 9, 5))
    assert alert["title"] == "Excise nil return for August 2026 due 21 Sep 2026"
    assert alert["due_date"] == "2026-09-21" and alert["overdue"] is False
    assert excise.reminder(db, org.id, profile, today=date(2026, 9, 22))["overdue"] is True

    lodged = client.post(
        "/api/compliant/nz-alcohol/excise/lodge", json={"period_start": "2026-08-01", "lodged_on": "2026-09-06"}
    )
    assert lodged.status_code == 201, lodged.get_json()
    assert lodged.get_json()["draft"]["nil_return"] is True
    assert excise.reminder(db, org.id, profile, today=date(2026, 9, 5)) is None


def test_main_configuration_save_keeps_excise_settings(world):
    client = world["client"]
    client.put(
        "/api/compliant/nz-alcohol/excise/settings", json={"frequency": "six_monthly", "tracking_from": "2026-07-01"}
    )
    client.put("/api/compliant/profile", json={"enabled": True, "settings": {"alcohol_product_types": ["spirits"]}})
    periods = client.get("/api/compliant/nz-alcohol/excise/periods").get_json()
    assert periods["settings"] == {"frequency": "six_monthly", "tracking_from": "2026-07-01"}


def test_move_endpoint_and_product_setup(world):
    client = world["client"]
    vat44 = world["lot"]("VAT44", 10)
    loc = client.post("/api/core/stock-locations", json={"name": "Market stall"}).get_json()
    assert client.post("/api/core/stock-locations", json={"name": "Market stall"}).status_code == 409
    moved = client.post(
        f"/api/core/inventory/{vat44.id}/move",
        json={"quantity": "4", "to_location_id": loc["id"], "occurred_on": "2026-09-02"},
    )
    assert moved.status_code == 201 and moved.get_json()["excise_removal"] is True
    assert (
        client.post(
            f"/api/core/inventory/{vat44.id}/move", json={"quantity": "40", "to_location_id": loc["id"]}
        ).status_code
        == 400
    )

    saved = client.put(
        "/api/compliant/nz-alcohol/excise/products",
        json={"name": GIN, "pack_volume_ml": "750", "tariff_item": "2208.50.00", "abv_fallback": "40"},
    )
    assert saved.status_code == 200
    assert (
        client.put("/api/compliant/nz-alcohol/excise/products", json={"name": GIN, "abv_fallback": "140"}).status_code
        == 400
    )
    assert (
        client.post(
            "/api/compliant/nz-alcohol/excise/rates",
            json={"tariff_item": "2208.50.00", "rate_per_lal": "64.10", "effective_from": "2026-07-01"},
        ).status_code
        == 409
    )
