"""GL-P08 part 2 in the browser: dispatching a customer-liable contract order from its page,
then recording the customer's receipt from Customs → Transfers."""

from __future__ import annotations

import uuid
from datetime import date

import pytest
from playwright.sync_api import expect

from tests.e2e.conftest import assert_clean_page, attach_probe, login_through_ui

pytestmark = pytest.mark.e2e


@pytest.fixture()
def contract_order(fresh_user):
    from app.core.db import db_session
    from app.core.db.models.inventory_item import InventoryType
    from app.core.db.models.user import UserRole
    from app.core.db.repositories.feature_subscription_repo import FeatureSubscriptionRepository
    from app.core.db.repositories.inventory_repo import InventoryRepository
    from app.features.compliant.models import ComplianceProfile
    from app.features.contract_manufacturing.models import (
        ContractCustomer,
        ContractOrder,
        ContractOrderExecution,
        ContractOrderLine,
    )
    from tests.factories import ExecutionFactory, ProcessFactory

    user = fresh_user(UserRole.ADMIN)
    org_id = uuid.UUID(user["org_id"])
    db = db_session()
    FeatureSubscriptionRepository(db).grant(org_id, "compliant")
    db.add(ComplianceProfile(org_id=org_id, enabled=True, settings={"alcohol_product_types": ["spirits"]}))
    customer = ContractCustomer(org_id=org_id, name="Kererū Botanicals")
    db.add(customer)
    db.flush()
    order = ContractOrder(
        org_id=org_id, customer_id=customer.id, reference="KB-0300", due_date=date.today(), status="confirmed",
        duty_responsibility="customer_licensee", customer_cca_reference="LMA-KB-77",
    )  # fmt: skip
    db.add(order)
    db.flush()
    line = ContractOrderLine(org_id=org_id, order_id=order.id, product_name="Bitters", quantity=240, unit="bottles", materials_source="customer")  # fmt: skip
    db.add(line)
    db.flush()
    batch = ExecutionFactory(org_id=org_id, process_id=ProcessFactory(org_id=org_id).id)
    db.add(ContractOrderExecution(org_id=org_id, order_id=order.id, line_id=line.id, execution_id=batch.id))
    InventoryRepository(db).create_inventory_item(
        org_id=org_id, name="Kawakawa Bitters 200 mL", quantity="240", unit="bottles",
        inventory_type=InventoryType.FINAL_PRODUCT.value, supplier_batch_number="KWB-1", source_execution_id=batch.id,
    )  # fmt: skip
    db.commit()
    return {**user, "order_id": str(order.id)}


def test_dispatch_then_record_the_customers_receipt(browser, app_url, contract_order):
    context = browser.new_context(base_url=app_url, ignore_https_errors=True, viewport={"width": 1440, "height": 900})
    page = context.new_page()
    attach_probe(page)
    login_through_ui(page, contract_order["email"], contract_order["password"])
    page.goto(f"/core/contracts/{contract_order['order_id']}")
    section = page.locator("[data-contract-dispatch]")
    expect(section.locator("[data-dispatch-rule='transfer']")).to_contain_text("LMA-KB-77")
    section.locator("[data-dispatch-lots] input").fill("100")
    section.locator("input[name=carrier]").fill("NZ Couriers")
    section.get_by_role("button", name="Record dispatch").click()
    item = section.locator(".contract-dispatch__item")
    expect(item).to_contain_text("100 bottles Kawakawa Bitters 200 mL")
    expect(item).to_contain_text("Awaiting receipt")
    expect(section.locator("[data-dispatch-lots]")).to_contain_text("140 bottles on hand")

    page.goto("/compliant/nz-alcohol/customs/transfers")
    page.locator("[data-customs-transfers-root][aria-busy='false']").wait_for()
    row = page.locator("[data-tr-row]")
    expect(row).to_contain_text("KB-0300 dispatch")
    row.click()
    receipt = page.locator("[data-tr-receipt-form]")
    receipt.get_by_label("Their acknowledgement").fill("Signed docket KB-77")
    receipt.get_by_role("button", name="Save receipt").click()
    expect(page.locator("[data-tr-row]")).to_have_count(0)  # received: off the to-do list
    page.goto(f"/core/contracts/{contract_order['order_id']}")
    expect(page.locator(".contract-dispatch__item")).to_contain_text("Received")
    assert_clean_page(page)
    context.close()
