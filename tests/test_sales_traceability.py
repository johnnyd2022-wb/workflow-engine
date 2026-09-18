"""CRM/Xero sales allocation to labelled final-product inventory."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.core.db import db_session
from app.core.db.models.entity_event import EntityEvent
from app.core.db.models.inventory_item import InventoryItem
from app.core.db.models.inventory_movement import InventoryMovement
from app.core.db.models.organisation import Organisation
from app.core.db.repositories.inventory_repo import InventoryRepository
from app.core.db.repositories.organisation_repo import OrganisationRepository
from app.features.crm.models.product_mapping import ProductMapping
from app.features.crm.models.sales_fifo_allocation import SalesFifoAllocation
from app.features.crm.models.sales_traceability_config import SalesTraceabilityConfig
from app.features.crm.models.xero_contact import XeroContact  # noqa: F401 - registers invoice FK target metadata
from app.features.crm.models.xero_invoice import XeroInvoice
from app.features.crm.models.xero_invoice_line_item import XeroInvoiceLineItem
from app.features.crm.services.sales_traceability_service import SalesTraceabilityService


@pytest.fixture
def db():
    session = db_session()
    try:
        yield session
    finally:
        session.close()
        db_session.remove()


@pytest.fixture
def sales_org(db):
    org = OrganisationRepository(db).create_org(f"Sales FIFO Test Org {uuid4()}")
    db.commit()
    yield org

    # The allocation table deliberately protects its referenced inventory batches, so
    # remove the test's durable audit trail before its source rows during teardown.
    db.rollback()
    db.query(SalesFifoAllocation).filter(SalesFifoAllocation.org_id == org.id).delete(synchronize_session=False)
    db.query(InventoryMovement).filter(InventoryMovement.org_id == org.id).delete(synchronize_session=False)
    db.query(EntityEvent).filter(EntityEvent.org_id == org.id).delete(synchronize_session=False)
    db.query(InventoryItem).filter(InventoryItem.org_id == org.id).delete(synchronize_session=False)
    db.query(XeroInvoiceLineItem).filter(XeroInvoiceLineItem.org_id == org.id).delete(synchronize_session=False)
    db.query(XeroInvoice).filter(XeroInvoice.org_id == org.id).delete(synchronize_session=False)
    db.query(ProductMapping).filter(ProductMapping.org_id == org.id).delete(synchronize_session=False)
    db.query(Organisation).filter(Organisation.id == org.id).delete(synchronize_session=False)
    db.commit()


def _add_sale(db, org_id, *, invoice_id: str, description: str, quantity: str, status: str = "AUTHORISED"):
    invoice = XeroInvoice(
        org_id=org_id,
        xero_invoice_id=invoice_id,
        xero_tenant_id="test-tenant",
        invoice_type="ACCREC",
        status=status,
        date=date(2026, 9, 1),
    )
    db.add(invoice)
    db.flush()
    db.add(
        XeroInvoiceLineItem(
            org_id=org_id,
            invoice_id=invoice.id,
            xero_line_item_id=f"{invoice_id}-line-1",
            description=description,
            quantity=Decimal(quantity),
        )
    )
    db.commit()
    return invoice


def _add_mapping(db, org_id, *, product: str, pattern: str, match_type: str = "exact"):
    db.add(
        ProductMapping(
            org_id=org_id,
            biz_e_product_name=product,
            xero_description_pattern=pattern,
            match_type=match_type,
        )
    )
    db.commit()


def _stock_by_batch(db, org_id):
    return {
        item.extra_data["batch_number"]: item.quantity
        for item in db.query(InventoryItem).filter(InventoryItem.org_id == org_id).all()
    }


def test_reconcile_allocates_oldest_batches_idempotently_and_reverses_voided_sale(db, sales_org):
    product = "Wildflower - final product"
    inventory = InventoryRepository(db)
    for batch_number in (1, 2):
        inventory.create_inventory_item(
            sales_org.id,
            name=product,
            quantity="500",
            unit="units",
            inventory_type="final_product",
            extra_data={"batch_number": batch_number},
        )
    _add_mapping(db, sales_org.id, product=product, pattern="Wildflower gin 700ml")
    invoice = _add_sale(
        db,
        sales_org.id,
        invoice_id="xero-sale-1",
        description="Wildflower gin 700ml",
        quantity="600",
    )

    first = SalesTraceabilityService(db).reconcile_org(sales_org.id)
    assert first["allocated"] == 1
    assert _stock_by_batch(db, sales_org.id) == {1: Decimal("0.0000"), 2: Decimal("400.0000")}
    allocations = db.query(SalesFifoAllocation).filter(SalesFifoAllocation.org_id == sales_org.id).all()
    assert sorted(allocation.quantity for allocation in allocations) == [Decimal("100.0000"), Decimal("500.0000")]

    second = SalesTraceabilityService(db).reconcile_org(sales_org.id)
    assert second["already_allocated"] == 1
    assert db.query(SalesFifoAllocation).filter(SalesFifoAllocation.org_id == sales_org.id).count() == 2
    assert _stock_by_batch(db, sales_org.id) == {1: Decimal("0.0000"), 2: Decimal("400.0000")}

    invoice.status = "VOIDED"
    db.commit()
    reversed_summary = SalesTraceabilityService(db).reconcile_org(sales_org.id)
    assert reversed_summary["reversed"] == 2
    assert db.query(SalesFifoAllocation).filter(SalesFifoAllocation.org_id == sales_org.id).count() == 0
    assert _stock_by_batch(db, sales_org.id) == {1: Decimal("500.0000"), 2: Decimal("500.0000")}


def test_reconcile_leaves_unmapped_and_insufficient_sales_unchanged(db, sales_org):
    product = "Solstice - final product"
    InventoryRepository(db).create_inventory_item(
        sales_org.id,
        name=product,
        quantity="100",
        unit="units",
        inventory_type="final_product",
        extra_data={"batch_number": 1},
    )
    _add_mapping(db, sales_org.id, product=product, pattern="Solstice gin 700ml")
    _add_sale(
        db,
        sales_org.id,
        invoice_id="xero-unmapped",
        description="Different product",
        quantity="5",
    )
    _add_sale(
        db,
        sales_org.id,
        invoice_id="xero-short-stock",
        description="Solstice gin 700ml",
        quantity="101",
    )

    summary = SalesTraceabilityService(db).reconcile_org(sales_org.id)
    assert summary["unmapped"] == 1
    assert summary["insufficient_stock"] == 1
    assert _stock_by_batch(db, sales_org.id) == {1: Decimal("100.0000")}
    assert db.query(SalesFifoAllocation).filter(SalesFifoAllocation.org_id == sales_org.id).count() == 0


def test_reconcile_accepts_a_unique_contains_mapping_when_exact_only_is_disabled(db, sales_org):
    product = "Wildflower - final product"
    InventoryRepository(db).create_inventory_item(
        sales_org.id,
        name=product,
        quantity="10",
        unit="units",
        inventory_type="final_product",
        extra_data={"batch_number": 1},
    )
    _add_mapping(db, sales_org.id, product=product, pattern="Wildflower", match_type="contains")
    db.add(SalesTraceabilityConfig(org_id=sales_org.id, matching_strategy="fifo", strict_mapping=False))
    db.commit()
    _add_sale(
        db,
        sales_org.id,
        invoice_id="xero-wildflower-trade",
        description="Whistlebird Gin 44% - Wildflower - 700ml trade (WBWF02)",
        quantity="2",
    )

    summary = SalesTraceabilityService(db).reconcile_org(sales_org.id)
    assert summary["allocated"] == 1
    assert _stock_by_batch(db, sales_org.id) == {1: Decimal("8.0000")}


def test_invoice_sync_returns_fifo_reconciliation_summary(db, sales_org, monkeypatch):
    """The manual Xero sync response must expose allocation work to the operator."""
    from app.features.crm.services.sales_traceability_service import SalesTraceabilityService
    from app.features.crm.services.xero_sync_service import XeroSyncService

    monkeypatch.setattr(
        SalesTraceabilityService,
        "reconcile_org",
        lambda _self, _org_id: {"allocated": 2, "unmapped": 1, "insufficient_stock": 3},
    )
    api = SimpleNamespace(get_all_invoices=lambda **_kwargs: [])

    result = XeroSyncService(db)._sync_invoices(api, sales_org.id, "test-tenant", incremental=True)

    assert result.sales_allocated == 2
    assert result.sales_unmapped == 1
    assert result.sales_insufficient_stock == 3
