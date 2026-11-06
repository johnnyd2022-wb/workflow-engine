"""GL-P01b: goods back from a customer, kept apart from the credit note (money) and duty."""

from datetime import date, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest

from app.core.db.models.audit_log import AuditLog
from app.core.db.models.inventory_item import InventoryItem
from app.core.db.models.lot_hold import LotHold
from app.core.db.models.stock_location import StockLocation
from app.core.domain.inventory_quantity_guard import InventoryQuantityWriteReason, allow_inventory_quantity_write
from app.core.services import lot_holds
from app.features.crm.models.product_mapping import ProductMapping
from app.features.crm.models.sales_fifo_allocation import SalesFifoAllocation
from app.features.crm.models.sales_return import SalesReturn
from app.features.crm.models.xero_credit_note import XeroCreditNote
from app.features.crm.models.xero_credit_note_line import XeroCreditNoteLine
from app.features.crm.services import sales_returns
from tests import test_crm as crm_fixtures
from tests.factories import OrganisationFactory

db = crm_fixtures.db
org = crm_fixtures.org
user = crm_fixtures.user
app_client = crm_fixtures.app_client

PRODUCT = "Dry gin 700ml"
TODAY = date.today()


@pytest.fixture(autouse=True)
def cleanup(db, org):
    yield
    db.rollback()
    for model in (SalesReturn,):
        db.query(model).filter(model.org_id == org.id).delete(synchronize_session=False)
    db.query(LotHold).filter(LotHold.org_id == org.id).delete(synchronize_session=False)
    for model in (
        SalesFifoAllocation,
        XeroCreditNoteLine,
        XeroCreditNote,
        InventoryItem,
        ProductMapping,
        StockLocation,
    ):
        db.query(model).filter(model.org_id == org.id).delete(synchronize_session=False)
    db.commit()


def _lot(db, org_id, quantity="4", location_id=None, name=PRODUCT):
    with allow_inventory_quantity_write(InventoryQuantityWriteReason.REPOSITORY_CREATE):
        item = InventoryItem(
            org_id=org_id,
            name=name,
            quantity=Decimal(quantity),
            unit="each",
            inventory_type="final_product",
            location_id=location_id,
            extra_data={"batch_number": 12},
        )
        db.add(item)
        db.commit()
    return item


@pytest.fixture
def credited(db, org):
    """A lot that sold 6 on invoice inv-1 (4 left), and a credit note for 3 of them."""
    lot = _lot(db, org.id)
    mapping = ProductMapping(
        org_id=org.id, biz_e_product_name=PRODUCT, xero_description_pattern="Dry gin", match_type="exact"
    )
    db.add(mapping)
    db.flush()
    allocation = SalesFifoAllocation(
        org_id=org.id,
        xero_invoice_id="inv-1",
        xero_line_key="inv-1:line-1",
        inventory_item_id=lot.id,
        product_mapping_id=mapping.id,
        product_name=PRODUCT,
        quantity=Decimal("6"),
        unit="each",
    )
    note = XeroCreditNote(
        org_id=org.id,
        xero_credit_note_id=f"cn-{uuid4()}",
        xero_tenant_id="tenant",
        number="CN-7",
        status="AUTHORISED",
        total=Decimal("120"),
        date=TODAY,
        allocated_invoice_ids=["inv-1"],
    )
    db.add_all([allocation, note])
    db.flush()
    line = XeroCreditNoteLine(
        org_id=org.id,
        credit_note_id=note.id,
        line_key="cn-line-1",
        description="Dry gin",
        quantity=Decimal("3"),
        line_amount=Decimal("120"),
        product_mapping_id=mapping.id,
    )
    db.add(line)
    db.commit()
    return {"lot": lot, "allocation": allocation, "note": note, "line": line, "mapping": mapping}


def _return(db, org_id, credited, condition, quantity, note=None):
    ret = sales_returns.record_return(
        db,
        org_id,
        None,
        condition=condition,
        quantity=quantity,
        received_on=TODAY,
        note=note,
        credit_note_line_id=credited["line"].id,
    )
    db.commit()
    return ret


def _qty(db, item_id):
    db.expire_all()
    return db.get(InventoryItem, item_id).quantity


# --- conditions -----------------------------------------------------------------------------------


