"""Plan item 1.2: whole bottles, part-fills to Library stock, pack sizes on sales mappings."""

from decimal import Decimal
from uuid import uuid4

import pytest

from app.core.db.models.inventory_item import InventoryItem, InventoryType
from app.core.db.models.organisation import Organisation
from app.core.db.repositories.execution_repo import ExecutionRepository
from app.core.db.repositories.inventory_repo import InventoryRepository
from app.core.db.repositories.process_repo import ProcessRepository
from app.core.utils.unit_conversion import is_count_unit, whole_count_error
from tests.dag_traversal_helpers import clear_org_synthetic_data
from tests.test_compliant_routes import _admin_client, flask_app  # noqa: F401 -- fixture re-export


def test_count_units_include_drinks_packaging():
    for unit in ("bottles", "Bottles", " cans ", "kegs", "cases", "units"):
        assert is_count_unit(unit), unit
    for unit in ("ml", "L", "kg", "g", "", None):
        assert not is_count_unit(unit), unit


@pytest.mark.parametrize(
    ("quantity", "unit", "ok"),
    [
        ("78", "bottles", True),
        ("78.0", "bottles", True),
        ("78.5", "bottles", False),
        ("0.25", "units", False),
        ("350.5", "ml", True),
        ("1.5", "L", True),
    ],
)
def test_whole_count_error(quantity, unit, ok):
    message = whole_count_error(Decimal(quantity), unit, what="Gin")
    assert (message is None) is ok
    if not ok:
        assert "whole numbers" in message and "Gin" in message


@pytest.fixture
def org(db):
    from tests.factories import OrganisationFactory

    o = OrganisationFactory()
    db.commit()
    yield o
    db.rollback()
    clear_org_synthetic_data(db, o.id)
    db.query(Organisation).filter(Organisation.id == o.id).delete(synchronize_session=False)
    db.commit()


def _final_lot(repo, org_id, name, qty, **extra):
    return repo.create_inventory_item(
        org_id=org_id,
        name=name,
        quantity=qty,
        unit="bottles",
        inventory_type=InventoryType.FINAL_PRODUCT.value,
        **extra,
    )


def test_repository_refuses_fractional_counted_writes(db, org):
    repo = InventoryRepository(db)
    with pytest.raises(ValueError, match="whole numbers"):
        _final_lot(repo, org.id, "Gin", "78.5")
    lot = _final_lot(repo, org.id, "Gin", "78")
    with pytest.raises(ValueError, match="whole numbers"):
        repo.add_quantity_to_inventory_item(lot.id, org.id, "0.5")
    with pytest.raises(ValueError, match="whole numbers"):
        repo.set_inventory_item_quantity(lot.id, org.id, "77.5")
    with pytest.raises(ValueError, match="whole numbers"):
        repo.update_inventory_item(lot.id, org.id, quantity="12.25")
    # Measured units are unaffected.
    repo.create_inventory_item(
        org_id=org.id, name="Library", quantity="350.5", unit="ml", inventory_type=InventoryType.FINAL_PRODUCT.value
    )


def test_fifo_never_splits_a_bottle_even_with_an_old_fractional_lot(db, org):
    repo = InventoryRepository(db)
    old = _final_lot(repo, org.id, "Gin", "10")
    # An old lot left holding a fraction (data from before whole-unit rules).
    from app.core.domain.inventory_quantity_guard import InventoryQuantityWriteReason, allow_inventory_quantity_write

    with allow_inventory_quantity_write(InventoryQuantityWriteReason.REPOSITORY_UPDATE):
        db.get(InventoryItem, old.id).quantity = Decimal("2.5")
        db.flush()
    newer = _final_lot(repo, org.id, "Gin", "5")
    db.commit()

    with pytest.raises(ValueError, match="whole numbers"):
        repo.consume_final_product_fifo(org.id, "Gin", "1.5")
    # 2.5 + 5 = 7.5 on hand but only 7 whole bottles.
    with pytest.raises(ValueError, match="Insufficient"):
        repo.consume_final_product_fifo(org.id, "Gin", "8")

    consumed = repo.consume_final_product_fifo(org.id, "Gin", "4")
    taken = {row["inventory_item_id"]: Decimal(row["quantity_consumed"]) for row in consumed}
    assert taken == {str(old.id): Decimal("2"), str(newer.id): Decimal("2")}
    assert all(q == q.to_integral_value() for q in taken.values())
    db.refresh(old)
    assert Decimal(str(old.quantity)) == Decimal("0.5")  # the half waits for a stocktake


def _bottling_workflow(db, org_id, settings=None):
    repo = ProcessRepository(db)
    gin = repo.create_process(org_id=org_id, name=f"Gin {uuid4().hex[:6]}", description="", is_draft=False)
    if settings:
        gin.settings = settings
    repo.add_step(
        process_id=gin.id,
        org_id=org_id,
        step_number=1,
        position=1000,
        name="Bottle",
        inputs=[],
        outputs=[{"name": "Gin - final product", "quantity": "80", "unit": "bottles"}],
        execution_prompts=[],
    )
    db.commit()
    execution = ExecutionRepository(db).create_execution(org_id=org_id, process_id=gin.id)
    db.commit()
    return execution, execution.execution_steps[0]


