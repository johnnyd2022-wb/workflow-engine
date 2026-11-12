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
from app.features.costing.engine import normalise  # noqa: E402

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
    from app.features.crm.models.xero_credit_note import XeroCreditNote
    from app.features.crm.models.xero_credit_note_line import XeroCreditNoteLine

    for model in (
        XeroCreditNoteLine,
        XeroCreditNote,
        SalesFifoAllocation,
        XeroInvoiceLineItem,
        XeroInvoice,
        ProductMapping,
        AlcoholProductProfile,
    ):
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


def test_unallocated_product_average_and_duty_ignore_same_name_raw_material(world, db):
    from app.core.db.repositories.inventory_repo import InventoryRepository

    _enable_alcohol(world)
    raw = InventoryRepository(db).create_inventory_item(
        org_id=world["org"].id,
        name=GIN,
        quantity="1000",
        unit="kg",
        inventory_type=InventoryType.RAW_MATERIAL.value,
    )
    price(db, world["org"].id, raw.id, D("10000"), D("1000"))
    product = world["lot"]("finished", unit_cost="4")
    world["sell"]([("Wildflower Gin 700ml", 10, "400", "0")])

    from app.features.costing.margins import _Costs

    assert _Costs(db, world["org"].id, products={GIN}).any_lot(GIN) is product
    row = _row(world)

    assert D(row["cost"]) == D("40")
    assert D(row["average_cost_per_unit"]) == D("4")
    assert D(row["duty"]) == D(excise.measure(db, world["org"].id, [(product, D("10"))], SOLD)[0]["duty"])


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


def _credit(world, db, *, amount="80", quantity="2", currency="NZD", day=date(2026, 10, 20)):
    from app.features.crm.models.xero_credit_note import XeroCreditNote
    from app.features.crm.models.xero_credit_note_line import XeroCreditNoteLine

    org = world["org"]
    mapping = db.query(ProductMapping).filter(ProductMapping.org_id == org.id).one()
    note = XeroCreditNote(
        org_id=org.id,
        xero_credit_note_id=f"cn-{uuid4()}",
        xero_tenant_id="t",
        number="CN-TEST",
        date=day,
        status="AUTHORISED",
        total=D(amount),
        currency=currency,
    )
    db.add(note)
    db.flush()
    db.add(
        XeroCreditNoteLine(
            org_id=org.id,
            credit_note_id=note.id,
            line_key="c1",
            description="Wildflower Gin 700ml",
            quantity=D(quantity),
            line_amount=D(amount),
            product_mapping_id=mapping.id,
        )
    )
    db.commit()
    return note


def test_credit_reverses_cost_at_its_month_sales_average(world, db):
    high = world["lot"]("October $10", unit_cost="10")
    world["lot"]("Other product stock $4", unit_cost="4")
    invoice = world["sell"]([("Wildflower Gin 700ml", 10, "400", "0")])
    world["allocate"](invoice, "l1", high, 10)
    _credit(world, db)

    row = _row(world)
    assert D(row["cost"]) == D("80")
    assert row["cost_status"] == "estimated"


def test_credit_without_month_sales_falls_back_to_all_time_average(world, db):
    high = world["lot"]("October $10", unit_cost="10")
    world["lot"]("Other stock $4", unit_cost="4")
    invoice = world["sell"]([("Wildflower Gin 700ml", 10, "400", "0")])
    world["allocate"](invoice, "l1", high, 10)
    _credit(world, db, day=date(2026, 11, 20))

    row = _row(world, month="2026-11")
    assert D(row["cost"]) == D("-14")
    assert row["cost_status"] == "estimated"


def test_foreign_currency_credit_revenue_is_not_tracked(world, db):
    batch = world["lot"]("B1", unit_cost="5")
    inv = world["sell"]([("Wildflower Gin 700ml", 10, "400", "0")])
    world["allocate"](inv, "l1", batch, 10)
    _credit(world, db, amount="80", currency="AUD")

    row = _row(world)
    assert row["revenue"] is None
    assert row["margin"] is None


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
    "query",
    [
        "from=2026-13&to=2026-10",
        "from=nope",
        "from=2026-1&to=2026-10",
        "from=%202026-10&to=2026-10",
        "from=2026-10%20&to=2026-10",
        "from=&to=2026-10",
        "from=2026-10&to=2026-01",
        "from=2020-01&to=2026-10",
    ],
)
def test_bad_ranges_are_400(world, query):
    assert world["client"].get(f"{API}?{query}").status_code == 400


def test_default_range_is_exactly_six_inclusive_months(world, monkeypatch):
    from app.features.costing import purchase_sources

    monkeypatch.setattr(purchase_sources, "nz_today", lambda: date(2026, 11, 12))
    response = world["client"].get(API)

    assert response.status_code == 200
    assert response.get_json()["from"] == "2026-06"
    assert response.get_json()["to"] == "2026-11"


