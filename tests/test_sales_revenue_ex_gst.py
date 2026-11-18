"""Design review 2026-11-17 X1 + A1: one revenue figure, ex GST in the base currency.

X1: monthly sales summed ``XeroInvoice.total`` (GST-inclusive, foreign currency unconverted, as a float)
while margins counted ex-GST base-currency revenue. A1: margins dropped the lines it could not map to a
product, so its revenue sat below Xero's by an amount nobody could see. Worked numbers, written before the fix.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import uuid4

from app.features.crm.models.xero_contact import XeroContact
from app.features.crm.models.xero_credit_note import XeroCreditNote
from app.features.crm.repositories.xero_invoice_repo import XeroInvoiceRepository
from tests.test_compliant_routes import flask_app  # noqa: F401 -- fixture re-export
from tests.test_costing_margins import world  # noqa: F401 -- fixture re-export

D = Decimal
MONTHLY = "/api/crm/analytics/monthly-sales?months=24"
MARGINS = "/api/core/costing/margins?from=2026-10&to=2026-10"
OCTOBER = date(2026, 10, 7)


def _october(world):  # noqa: F811
    body = world["client"].get(MONTHLY).get_json()
    rows = [r for r in body["monthly_sales"] if r["month"] == "2026-10"]
    assert len(rows) == 1, body
    return rows[0]


def test_x1_a_tax_inclusive_invoice_of_115_with_15_tax_is_100_of_revenue(world):  # noqa: F811
    world["sell"]([("Wildflower Gin 700ml", 1, "115", "15")], inclusive=True)  # total 115, tax 15

    row = _october(world)

    assert row["total"] == "100.00", "revenue is ex GST, as a Decimal string"
    assert row["invoiced_inc_gst"] == "115.00", "the old GST-inclusive figure keeps its own name"
    assert row["invoice_count"] == 1


def test_x1_a_usd_invoice_is_not_added_to_the_base_currency_total(world):  # noqa: F811
    world["sell"]([("Wildflower Gin 700ml", 1, "100", "15")])  # NZD: 100 ex GST
    world["sell"]([("Wildflower Gin 700ml", 1, "500", "0")], currency="USD")

    row = _october(world)

    assert row["total"] == "100.00", "500 USD is never added as if it were NZD"
    assert row["not_converted"] == 1
    assert row["currency"] == "NZD"


def test_x1_a_credit_note_comes_off_ex_gst(world):  # noqa: F811
    db, org = world["db"], world["org"]
    world["sell"]([("Wildflower Gin 700ml", 1, "100", "15")])
    db.add(
        XeroCreditNote(
            org_id=org.id,
            xero_credit_note_id=f"cn-{uuid4()}",
            xero_tenant_id="t",
            status="AUTHORISED",
            date=OCTOBER,
            total=D("23"),
            currency="NZD",
            raw_fields={"sub_total": "20", "total_tax": "3"},
        )
    )
    db.commit()

    row = _october(world)

    assert row["total"] == "80.00"  # 100 - 20, not 100 - 23
    assert row["invoiced_inc_gst"] == "92.00"  # 115 - 23


def test_x1_daily_and_customer_totals_use_the_same_ex_gst_rule(world):  # noqa: F811
    db, org = world["db"], world["org"]
    contact = XeroContact(org_id=org.id, xero_contact_id=f"c-{uuid4()}", xero_tenant_id="t", name="Corner Store")
    db.add(contact)
    db.flush()
    try:
        inv = world["sell"]([("Wildflower Gin 700ml", 1, "115", "15")], inclusive=True)
        inv.contact_id = contact.id
        world["sell"]([("Wildflower Gin 700ml", 1, "500", "0")], currency="USD")
        db.commit()
        repo = XeroInvoiceRepository(db)

        (day,) = repo.daily_sales_totals_for_period(org.id, date(2026, 10, 1), date(2026, 11, 1))
        (month,) = repo.monthly_sales_totals_for_contact(contact.id, org.id)
        period = repo.sales_totals_for_period(org.id, date(2026, 10, 1), date(2026, 11, 1))

        assert (day["day"], D(day["total"])) == ("2026-10-07", D("100"))
        assert D(month["total"]) == D("100")
        assert D(str(period["total"])) == D("100")
    finally:
        db.rollback()
        from app.features.crm.models.xero_invoice import XeroInvoice

        db.query(XeroInvoice).filter(XeroInvoice.org_id == org.id).update(
            {XeroInvoice.contact_id: None}, synchronize_session=False
        )
        db.query(XeroContact).filter(XeroContact.org_id == org.id).delete(synchronize_session=False)
        db.commit()


def test_a1_margins_shows_the_unmapped_50_line_beside_its_rows(world):  # noqa: F811
    world["sell"]([("Wildflower Gin 700ml", 1, "100", "15"), ("Freight", 1, "50", "7.50")])

    body = world["client"].get(MARGINS).get_json()

    assert [D(r["revenue"]) for r in body["rows"]] == [D("100")]
    assert body["unmapped"]["revenue"] == "50.00"
    assert body["unmapped"]["lines"] == 1
