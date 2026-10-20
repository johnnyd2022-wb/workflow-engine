"""Sales -> Excise: monthly LAL and estimated duty, levy and GST from Xero sales."""

from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest

from app.core.db.models.inventory_item import InventoryType
from app.core.db.models.organisation import Organisation
from app.core.db.repositories.inventory_repo import InventoryRepository
from app.features.compliant.models.alcohol_product_profile import AlcoholProductProfile
from app.features.compliant.models.compliance_profile import ComplianceProfile
from app.features.compliant.models.excise import ExciseLodgement, ExciseRate
from app.features.compliant.modules.nz_alcohol import excise, sales_excise
from app.features.crm.models.product_mapping import ProductMapping
from app.features.crm.models.sales_fifo_allocation import SalesFifoAllocation
from app.features.crm.models.xero_invoice import XeroInvoice
from app.features.crm.models.xero_invoice_line_item import XeroInvoiceLineItem
from tests.dag_traversal_helpers import clear_org_synthetic_data
from tests.test_compliant_routes import _admin_client, flask_app  # noqa: F401 -- fixture re-export

GIN = "Wildflower"
SEPT = date(2026, 9, 1)
TODAY = date(2026, 10, 20)


@pytest.fixture
def world(db, flask_app):  # noqa: F811
    org, client = _admin_client(db, flask_app)
    client.put("/api/compliant/profile", json={"enabled": True, "settings": {"alcohol_product_types": ["spirits"]}})
    db.add(
        AlcoholProductProfile(
            org_id=org.id,
            inventory_name=GIN,
            product_type="spirits",
            pack_volume_ml=Decimal("700"),
            abv_percent=Decimal("44"),
            excise_category="gin",
        )
    )
    db.add(ProductMapping(org_id=org.id, biz_e_product_name=GIN, xero_description_pattern="Wildflower Gin 700ml"))
    db.add(
        ProductMapping(
            org_id=org.id, biz_e_product_name=GIN, xero_description_pattern="Wildflower Gin case of 6", units_per_line=6
        )
    )
    db.commit()

    def sell(lines, day, status="AUTHORISED", number=None, invoice_type="ACCREC"):
        inv = XeroInvoice(
            org_id=org.id,
            xero_invoice_id=f"inv-{uuid4()}",
            xero_tenant_id="t",
            invoice_type=invoice_type,
            status=status,
            invoice_number=number or f"INV-{uuid4().hex[:4]}",
            date=day,
        )
        db.add(inv)
        db.flush()
        for i, (description, qty) in enumerate(lines):
            db.add(
                XeroInvoiceLineItem(
                    org_id=org.id,
                    invoice_id=inv.id,
                    xero_line_item_id=f"l{i + 1}",
                    description=description,
                    quantity=Decimal(str(qty)),
                )
            )
        db.commit()
        return inv

    def lot(batch, abv):
        return InventoryRepository(db).create_inventory_item(
            org_id=org.id,
            name=GIN,
            quantity="100",
            unit="bottles",
            inventory_type=InventoryType.FINAL_PRODUCT.value,
            supplier_batch_number=batch,
            extra_data={"abv_percent": abv},
        )

    def allocate(inv, line_key, item, qty):
        db.add(
            SalesFifoAllocation(
                org_id=org.id,
                xero_invoice_id=inv.xero_invoice_id,
                xero_line_key=line_key,
                inventory_item_id=item.id,
                product_name=GIN,
                quantity=Decimal(str(qty)),
                unit="bottles",
            )
        )
        db.commit()

    yield {"org": org, "client": client, "db": db, "sell": sell, "lot": lot, "allocate": allocate}

    db.rollback()
    for model in (
        ExciseLodgement,
        ExciseRate,
        AlcoholProductProfile,
        SalesFifoAllocation,
        XeroInvoiceLineItem,
        XeroInvoice,
        ProductMapping,
    ):
        db.query(model).filter(model.org_id == org.id).delete(synchronize_session=False)
    db.commit()
    clear_org_synthetic_data(db, org.id)
    db.query(Organisation).filter(Organisation.id == org.id).delete(synchronize_session=False)
    db.commit()