@pytest.mark.parametrize(
    ("quantities", "expected"),
    [([0, 100], "8"), ([0, 0], None)],
)
def test_product_average_excludes_empty_and_nonpositive_lots(world, quantities, expected):
    empty = world["lot"]("empty", qty=quantities[0])
    price(world["db"], world["org"].id, empty.id, D("400"), D("100"))
    positive = world["lot"]("positive", qty=quantities[1])
    price(world["db"], world["org"].id, positive.id, D("800"), D("100"))
    world["sell"]([("Wildflower Gin 700ml", 1, "40", "0")])

    row = _row(world)
    if expected is None:
        assert row["cost"] is None and row["cost_status"] == "unknown"
    else:
        assert D(row["cost"]) == D(expected)


def test_margins_query_count_stays_bounded_with_more_allocations_and_products(world, db):
    from sqlalchemy import event

    def capture_count():
        statements = []
        engine = getattr(db.get_bind(), "engine", db.get_bind())

        def count(*_args):
            statements.append(1)

        event.listen(engine, "before_cursor_execute", count)
        try:
            assert world["client"].get(f"{API}?from=2026-10&to=2026-10").status_code == 200
        finally:
            event.remove(engine, "before_cursor_execute", count)
        return len(statements)

    first = world["lot"]("baseline-1", unit_cost="4")
    baseline_invoice = world["sell"]([("Wildflower Gin 700ml", 3, "120", "0")])
    world["allocate"](baseline_invoice, "l1", world["lot"]("baseline-2", unit_cost="4"), 1)
    world["allocate"](baseline_invoice, "l1", world["lot"]("baseline-3", unit_cost="4"), 1)
    world["allocate"](baseline_invoice, "l1", first, 1)
    baseline = capture_count()

    from app.core.db.repositories.inventory_repo import InventoryRepository

    def extra_product(name, allocations):
        description = f"Margin product {name}"
        mapping = ProductMapping(
            org_id=world["org"].id,
            biz_e_product_name=name,
            xero_description_pattern=description,
        )
        db.add(mapping)
        db.flush()
        invoice = XeroInvoice(
            org_id=world["org"].id,
            xero_invoice_id=f"inv-{uuid4()}",
            xero_tenant_id="t",
            invoice_type="ACCREC",
            status="AUTHORISED",
            invoice_number=f"INV-{uuid4().hex[:4]}",
            date=SOLD,
            currency_code="NZD",
            sub_total=D(allocations * 10),
            total_tax=D(0),
            total=D(allocations * 10),
        )
        db.add(invoice)
        db.flush()
        line = XeroInvoiceLineItem(
            org_id=world["org"].id,
            invoice_id=invoice.id,
            xero_line_item_id="l1",
            description=description,
            quantity=D(allocations),
            line_amount=D(allocations * 10),
            tax_amount=D(0),
        )
        db.add(line)
        db.flush()
        for index in range(allocations):
            item = InventoryRepository(db).create_inventory_item(
                org_id=world["org"].id,
                name=name,
                quantity="100",
                unit="bottles",
                inventory_type=InventoryType.FINAL_PRODUCT.value,
                supplier_batch_number=f"{name}-{index}",
            )
            price(db, world["org"].id, item.id, D("400"), D("100"))
            db.add(
                SalesFifoAllocation(
                    org_id=world["org"].id,
                    xero_invoice_id=invoice.xero_invoice_id,
                    xero_line_key="l1",
                    inventory_item_id=item.id,
                    product_name=name,
                    quantity=D(1),
                    unit="bottles",
                )
            )
        db.commit()

    # Grow the first product from 3 to 6 allocations, then add four products with 6 each.
    line = db.query(XeroInvoiceLineItem).filter(XeroInvoiceLineItem.invoice_id == baseline_invoice.id).one()
    line.quantity = D(6)
    line.line_amount = D(240)
    baseline_invoice.sub_total = D(240)
    baseline_invoice.total = D(240)
    for index in range(3):
        item = world["lot"](f"baseline-extra-{index}", unit_cost="4")
        world["allocate"](baseline_invoice, "l1", item, 1)
    for index in range(2, 6):
        extra_product(f"Margin product {index}", 6)

    scaled = capture_count()
    assert scaled <= baseline + 10, f"query count grew from {baseline} to {scaled}"