def test_resaleable_goes_back_into_the_batch_it_was_sold_from(db, org, credited):
    ret = _return(db, org.id, credited, "resaleable", "2")
    assert ret.resulting_lot_id == credited["lot"].id == ret.original_lot_id
    assert ret.allocation_id == credited["allocation"].id and ret.xero_invoice_id == "inv-1"
    assert _qty(db, credited["lot"].id) == Decimal("6")


def test_damaged_comes_back_as_its_own_lot_on_quality_hold(db, org, credited):
    ret = _return(db, org.id, credited, "damaged", "1", note="Broken seals")
    assert ret.resulting_lot_id != credited["lot"].id
    lot = db.get(InventoryItem, ret.resulting_lot_id)
    assert (lot.name, lot.quantity, lot.extra_data["batch_number"]) == (PRODUCT, Decimal("1.0000"), 12)
    held = lot_holds.open_holds(db, org.id, [lot.id])
    assert held[lot.id].reason == "Returned damaged: Broken seals" and ret.hold_id == held[lot.id].id
    assert _qty(db, credited["lot"].id) == Decimal("4")  # the good batch is untouched


def test_destroyed_puts_nothing_back(db, org, credited):
    before = db.query(InventoryItem).filter(InventoryItem.org_id == org.id).count()
    ret = _return(db, org.id, credited, "destroyed", "3", note="Customer binned them")
    assert ret.resulting_lot_id is None
    assert db.query(InventoryItem).filter(InventoryItem.org_id == org.id).count() == before
    assert _qty(db, credited["lot"].id) == Decimal("4")


def test_a_return_without_a_credit_note_makes_a_new_lot(db, org):
    _lot(db, org.id, name="Navy gin 700ml")
    ret = sales_returns.record_return(
        db, org.id, None, condition="resaleable", quantity="2", received_on=TODAY, product_name="Navy gin 700ml"
    )
    db.commit()
    assert ret.credit_note_line_id is None and ret.unit == "each"
    assert db.get(InventoryItem, ret.resulting_lot_id).quantity == Decimal("2.0000")
    with pytest.raises(sales_returns.ReturnError, match="unit"):
        sales_returns.record_return(
            db, org.id, None, condition="resaleable", quantity="1", received_on=TODAY, product_name="Unknown thing"
        )


# --- guards ---------------------------------------------------------------------------------------


def test_never_more_back_than_was_credited(db, org, credited):
    _return(db, org.id, credited, "resaleable", "2")
    with pytest.raises(sales_returns.ReturnError, match="Only 1 more"):
        _return(db, org.id, credited, "resaleable", "2")
    db.rollback()
    assert _qty(db, credited["lot"].id) == Decimal("6")


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"condition": "lost"}, "condition"),
        ({"quantity": "0"}, "how many"),
        ({"quantity": "abc"}, "how many"),
        ({"received_on": TODAY + timedelta(days=3)}, "future"),
        ({"note": "x" * 501}, "under 500"),
    ],
)
def test_bad_input_is_refused(db, org, credited, kwargs, message):
    args = {
        "condition": "resaleable",
        "quantity": "1",
        "received_on": TODAY,
        "credit_note_line_id": credited["line"].id,
    }
    args.update(kwargs)
    with pytest.raises(sales_returns.ReturnError, match=message):
        sales_returns.record_return(db, org.id, None, **args)


def test_a_credit_only_line_cannot_also_have_goods_back(db, org, credited):
    credited["line"].no_return_at = credited["line"].created_at
    credited["line"].no_return_note = "kept by customer"
    db.commit()
    with pytest.raises(sales_returns.ReturnConflictError):
        _return(db, org.id, credited, "resaleable", "1")


# --- routes, pending list, audit --------------------------------------------------------------------