def test_step_refuses_half_bottles_and_sends_the_part_fill_to_library_stock(db, flask_app):  # noqa: F811
    org, client = _admin_client(db, flask_app)
    try:
        execution, es = _bottling_workflow(db, org.id)
        url = f"/api/core/executions/{execution.id}/steps/{es.id}/complete"

        half = client.post(
            url,
            json={
                "actual_inputs": [],
                "actual_outputs": [{"name": "Gin - final product", "quantity": 78.5, "unit": "bottles"}],
                "execution_data": {},
            },
        )
        assert half.status_code == 400
        assert "whole numbers" in " ".join(half.get_json()["details"])

        ok = client.post(
            url,
            json={
                "actual_inputs": [],
                "actual_outputs": [
                    {"name": "Gin - final product", "quantity": 78, "unit": "bottles", "library_remainder_ml": "350"}
                ],
                "execution_data": {},
            },
        )
        assert ok.status_code == 200, ok.get_json()

        items = {i.name: i for i in db.query(InventoryItem).filter(InventoryItem.org_id == org.id).all()}
        bottles = items["Gin - final product"]
        library = items["Gin - final product - Library stock"]
        assert Decimal(str(bottles.quantity)) == 78 and bottles.unit == "bottles"
        assert Decimal(str(library.quantity)) == 350 and library.unit == "ml"
        assert library.inventory_type == InventoryType.FINAL_PRODUCT.value  # mappable and sellable
        assert library.source_execution_step_id == bottles.source_execution_step_id  # same lineage
        assert library.extra_data["library_stock"] is True
    finally:
        clear_org_synthetic_data(db, org.id)
        db.query(Organisation).filter(Organisation.id == org.id).delete(synchronize_session=False)
        db.commit()


def test_library_stock_name_is_a_workflow_setting(db, flask_app):  # noqa: F811
    org, client = _admin_client(db, flask_app)
    try:
        execution, es = _bottling_workflow(db, org.id, settings={"library_stock_name": "Tasting stock"})
        ok = client.post(
            f"/api/core/executions/{execution.id}/steps/{es.id}/complete",
            json={
                "actual_inputs": [],
                "execution_data": {},
                "actual_outputs": [
                    {"name": "Gin - final product", "quantity": 12, "unit": "bottles", "library_remainder_ml": 90}
                ],
            },
        )
        assert ok.status_code == 200, ok.get_json()
        names = {i.name for i in db.query(InventoryItem).filter(InventoryItem.org_id == org.id).all()}
        assert "Gin - final product - Tasting stock" in names

        bad = client.put(f"/api/core/processes/{execution.process_id}", json={"settings": {"library_stock_name": ""}})
        assert bad.status_code == 400
    finally:
        clear_org_synthetic_data(db, org.id)
        db.query(Organisation).filter(Organisation.id == org.id).delete(synchronize_session=False)
        db.commit()


def test_pack_size_on_a_mapping_multiplies_the_line_quantity(db, flask_app):  # noqa: F811
    from app.features.crm.models.product_mapping import ProductMapping
    from app.features.crm.models.sales_fifo_allocation import SalesFifoAllocation
    from app.features.crm.models.xero_invoice import XeroInvoice
    from app.features.crm.models.xero_invoice_line_item import XeroInvoiceLineItem
    from app.features.crm.services.sales_traceability_service import SalesTraceabilityService

    org, client = _admin_client(db, flask_app)
    try:
        repo = InventoryRepository(db)
        _final_lot(repo, org.id, "Gin - final product", "30")
        created = client.post(
            "/api/crm/product-mappings",
            json={
                "biz_e_product_name": "Gin - final product",
                "xero_description_pattern": "Gin 700ml - Case of 6",
                "match_type": "exact",
                "units_per_line": 6,
            },
        )
        assert created.status_code in (200, 201), created.get_json()
        assert (
            client.post(
                "/api/crm/product-mappings",
                json={
                    "biz_e_product_name": "Gin - final product",
                    "xero_description_pattern": "Gin x1",
                    "units_per_line": 0,
                },
            ).status_code
            == 400
        )

        invoice = XeroInvoice(
            org_id=org.id,
            xero_invoice_id=f"inv-{uuid4()}",
            xero_tenant_id="t",
            invoice_type="ACCREC",
            status="AUTHORISED",
            invoice_number="INV-1",
        )
        db.add(invoice)
        db.flush()
        db.add(
            XeroInvoiceLineItem(
                org_id=org.id,
                invoice_id=invoice.id,
                xero_line_item_id="line-1",
                description="Gin 700ml - Case of 6",
                quantity=Decimal("2"),
            )
        )
        db.commit()

        summary = SalesTraceabilityService(db).reconcile_org(org.id)
        db.commit()
        assert summary.get("allocated") == 1, summary
        allocated = db.query(SalesFifoAllocation).filter(SalesFifoAllocation.org_id == org.id).all()
        assert sum(Decimal(str(a.quantity)) for a in allocated) == 12
        assert db.query(ProductMapping).filter(ProductMapping.org_id == org.id).one().units_per_line == 6
    finally:
        db.rollback()
        for model in (SalesFifoAllocation, XeroInvoiceLineItem, XeroInvoice, ProductMapping):
            db.query(model).filter(model.org_id == org.id).delete(synchronize_session=False)
        db.commit()
        clear_org_synthetic_data(db, org.id)
        db.query(Organisation).filter(Organisation.id == org.id).delete(synchronize_session=False)
        db.commit()