def test_duty_measurement_batches_all_allocations_on_the_same_date(world, db, monkeypatch):
    _enable_alcohol(world)
    invoice = world["sell"]([("Wildflower Gin 700ml", 3, "120", "0")])
    for index in range(3):
        world["allocate"](invoice, "l1", world["lot"](f"duty-{index}", unit_cost="4"), 1)

    calls = []
    original = excise.measure

    def measure(session, org_id, pairs, on):
        calls.append((pairs, on))
        return original(session, org_id, pairs, on)

    monkeypatch.setattr(excise, "measure", measure)
    assert world["client"].get(f"{API}?from=2026-10&to=2026-10").status_code == 200

    assert len(calls) == 1
    assert len(calls[0][0]) == 3
    assert calls[0][1] == SOLD


def test_active_alcohol_duty_is_unknown_when_sale_has_no_inventory_lot(world):
    _enable_alcohol(world)
    world["sell"]([("Wildflower Gin 700ml", 3, "120", "0")])

    row = _row(world)

    assert row["duty_tracked"] is True
    assert row["duty"] is None


def test_partial_production_cost_keeps_partial_status_in_margin_row(world, db):
    from tests.costing_helpers import complete, produced_lots, workflow
    from tests.costing_helpers import lot as make_lot

    org = world["org"]
    client = world["client"]
    known = make_lot(db, org.id, "known input", 1, "bottles")
    price(db, org.id, known.id, D("5"), D("1"))
    missing = make_lot(db, org.id, "missing input", 1, "bottles")
    execution, (step,) = workflow(db, org.id, [[{"name": GIN, "unit": "bottles"}]])
    complete(
        client,
        execution,
        step,
        [(known, 1, "bottles"), (missing, 1, "bottles")],
        [{"name": GIN, "quantity": 2, "unit": "bottles"}],
    )
    (batch,) = produced_lots(db, org.id, step.id)
    invoice = world["sell"]([("Wildflower Gin 700ml", 2, "80", "0")])
    world["allocate"](invoice, "l1", batch, 2)

    row = _row(world)

    assert row["cost_status"] == "partial"
    assert row["cost"] is None and row["margin"] is None


def test_production_execution_query_count_stays_flat_as_sold_lots_grow(world, db):
    from sqlalchemy import event

    from tests.costing_helpers import complete, produced_lots, workflow

    org, client = world["org"], world["client"]
    input_lot = world["lot"]("priced input", unit_cost="5")
    invoice = world["sell"]([("Wildflower Gin 700ml", 2, "80", "0")])
    line = db.query(XeroInvoiceLineItem).filter(XeroInvoiceLineItem.invoice_id == invoice.id).one()

    def produce_and_allocate(index):
        execution, (step,) = workflow(db, org.id, [[{"name": GIN, "unit": "bottles"}]])
        complete(
            client,
            execution,
            step,
            [(input_lot, 1, "bottles")],
            [{"name": GIN, "quantity": 1, "unit": "bottles"}],
        )
        (batch,) = produced_lots(db, org.id, step.id)
        db.add(
            SalesFifoAllocation(
                org_id=org.id,
                xero_invoice_id=invoice.xero_invoice_id,
                xero_line_key="l1",
                inventory_item_id=batch.id,
                product_name=GIN,
                quantity=D(1),
                unit="bottles",
            )
        )
        line.quantity = D(index + 1)
        line.line_amount = D((index + 1) * 40)
        invoice.sub_total = D((index + 1) * 40)
        invoice.total = D((index + 1) * 40)
        db.commit()

    for index in range(2):
        produce_and_allocate(index)

    def capture_count():
        statements = []
        engine = getattr(db.get_bind(), "engine", db.get_bind())

        def count(*_args):
            statements.append(1)

        event.listen(engine, "before_cursor_execute", count)
        try:
            assert world["client"].get(f"{API}?from=2026-10&to=2026-10").status_code == 200
        finally:
            event.remove(engine, "before_cursor_execute", count)
        return len(statements)

    baseline = capture_count()
    for index in range(2, 6):
        produce_and_allocate(index)
    scaled = capture_count()

    assert abs(scaled - baseline) <= 2, f"query count grew from {baseline} to {scaled}"


def test_prime_handles_production_lineage_deeper_than_python_recursion_limit(world, db):
    import sys

    from app.features.costing.engine import CostEngine
    from tests.costing_helpers import complete, produced_lots, workflow

    org, client = world["org"], world["client"]
    seed = world["lot"]("lineage seed", unit_cost="1")
    previous = seed
    last = None
    for _ in range(160):
        execution, (execution_step,) = workflow(db, org.id, [[{"name": GIN, "unit": "bottles"}]])
        complete(
            client,
            execution,
            execution_step,
            [(previous, 1, "bottles")],
            [{"name": GIN, "quantity": 1, "unit": "bottles"}],
        )
        (previous,) = produced_lots(db, org.id, execution_step.id)
        last = previous

    engine = CostEngine(db, org.id)
    original_limit = sys.getrecursionlimit()
    try:
        sys.setrecursionlimit(180)
        engine.prime([last.id])
    finally:
        sys.setrecursionlimit(original_limit)

    assert last.id in engine._in_flow_cache