def test_route_records_a_return_and_the_line_leaves_the_pending_list_when_covered(db, org, credited, app_client):
    line_id = str(credited["line"].id)
    pending = app_client.get("/api/crm/returns/pending").get_json()["items"]
    assert [i["line_id"] for i in pending] == [line_id]

    first = app_client.post(
        "/api/crm/returns",
        json={
            "credit_note_line_id": line_id,
            "condition": "resaleable",
            "quantity": "2",
            "received_on": TODAY.isoformat(),
        },
    )
    assert first.status_code == 201, first.get_json()
    assert first.get_json()["return"]["resulting_lot_id"] == str(credited["lot"].id)
    assert [i["line_id"] for i in app_client.get("/api/crm/returns/pending").get_json()["items"]] == [line_id]

    second = app_client.post(
        "/api/crm/returns", json={"credit_note_line_id": line_id, "condition": "damaged", "quantity": "1"}
    )
    assert second.status_code == 201
    assert second.get_json()["return"]["on_hold"] is True
    assert app_client.get("/api/crm/returns/pending").get_json()["items"] == []
    assert (
        app_client.post(
            "/api/crm/returns", json={"credit_note_line_id": line_id, "condition": "resaleable", "quantity": "1"}
        ).status_code
        == 400
    )

    listed = app_client.get("/api/crm/returns").get_json()["returns"]
    assert sorted(r["condition"] for r in listed) == ["damaged", "resaleable"]
    actions = [
        a.action for a in db.query(AuditLog).filter(AuditLog.org_id == org.id, AuditLog.entity == "sales_return")
    ]
    assert actions == ["customer_return_recorded", "customer_return_recorded"]


def test_route_input_errors(app_client, credited):
    assert app_client.post("/api/crm/returns", data="nope", content_type="text/plain").status_code == 400
    assert app_client.post("/api/crm/returns", json={"credit_note_line_id": "x"}).status_code == 404
    assert (
        app_client.post(
            "/api/crm/returns", json={"credit_note_line_id": str(uuid4()), "condition": "resaleable", "quantity": "1"}
        ).status_code
        == 404
    )
    assert (
        app_client.post(
            "/api/crm/returns",
            json={
                "credit_note_line_id": str(credited["line"].id),
                "condition": "resaleable",
                "quantity": "1",
                "received_on": "soon",
            },
        ).status_code
        == 400
    )


def test_another_orgs_credit_line_is_not_found(db, org, credited):
    other = OrganisationFactory()
    db.commit()
    try:
        with pytest.raises(LookupError):
            sales_returns.record_return(
                db,
                other.id,
                None,
                condition="resaleable",
                quantity="1",
                received_on=TODAY,
                credit_note_line_id=credited["line"].id,
            )
    finally:
        db.rollback()
        db.delete(db.merge(other))
        db.commit()


def test_recording_a_return_needs_sales_record():
    from app.core.db.models.user import UserRole
    from app.core.security.access_policy import allows

    class Person:
        def __init__(self, role):
            self.role = role

    assert allows(Person(UserRole.SALES), "crm.crm_api.record_customer_return", "POST")
    assert allows(Person(UserRole.SALES), "crm.crm_api.list_customer_returns", "GET")
    assert not allows(Person(UserRole.AUDITOR), "crm.crm_api.record_customer_return", "POST")
    assert not allows(Person(UserRole.PRODUCTION), "crm.crm_api.list_customer_returns", "GET")


# --- duty ----------------------------------------------------------------------------------------


def test_returns_into_the_licensed_area_are_possible_duty_credits(db, org, credited):
    from app.features.compliant.modules.nz_alcohol import excise

    outside = StockLocation(org_id=org.id, name="Cellar door shop", inside_licensed_area=False)
    db.add(outside)
    db.commit()
    back = _return(db, org.id, credited, "resaleable", "1")  # into the batch, which is in the licensed area
    _return(db, org.id, credited, "destroyed", "1")  # nothing came back: no credit
    standalone = sales_returns.record_return(
        db, org.id, None, condition="resaleable", quantity="5", received_on=TODAY, product_name=PRODUCT
    )
    standalone_lot = db.get(InventoryItem, standalone.resulting_lot_id)
    standalone_lot.location_id = outside.id  # duty-paid shop stock: not a duty matter
    db.commit()

    start = TODAY.replace(day=1)
    end = (start + timedelta(days=32)).replace(day=1)
    locations = {loc.id: loc for loc in db.query(StockLocation).filter(StockLocation.org_id == org.id)}
    rows = excise._customer_returns(db, org.id, start, end, locations)
    assert [(r.kind, r.item.id, r.quantity) for r in rows] == [("returned", back.resulting_lot_id, Decimal("1"))]
    assert rows[0].reference == f"Customer return: {PRODUCT} (resaleable)"
    assert {r.reference for r in excise._removals(db, org.id, start, end) if r.kind == "returned"} >= {
        rows[0].reference
    }
