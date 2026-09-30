"""Real isolated tenants for the source-to-sale acceptance scenarios."""

from datetime import date
from decimal import Decimal
from uuid import UUID, uuid4

import pytest

from app.core.db import db_session
from app.core.db.models.execution_step import ExecutionStep
from app.core.db.models.process import ProcessCategory
from app.core.db.models.user import UserRole
from app.core.db.repositories.execution_repo import ExecutionRepository
from app.core.db.repositories.feature_subscription_repo import FeatureSubscriptionRepository
from app.core.db.repositories.inventory_repo import InventoryRepository
from app.core.db.repositories.process_repo import ProcessRepository
from app.features.compliant.models.alcohol_product_profile import AlcoholProductProfile
from app.features.compliant.models.excise import ExciseRate
from app.features.crm.models.sales_fifo_allocation import SalesFifoAllocation
from app.features.crm.models.xero_invoice import XeroInvoice
from app.features.crm.models.xero_invoice_line_item import XeroInvoiceLineItem
from tests.e2e.conftest import csrf_headers, login_through_ui

PRODUCT = "Scenario gin"
BATCH = "SCENARIO-001"


@pytest.fixture
def alcohol_scenario(browser, app_url, fresh_user):
    user = fresh_user(role=UserRole.ADMIN)
    org_id = UUID(user["org_id"])
    db = db_session()
    FeatureSubscriptionRepository(db).grant(org_id, "compliant")
    repo = InventoryRepository(db)
    processes = ProcessRepository(db)
    executions = ExecutionRepository(db)
    process = processes.create_process(
        org_id, "Scenario bottling", category=ProcessCategory.MANUFACTURING, is_draft=False
    )
    processes.add_step(
        process_id=process.id,
        org_id=org_id,
        step_number=1,
        position=1000,
        name="Bottle",
        inputs=[{"name": "Bulk spirit", "quantity": 35, "unit": "L"}],
        outputs=[{"name": PRODUCT, "quantity": 50, "unit": "bottles"}],
    )
    raw = repo.create_inventory_item(
        org_id, "Bulk spirit", "35", "L", "raw_material", supplier_batch_number="SUPPLIER-001"
    )
    execution = executions.create_execution(org_id, process.id)
    step = db.query(ExecutionStep).filter(ExecutionStep.execution_id == execution.id).one()
    executions.complete_step(
        step.id,
        org_id,
        actual_inputs=[{"name": raw.name, "quantity": 35, "unit": "L", "inventory_item_id": str(raw.id)}],
        actual_outputs=[{"name": PRODUCT, "quantity": 50, "unit": "bottles"}],
    )
    final = repo.create_inventory_item(
        org_id,
        PRODUCT,
        "50",
        "bottles",
        "final_product",
        supplier_batch_number=BATCH,
        source_execution_id=execution.id,
        source_execution_step_id=step.id,
        source_step_name="Bottle",
        extra_data={"abv_percent": "44", "bottling_date": date.today().isoformat()},
    )
    db.add(
        AlcoholProductProfile(
            org_id=org_id,
            inventory_name=PRODUCT,
            product_type="spirits",
            pack_volume_ml=700,
            customs_product_code="2208.50.00",
        )
    )
    db.add(
        ExciseRate(
            org_id=org_id, tariff_item="2208.50.00", rate_per_lal=Decimal("64.10"), effective_from=date(2020, 1, 1)
        )
    )
    db.commit()

    def sell(quantity, invoice_number, contact):
        invoice = XeroInvoice(
            org_id=org_id,
            xero_invoice_id=str(uuid4()),
            xero_tenant_id="scenario",
            contact_id=contact.id,
            invoice_number=invoice_number,
            invoice_type="ACCREC",
            status="AUTHORISED",
            date=date.today(),
        )
        db.add(invoice)
        db.flush()
        db.add(
            XeroInvoiceLineItem(
                org_id=org_id, invoice_id=invoice.id, xero_line_item_id="L1", description=PRODUCT, quantity=quantity
            )
        )
        allocations = repo.consume_final_product_fifo(
            org_id, PRODUCT, str(quantity), reference=invoice_number, commit=False
        )
        for allocation in allocations:
            db.add(
                SalesFifoAllocation(
                    org_id=org_id,
                    xero_invoice_id=invoice.xero_invoice_id,
                    xero_line_key="L1",
                    inventory_item_id=UUID(allocation["inventory_item_id"]),
                    product_name=PRODUCT,
                    quantity=Decimal(allocation["quantity_consumed"]),
                    unit="bottles",
                )
            )
        db.commit()
        return invoice

    context = browser.new_context(base_url=app_url, ignore_https_errors=True)
    page = context.new_page()
    login_through_ui(page, user["email"], user["password"])
    headers = csrf_headers(page)
    response = page.request.put(
        "/api/compliant/profile",
        data={"enabled": True, "settings": {"alcohol_product_types": ["spirits"]}},
        headers=headers,
    )
    assert response.status == 200, response.text()
    try:
        yield {"page": page, "db": db, "org_id": org_id, "raw": raw, "final": final, "sell": sell, "repo": repo}
    finally:
        context.close()