@pytest.mark.parametrize(
    ("sub_total", "total", "expected"),
    [("1.14", "1.15", True), ("1.15", "1.16", False), ("1.14", "1.16", None)],
)
def test_one_cent_tax_picks_the_total_the_lines_match_exactly(sub_total, total, expected):
    """Review r3: with $0.01 GST both totals sit within a cent; the exact match decides."""
    from types import SimpleNamespace

    from app.features.crm.services.sales_sources import _tax_inclusive

    invoice = SimpleNamespace(sub_total=Decimal(sub_total), total=Decimal(total))
    assert _tax_inclusive(invoice, [SimpleNamespace(line_amount=Decimal("1.15"))]) is expected


def test_r5_tracked_duty_that_cannot_be_measured_leaves_the_margin_unknown(world, monkeypatch):
    """Review r5: NZ Alcohol is on but the lot can't be measured: the margin is not revenue - cost."""
    from app.features.compliant.modules.nz_alcohol import excise

    _enable_alcohol(world)
    batch = world["lot"]("B1", unit_cost="4")
    inv = world["sell"]([("Wildflower Gin 700ml", 2, "80", "0")])
    world["allocate"](inv, "l1", batch, 2)
    monkeypatch.setattr(
        excise,
        "measure",
        lambda _db, _org, pairs, _on, **_kw: [{"litres": None, "abv_percent": None, "lal": None, "duty": None}]
        * len(pairs),
    )
    row = _row(world)
    assert row["cost"] is not None and row["duty_tracked"] is True and row["duty"] is None
    assert row["margin"] is None and row["margin_percent"] is None


def test_r5_unrelated_products_are_never_primed(world, db):
    """Review r5: a tenant's other products' history costs this report nothing."""
    from app.features.costing.margins import _Costs
    from tests.costing_helpers import lot as make_lot

    sold = world["lot"]("B1", unit_cost="4")
    unrelated = [
        make_lot(db, world["org"].id, f"Other product {i}", 1, "bottles", inventory_type="final_product")
        for i in range(5)
    ]
    db.commit()
    costs = _Costs(db, world["org"].id, products={GIN}, sold_lot_ids={sold.id})
    primed = set(costs.engine._in_flow_cache)
    assert sold.id in primed
    assert not primed & {item.id for item in unrelated}
    fetched = {item.id for items in costs._lots_by_name.values() for item in items}
    assert not fetched & {item.id for item in unrelated}, "unrelated lots never leave the database"


def test_r6_library_stock_and_spacing_still_match_the_product_in_sql(world, db):
    from app.features.costing.margins import _Costs
    from tests.costing_helpers import lot as make_lot

    library = make_lot(
        db, world["org"].id, f"  {GIN.upper()}  - Library stock", 1, "bottles", inventory_type="final_product"
    )
    db.commit()
    costs = _Costs(db, world["org"].id, products={GIN})
    assert library.id in {item.id for item in costs._lots_by_name[normalise(GIN)]}


def test_r6_a_lineage_too_big_to_prime_reads_unknown_not_a_500(world, monkeypatch):
    from app.features.costing import engine as engine_module

    batch = world["lot"]("B1", unit_cost="4")
    inv = world["sell"]([("Wildflower Gin 700ml", 2, "80", "0")])
    world["allocate"](inv, "l1", batch, 2)
    monkeypatch.setattr(engine_module, "MAX_WORK", 0)
    response = world["client"].get(f"{API}?from=2026-10&to=2026-10")
    assert response.status_code == 200, response.get_json()
    (row,) = [r for r in response.get_json()["rows"] if r["product"] == GIN]
    assert row["cost"] is None and row["cost_status"] == "unknown"


def test_r6_one_unmeasurable_sale_leaves_a_mixed_months_margin_unknown(world, monkeypatch):
    """A month with one measured and one unmeasured sale has no margin: half the duty isn't the duty."""
    from app.features.compliant.modules.nz_alcohol import excise

    _enable_alcohol(world)
    first, second = world["lot"]("B1", unit_cost="4"), world["lot"]("B2", unit_cost="4")
    inv = world["sell"]([("Wildflower Gin 700ml", 2, "80", "0")])
    world["allocate"](inv, "l1", first, 1)
    world["allocate"](inv, "l1", second, 1)
    real = excise.measure

    def half_measured(db, org, pairs, on, **kw):
        out = real(db, org, pairs, on, **kw)
        return [dict(out[0], duty="1.00")] + [dict(r, duty=None) for r in out[1:]]

    monkeypatch.setattr(excise, "measure", half_measured)
    row = _row(world)
    assert row["duty"] is None and row["margin"] is None
