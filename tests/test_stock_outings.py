"""Taking stock out to a tasting or event: pours, bottles sold and bottles brought back
(founder, 2026-10-28).

Take 10 bottles, sell 6 at the event, bring 4 back. All 10 were removed for excise when they
left. The 6 sold are sales of stock already removed: counted at close or as linked Xero lines,
never a second removal and never taken from warehouse stock. The 4 go back where they came from
as their own lot, duty paid, and are listed as a possible credit to raise with Customs.
"""

from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest

from app.core.db.models.inventory_item import InventoryItem
from app.core.domain.inventory_quantity_guard import InventoryQuantityWriteReason, allow_inventory_quantity_write
from app.features.compliant.modules.nz_alcohol import excise
from app.features.crm.models.product_mapping import ProductMapping
from app.features.crm.models.sales_fifo_allocation import SalesFifoAllocation
from app.features.crm.models.xero_invoice import XeroInvoice
from app.features.crm.models.xero_invoice_line_item import XeroInvoiceLineItem
from app.features.crm.services.sales_traceability_service import SalesTraceabilityService
from app.features.tastings.models import TastingAllocation, TastingStockLot
from app.features.tastings.services import tasting_service as service
from tests.test_tastings import payload, world  # noqa: F401 -- shared fixture

OCT = date(2026, 10, 1)


def _event(db, world, quantity="10"):  # noqa: F811
    org, rep, item, *_ = world
    event = service.save_event(db, org.id, rep.id, {**payload(rep, item, quantity), "kind": "event"})
    service.dispatch(db, org.id, rep.id, event.id, {"actual_date": "2026-10-20"}, str(uuid4()))
    db.commit()
    return event


def _close(db, world, event, sold="0", returned="0", used="0", links=None):  # noqa: F811
    org, rep, *_ = world
    (line,) = db.query(TastingAllocation).filter(TastingAllocation.tasting_id == event.id).all()
    body = {
        "usage": [
            {"allocation_id": str(line.id), "used_volume_ml": used, "sold_units": sold, "returned_units": returned}
        ]
    }
    if links is not None:
        body["invoice_lines"] = [{"allocation_id": str(line.id), **link} for link in links]
    service.finalise(db, org.id, rep.id, event.id, body)
    db.commit()
    db.refresh(line)
    return line


def _sale(db, org, quantity, day=date(2026, 10, 20), name="INV-EVENT"):
    invoice = XeroInvoice(
        org_id=org.id,
        xero_invoice_id=f"inv-{uuid4()}",
        xero_tenant_id="t",
        invoice_type="ACCREC",
        status="AUTHORISED",
        invoice_number=name,
        date=day,
    )
    db.add(invoice)
    db.flush()
    db.add(
        XeroInvoiceLineItem(
            org_id=org.id,
            invoice_id=invoice.id,
            xero_line_item_id=f"{name}-1",
            description="Sampling Gin 700",
            quantity=Decimal(quantity),
        )
    )
    db.commit()
    return invoice


def _map(db, org, item):
    # Sales match oldest batch first by its number, so a sold product carries a numbered batch.
    item.extra_data = {**item.extra_data, "batch_number": 12}
    db.add(ProductMapping(org_id=org.id, biz_e_product_name=item.name, xero_description_pattern="Sampling Gin 700"))
    db.commit()


def _removal_refs(d):
    return sorted((r["kind"], r["quantity"]) for line in d["lines"] for r in line["removals"])


def test_take_ten_sell_six_bring_four_back(db, world):  # noqa: F811
    org, _, item, *_ = world
    item.supplier_batch_number = "WB-26-041"
    db.commit()
    event = _event(db, world)
    assert event.kind == "event"
    line = _close(db, world, event, sold="6", returned="4")
    assert (line.sold_units, line.returned_units) == (6, 4)
    db.refresh(item)
    assert item.quantity == 0  # all ten left when they were taken out
    back = db.get(InventoryItem, line.return_item_id)
    assert back.quantity == 4 and back.name == item.name and back.site_id == item.site_id
    # Its own lot of the same batch, beside the duty-suspended one: recall still finds it.
    assert back.supplier_batch_number == item.supplier_batch_number and back.location_id == item.location_id
    assert back.extra_data["duty_paid_return"]["tasting_id"] == str(event.id)
    pool = db.get(TastingStockLot, line.stock_lot_id)
    assert pool.remaining_volume_ml == 0  # nothing left in tasting stock: sold or back

    d = excise.draft(db, org.id, OCT, "monthly", today=date(2026, 11, 5))
    assert [Decimal(line["units"]) for line in d["lines"]] == [Decimal("10")]  # the removal when they left, once
    (credit,) = d["returns"]
    assert Decimal(credit["quantity"]) == 4 and credit["reference"] == "Back from Friday tasting"


