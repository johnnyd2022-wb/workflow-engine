"""Live-cogs 8.1f-2: margin per product per month, with duty from the excise module.

Spec .agents/specs/live-cogs.md, "8.1f-2 build contract" (AC45-AC48, AC102-AC104). Written before the code.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest

from app.core.db.models.inventory_item import InventoryType
from app.core.db.models.user import UserRole
from app.core.db.repositories.feature_subscription_repo import FeatureSubscriptionRepository
from app.core.db.repositories.inventory_repo import InventoryRepository
from app.features.compliant.models.alcohol_product_profile import AlcoholProductProfile
from app.features.compliant.modules.nz_alcohol import excise
from app.features.crm.models.product_mapping import ProductMapping
from app.features.crm.models.sales_fifo_allocation import SalesFifoAllocation
from app.features.crm.models.xero_invoice import XeroInvoice
from app.features.crm.models.xero_invoice_line_item import XeroInvoiceLineItem
from tests.costing_helpers import new_org, price, purge, user_client
from tests.test_compliant_routes import flask_app  # noqa: F401 -- fixture re-export

API = "/api/core/costing/margins"
GIN = "Wildflower"
D = Decimal
SOLD = date(2026, 10, 7)


@pytest.fixture
def world(db, flask_app):  # noqa: F811
    org = new_org(db)  # costing granted
    FeatureSubscriptionRepository(db).grant(org.id, "crm")
    client = user_client(db, flask_app, org)
    db.add(
        AlcoholProductProfile(
            org_id=org.id,
            inventory_name=GIN,
            product_type="spirits",
            pack_volume_ml=D("700"),
            abv_percent=D("44"),
            excise_category="gin",
        )
    )
    db.add(ProductMapping(org_id=org.id, biz_e_product_name=GIN, xero_description_pattern="Wildflower Gin 700ml"))
    db.commit()

    def sell(lines, day=SOLD, *, inclusive=False, status="AUTHORISED", currency="NZD"):
        """lines: (description, qty, line_amount, tax)."""
        net = sum(D(str(a)) for _, _, a, _ in lines)
        tax = sum(D(str(t)) for _, _, _, t in lines)
        inv = XeroInvoice(
            org_id=org.id,
            xero_invoice_id=f"inv-{uuid4()}",
            xero_tenant_id="t",
            invoice_type="ACCREC",
            status=status,
            invoice_number=f"INV-{uuid4().hex[:4]}",
            date=day,
            currency_code=currency,
            sub_total=(net - tax) if inclusive else net,
            total_tax=tax,
            total=net if inclusive else net + tax,
        )
        db.add(inv)
        db.flush()
        for i, (description, qty, amount, line_tax) in enumerate(lines):
            db.add(
                XeroInvoiceLineItem(
                    org_id=org.id,
                    invoice_id=inv.id,
                    xero_line_item_id=f"l{i + 1}",
                    description=description,
                    quantity=D(str(qty)),
                    line_amount=D(str(amount)),
                    tax_amount=D(str(line_tax)),
                )
            )
        db.commit()
        return inv

    def lot(batch, unit_cost=None, qty=100):
        item = InventoryRepository(db).create_inventory_item(
            org_id=org.id,
            name=GIN,
            quantity=str(qty),
            unit="bottles",
            inventory_type=InventoryType.FINAL_PRODUCT.value,
            supplier_batch_number=batch,
            extra_data={"abv_percent": "44"},
        )
        if unit_cost is not None:
            price(db, org.id, item.id, D(str(unit_cost)) * qty, qty)
        return item

    def allocate(inv, line_key, item, qty):
        db.add(
            SalesFifoAllocation(
                org_id=org.id,
                xero_invoice_id=inv.xero_invoice_id,
                xero_line_key=line_key,
                inventory_item_id=item.id,
                product_name=GIN,
                quantity=D(str(qty)),
                unit="bottles",
            )
        )
        db.commit()

    yield {"org": org, "client": client, "db": db, "sell": sell, "lot": lot, "allocate": allocate}

    db.rollback()
    for model in (SalesFifoAllocation, XeroInvoiceLineItem, XeroInvoice, ProductMapping, AlcoholProductProfile):
        db.query(model).filter(model.org_id == org.id).delete(synchronize_session=False)
    db.commit()
    purge(db, org)


def _enable_alcohol(world):
    """The org runs NZ Alcohol: the Compliance subscription and the module switched on."""
    from app.features.compliant.service import ComplianceService

    db, org = world["db"], world["org"]
    FeatureSubscriptionRepository(db).grant(org.id, "compliant")
    ComplianceService(db).upsert_profile(
        org.id, {"enabled": True, "industry_module": "nz_alcohol", "settings": {"alcohol_product_types": ["spirits"]}}
    )
    db.commit()


def _row(world, month="2026-10"):
    body = world["client"].get(f"{API}?from={month}&to={month}").get_json()
    rows = [r for r in body["rows"] if r["product"] == GIN and r["month"] == month]
    assert len(rows) == 1, body
    return rows[0]


def test_ac45_margin_with_cost_and_duty_from_the_excise_module(world, db):
    from app.core.security.entitlements import org_has_feature

    _enable_alcohol(world)
    assert org_has_feature(db, world["org"].id, "compliant")
    batch = world["lot"]("B1", unit_cost="4.75")
    inv = world["sell"]([("Wildflower Gin 700ml", 12, "480", "72")])
    world["allocate"](inv, "l1", batch, 12)
    row = _row(world)
    duty = D(excise.measure(db, world["org"].id, [(batch, D("12"))], SOLD)[0]["duty"])
    assert (D(row["units"]), D(row["revenue"]), D(row["cost"])) == (D("12"), D("480"), D("57"))
    assert row["cost_status"] == "actual"
    assert D(row["duty"]) == duty and duty > 0
    assert D(row["margin"]) == D("480") - D("57") - duty
    assert D(row["average_cost_per_unit"]) == D("4.75")
    (line,) = row["lines"]
    assert line["batches"][0]["inventory_item_id"] == str(batch.id)


def test_ac46_units_with_no_lot_use_the_products_average_and_are_estimated(world, db):
    a = world["lot"]("A", unit_cost="4")
    b = world["lot"]("B", unit_cost="6")
    inv = world["sell"]([("Wildflower Gin 700ml", 10, "400", "0")])
    world["allocate"](inv, "l1", a, 2)
    world["allocate"](inv, "l1", b, 2)  # 6 of 10 units have no lot
    row = _row(world)
    assert row["cost_status"] == "estimated"
    # 2 x 4 + 2 x 6 + 6 x average(4, 6 by units = 5) = 8 + 12 + 30
    assert D(row["cost"]) == D("50")


def test_ac46_no_costed_lot_at_all_is_unknown_not_zero(world, db):
    world["sell"]([("Wildflower Gin 700ml", 5, "200", "0")])
    row = _row(world)
    assert row["cost_status"] == "unknown" and row["cost"] is None
    assert row["margin"] is None, "no margin from an unknown cost"


def test_ac47_needs_costs_view_and_sales_view(world, db, flask_app):  # noqa: F811
    org = world["org"]
    only_costs = user_client(db, flask_app, org, permissions=["costs.view"])
    only_sales = user_client(db, flask_app, org, permissions=["sales.view"])
    both = user_client(db, flask_app, org, permissions=["costs.view", "sales.view"])
    assert only_costs.get(API).status_code == 403
    assert only_sales.get(API).status_code == 403
    assert both.get(API).status_code == 200
    assert user_client(db, flask_app, org, role=UserRole.PRODUCTION).get(API).status_code == 403


def test_ac48_duty_is_not_tracked_without_the_alcohol_module(world, db):
    batch = world["lot"]("B1", unit_cost="4.75")
    inv = world["sell"]([("Wildflower Gin 700ml", 12, "480", "72")])
    world["allocate"](inv, "l1", batch, 12)
    row = _row(world)
    assert row["duty"] is None
    assert D(row["margin"]) == D("423")


def test_ac102_tax_inclusive_lines_count_revenue_ex_gst(world, db):
    batch = world["lot"]("B1", unit_cost="4.75")
    inv = world["sell"]([("Wildflower Gin 700ml", 12, "552", "72")], inclusive=True)
    world["allocate"](inv, "l1", batch, 12)
    assert D(_row(world)["revenue"]) == D("480")


def test_foreign_currency_revenue_is_not_tracked(world, db):
    batch = world["lot"]("B1", unit_cost="4.75")
    inv = world["sell"]([("Wildflower Gin 700ml", 12, "300", "0")], currency="AUD")
    world["allocate"](inv, "l1", batch, 12)
    row = _row(world)
    assert row["revenue"] is None and row["margin"] is None


def test_ac103_credit_note_reduces_revenue_and_units_with_estimated_cost(world, db):
    from app.features.crm.models.xero_credit_note import XeroCreditNote
    from app.features.crm.models.xero_credit_note_line import XeroCreditNoteLine

    org = world["org"]
    batch = world["lot"]("B1", unit_cost="5")
    inv = world["sell"]([("Wildflower Gin 700ml", 10, "400", "0")])
    world["allocate"](inv, "l1", batch, 10)
    mapping = db.query(ProductMapping).filter(ProductMapping.org_id == org.id).one()
    note = XeroCreditNote(
        org_id=org.id,
        xero_credit_note_id=f"cn-{uuid4()}",
        xero_tenant_id="t",
        number="CN-1",
        contact="Bottle-O",
        date=date(2026, 10, 20),
        status="AUTHORISED",
        total=D("80"),
        currency="NZD",
    )
    db.add(note)
    db.flush()
    db.add(
        XeroCreditNoteLine(
            org_id=org.id,
            credit_note_id=note.id,
            line_key="c1",
            description="Wildflower Gin 700ml",
            quantity=D("2"),
            line_amount=D("80"),
            product_mapping_id=mapping.id,
        )
    )
    db.commit()
    try:
        row = _row(world)
        assert (D(row["units"]), D(row["revenue"])) == (D("8"), D("320"))
        assert D(row["cost"]) == D("40") and row["cost_status"] == "estimated"
    finally:
        db.query(XeroCreditNoteLine).filter(XeroCreditNoteLine.org_id == org.id).delete()
        db.query(XeroCreditNote).filter(XeroCreditNote.org_id == org.id).delete()
        db.commit()


def test_ac104_margins_never_cross_orgs(world, db, flask_app):  # noqa: F811
    batch = world["lot"]("B1", unit_cost="4.75")
    inv = world["sell"]([("Wildflower Gin 700ml", 12, "480", "0")])
    world["allocate"](inv, "l1", batch, 12)
    other = new_org(db)
    try:
        FeatureSubscriptionRepository(db).grant(other.id, "crm")
        body = user_client(db, flask_app, other).get(f"{API}?from=2026-10&to=2026-10").get_json()
        assert body["rows"] == []
    finally:
        purge(db, other)


@pytest.mark.parametrize(
    "query", ["from=2026-13&to=2026-10", "from=nope", "from=2026-10&to=2026-01", "from=2020-01&to=2026-10"]
)
def test_bad_ranges_are_400(world, query):
    assert world["client"].get(f"{API}?{query}").status_code == 400