def _report(world, start=SEPT):
    return sales_excise.month_report(world["db"], world["org"].id, start, today=TODAY)


def test_worked_example_50_bottles_of_700ml_at_44_percent(world):
    world["sell"]([("Wildflower Gin 700ml", 50)], date(2026, 9, 14), number="INV-0100")
    r = _report(world)
    (row,) = r["rows"]
    assert row["label"] == "Wildflower - 44%"
    assert row["units"] == "50" and row["supplementary_litres"] == "35"
    assert row["lal"] == "15.4"  # 35 L x 0.44
    assert row["tariff_item"] == "99.45.35A" and row["rate"] == "71.034" and row["basis"] == "per_lal"
    assert row["duty"] == "1093.92"  # 15.4 x $71.034 = 1093.9236
    assert row["levy"] == "7.63"  # 35 L x 21.8047 cents
    assert row["gst"] == "165.23"  # 15% of (1093.92 + 7.63)
    assert r["totals"] == {
        "litres": "35",
        "lal": "15.4",
        "duty": "1093.92",
        "levy": "7.63",
        "customs": "1101.55",
        "gst": "165.23",
    }
    assert r["complete"] is True and r["problems"] == [] and r["unmapped"]["count"] == 0


def test_cases_count_in_bottles_and_a_july_sale_uses_last_years_rate(world):
    world["sell"]([("Wildflower Gin case of 6", 2)], date(2026, 6, 3))
    (row,) = _report(world, date(2026, 6, 1))["rows"]
    assert row["units"] == "12" and row["supplementary_litres"] == "8.4" and row["lal"] == "3.696"
    assert row["rate"] == "68.915" and row["duty"] == "254.71"  # 3.696 x 68.915 = 254.7098


def test_batches_at_different_strengths_get_their_own_rows(world):
    inv = world["sell"]([("Wildflower Gin 700ml", 10)], date(2026, 9, 3))
    world["allocate"](inv, "l1", world["lot"]("B44", "44"), 6)
    world["allocate"](inv, "l1", world["lot"]("B42", "42.5"), 3)
    rows = {r["label"]: r for r in _report(world)["rows"]}
    # 6 from the 44% batch, 3 from the 42.5% batch, 1 not matched to a batch -> fallback 44%
    assert set(rows) == {"Wildflower - 44%", "Wildflower - 42.5%"}
    assert rows["Wildflower - 44%"]["units"] == "7"
    assert rows["Wildflower - 42.5%"]["units"] == "3" and rows["Wildflower - 42.5%"]["lal"] == "0.8925"


def test_only_authorised_and_paid_sales_in_the_month_count(world):
    world["sell"]([("Wildflower Gin 700ml", 1)], date(2026, 9, 1), status="PAID")
    world["sell"]([("Wildflower Gin 700ml", 2)], date(2026, 9, 30))
    world["sell"]([("Wildflower Gin 700ml", 100)], date(2026, 9, 5), status="VOIDED")
    world["sell"]([("Wildflower Gin 700ml", 100)], date(2026, 9, 5), status="DRAFT")
    world["sell"]([("Wildflower Gin 700ml", 100)], date(2026, 9, 5), invoice_type="ACCPAY")
    world["sell"]([("Wildflower Gin 700ml", 100)], date(2026, 10, 1))
    world["sell"]([("Wildflower Gin 700ml", 100)], date(2026, 8, 31))
    (row,) = _report(world)["rows"]
    assert row["units"] == "3"


def test_unmapped_lines_and_setup_gaps_are_listed_not_guessed(world):
    db, org = world["db"], world["org"]
    world["sell"]([("Wildflower Gin 700ml", 1), ("Tasting fee", 1)], date(2026, 9, 9))
    db.add(ProductMapping(org_id=org.id, biz_e_product_name="Navy Strength", xero_description_pattern="Navy 500ml"))
    db.commit()
    world["sell"]([("Navy 500ml", 4)], date(2026, 9, 9))
    r = _report(world)
    assert r["unmapped"]["count"] == 1 and r["unmapped"]["lines"][0]["description"] == "Tasting fee"
    navy = next(row for row in r["rows"] if row["product"] == "Navy Strength")
    assert navy["lal"] is None and navy["duty"] is None
    assert {"product": "Navy Strength", "reason": "Not set up as an excise product", "fix": "customs"} in r["problems"]
    assert r["totals"]["duty"] == "21.88"  # only the mapped, set-up gin: 0.308 LAL x 71.034