def test_bottles_brought_back_are_duty_paid_when_sold_later(db, world):  # noqa: F811
    org, _, item, *_ = world
    _map(db, org, item)
    line = _close(db, world, _event(db, world), sold="6", returned="4")
    _sale(db, org, "2", day=date(2026, 10, 25), name="INV-LATER")
    SalesTraceabilityService(db).reconcile_org(org.id)
    db.commit()
    db.refresh(db.get(InventoryItem, line.return_item_id))
    assert db.get(InventoryItem, line.return_item_id).quantity == 2  # sold from the bottles that came back
    d = excise.draft(db, org.id, OCT, "monthly", today=date(2026, 11, 5))
    assert [Decimal(line["units"]) for line in d["lines"]] == [Decimal("10")]  # no second removal for them


def test_a_xero_sale_at_the_event_comes_from_event_stock_not_the_warehouse(db, world):  # noqa: F811
    org, rep, item, *_ = world
    # Fifteen in the warehouse: take ten to the event, five stay behind.
    with allow_inventory_quantity_write(InventoryQuantityWriteReason.MANUAL_API_UPDATE):
        item.quantity = Decimal("15")
        db.commit()
    event = _event(db, world)
    _map(db, org, item)
    invoice = _sale(db, org, "3")
    SalesTraceabilityService(db).reconcile_org(org.id)  # the sync matches it to the warehouse, oldest first
    db.commit()
    db.refresh(item)
    assert item.quantity == 2  # the sync took the three invoiced from what stayed behind
    choices = service.invoice_line_choices(db, org.id, event.id)
    assert [(c["invoice_number"], c["quantity"]) for c in choices] == [("INV-EVENT", "3")]

    line = _close(
        db,
        world,
        event,
        sold="2",
        returned="5",
        links=[{"xero_invoice_id": invoice.xero_invoice_id, "line_key": "INV-EVENT-1"}],
    )
    assert (line.sold_units, line.returned_units) == (5, 5)  # 2 counted + 3 invoiced
    db.refresh(item)
    assert item.quantity == 5  # the warehouse match was undone: those bottles never left
    linked = db.query(SalesFifoAllocation).filter(SalesFifoAllocation.xero_invoice_id == invoice.xero_invoice_id).all()
    assert [(a.quantity, a.tasting_allocation_id) for a in linked] == [(3, line.id)]

    # A later sync leaves it alone, and excise counts the ten once.
    SalesTraceabilityService(db).reconcile_org(org.id)
    db.commit()
    db.refresh(item)
    assert item.quantity == 5
    d = excise.draft(db, org.id, OCT, "monthly", today=date(2026, 11, 5))
    assert [Decimal(line["units"]) for line in d["lines"]] == [Decimal("10")]
    assert service.invoice_line_choices(db, org.id, event.id) == []  # no longer offered
    with pytest.raises(ValueError, match="sold at a tasting or event"):
        SalesTraceabilityService(db).assign_line(
            org.id, invoice.xero_invoice_id, "INV-EVENT-1", [{"inventory_item_id": str(item.id), "quantity": "3"}]
        )
    # The invoice is edited afterwards (3 becomes 4): the sync still leaves the warehouse alone.
    db.query(XeroInvoiceLineItem).filter(XeroInvoiceLineItem.invoice_id == invoice.id).one().quantity = Decimal("4")
    db.commit()
    SalesTraceabilityService(db).reconcile_org(org.id)
    db.commit()
    db.refresh(item)
    assert item.quantity == 5


@pytest.mark.parametrize(
    ("sold", "returned", "used", "message"),
    [
        ("8", "4", "0", "more than was taken"),
        ("2", "1.5", "0", "whole bottles"),
        ("9", "0", "800", "more than was taken"),  # nine sold and more than a bottle poured
    ],
)
def test_a_close_that_does_not_add_up_is_refused(db, world, sold, returned, used, message):  # noqa: F811
    event = _event(db, world)
    with pytest.raises(service.TastingError, match=message):
        _close(db, world, event, sold=sold, returned=returned, used=used)


def test_a_tasting_that_pours_only_still_closes_as_before(db, world):  # noqa: F811
    org, rep, item, *_ = world
    event = service.save_event(db, org.id, rep.id, payload(rep, item, "2"))
    service.dispatch(db, org.id, rep.id, event.id, {"actual_date": "2026-10-20"}, str(uuid4()))
    db.commit()
    (line,) = db.query(TastingAllocation).filter(TastingAllocation.tasting_id == event.id).all()
    service.finalise(
        db, org.id, rep.id, event.id, {"usage": [{"allocation_id": str(line.id), "used_volume_ml": "300"}]}
    )
    db.commit()
    assert event.kind == "tasting" and line.sold_units == 0 and line.return_item_id is None
    pool = db.get(TastingStockLot, line.stock_lot_id)
    assert pool.remaining_volume_ml == 1100  # 1,400 mL taken, 300 poured: the rest waits in tasting stock


def test_only_live_sales_on_the_event_day_are_offered_and_linked(db, world):  # noqa: F811
    org, _, item, *_ = world
    event = _event(db, world)
    _map(db, org, item)
    voided = _sale(db, org, "1", name="INV-VOID")
    voided.status = "VOIDED"
    _sale(db, org, "1", day=date(2026, 10, 21), name="INV-NEXT-DAY")
    db.commit()
    assert service.invoice_line_choices(db, org.id, event.id) == []
    with pytest.raises(service.TastingError, match="approved or paid"):
        _close(db, world, event, links=[{"xero_invoice_id": voided.xero_invoice_id, "line_key": "INV-VOID-1"}])


def test_voiding_a_linked_invoice_puts_nothing_back_in_the_warehouse(db, world):  # noqa: F811
    org, _, item, *_ = world
    event = _event(db, world)
    _map(db, org, item)
    invoice = _sale(db, org, "3")
    _close(
        db, world, event, returned="7", links=[{"xero_invoice_id": invoice.xero_invoice_id, "line_key": "INV-EVENT-1"}]
    )
    invoice.status = "VOIDED"
    db.commit()
    SalesTraceabilityService(db).reconcile_org(org.id)
    db.commit()
    db.refresh(item)
    assert item.quantity == 0  # the three were sold from event stock, never from here


def test_bottles_can_only_come_back_from_stock_taken_as_bottles(db, world):  # noqa: F811
    org, rep, item, *_ = world
    first = _event(db, world, "1")
    _close(db, world, first, used="100")  # 600 mL left in tasting stock
    lot = db.query(TastingStockLot).filter_by(org_id=org.id).one()
    data = payload(rep, item)
    data["allocations"] = [{"source_pool_id": str(lot.id), "quantity": "300"}]
    again = service.save_event(db, org.id, rep.id, data)
    service.dispatch(db, org.id, rep.id, again.id, {"actual_date": "2026-10-21"}, str(uuid4()))
    db.commit()
    with pytest.raises(service.TastingError, match="only from stock taken as bottles"):
        _close(db, world, again, returned="1")


def test_invoice_lines_api_is_scoped_to_the_org(db, world):  # noqa: F811
    from app.api.app_factory import create_app
    from app.core.db.repositories.feature_subscription_repo import FeatureSubscriptionRepository
    from app.features.compliant.models.compliance_profile import ComplianceProfile
    from tests.factories import DEFAULT_TEST_PASSWORD, OrganisationFactory, UserFactory

    org, rep, item, *_ = world
    event = _event(db, world)
    _map(db, org, item)
    _sale(db, org, "2")
    other = OrganisationFactory()
    stranger = UserFactory(org_id=other.id, email=f"stranger-{uuid4()}@example.test")
    for org_id in (org.id, other.id):
        FeatureSubscriptionRepository(db).grant(org_id, "compliant")
        db.add(ComplianceProfile(org_id=org_id, enabled=True, industry_module="nz_alcohol"))
    db.commit()
    app = create_app()
    app.config.update(TESTING=True, WTF_CSRF_ENABLED=False)

    def login(user):
        client = app.test_client()
        client.environ_base["wsgi.url_scheme"] = "https"
        client.environ_base["HTTP_X_FORWARDED_PROTO"] = "https"
        assert (
            client.post("/auth/login", json={"email": user.email, "password": DEFAULT_TEST_PASSWORD}).status_code == 200
        )
        return client

    response = login(rep).get(f"/api/crm/tastings/{event.id}/invoice-lines")
    assert response.status_code == 200
    assert [(line["invoice_number"], line["quantity"]) for line in response.get_json()["lines"]] == [("INV-EVENT", "2")]
    assert login(stranger).get(f"/api/crm/tastings/{event.id}/invoice-lines").status_code == 404