def test_an_org_rate_overrides_the_built_in_guide(world):
    db, org = world["db"], world["org"]
    profile = db.query(AlcoholProductProfile).filter_by(org_id=org.id, inventory_name=GIN).one()
    profile.customs_product_code = "2208.50.00"
    db.add(ExciseRate(org_id=org.id, tariff_item="2208.50.00", rate_per_lal=Decimal("70"), effective_from=SEPT))
    db.commit()
    world["sell"]([("Wildflower Gin 700ml", 50)], date(2026, 9, 14))
    (row,) = _report(world)["rows"]
    assert row["tariff_item"] == "2208.50.00" and row["rate"] == "70" and row["duty"] == "1078.00"


def test_lodgement_draft_uses_the_built_in_rate_when_none_is_typed(world):
    inv = world["sell"]([("Wildflower Gin 700ml", 12)], date(2026, 9, 10))
    world["allocate"](inv, "l1", world["lot"]("VAT44", "44"), 12)
    d = excise.draft(world["db"], world["org"].id, SEPT, "monthly", today=TODAY)
    (line,) = d["lines"]
    assert line["tariff_item"] == "99.45.35A" and line["rate"] == "71.034" and line["basis"] == "per_lal"
    assert line["duty"] == "262.54"  # 3.696 LAL x 71.034 = 262.5417


def test_months_run_from_the_first_sale_to_now_newest_first(world):
    world["sell"]([("Wildflower Gin 700ml", 50)], date(2026, 8, 20))
    world["sell"]([("Tasting fee", 1)], date(2026, 9, 2))
    months = sales_excise.months(world["db"], world["org"].id, today=TODAY)
    assert [m["month"] for m in months] == ["2026-10", "2026-09", "2026-08"]
    assert months[0]["complete"] is False and months[2]["lal"] == "15.4" and months[2]["customs"] == "1101.55"
    assert months[1]["needs_attention"] is True and months[2]["needs_attention"] is False


def test_page_and_api_only_for_nz_alcohol_orgs(world):
    client, db, org = world["client"], world["db"], world["org"]
    world["sell"]([("Wildflower Gin 700ml", 50)], date(2026, 9, 14))
    assert client.get("/crm/excise").status_code == 200
    body = client.get("/api/crm/excise?month=2026-09").get_json()
    assert body["report"]["totals"]["lal"] == "15.4"
    assert client.get("/api/crm/excise?month=nope").status_code == 400
    assert "/crm/excise" in client.get("/crm").get_data(as_text=True)

    db.query(ComplianceProfile).filter_by(org_id=org.id).update({"enabled": False})
    db.commit()
    assert client.get("/crm/excise").status_code == 404
    assert client.get("/api/crm/excise/months").status_code == 404
    assert "/crm/excise" not in client.get("/crm").get_data(as_text=True)


def test_another_orgs_sales_are_never_counted(world, db, flask_app):  # noqa: F811
    other, other_client = _admin_client(db, flask_app)
    try:
        other_client.put("/api/compliant/profile", json={"enabled": True})
        world["sell"]([("Wildflower Gin 700ml", 50)], date(2026, 9, 14))
        assert other_client.get("/api/crm/excise?month=2026-09").get_json()["report"]["rows"] == []
    finally:
        clear_org_synthetic_data(db, other.id)
        db.query(Organisation).filter(Organisation.id == other.id).delete(synchronize_session=False)
        db.commit()


def test_final_product_suffix_is_left_out_of_the_label():
    assert sales_excise._display_name("Wildflower - final product") == "Wildflower"
    assert sales_excise._display_name("Wildflower") == "Wildflower"
