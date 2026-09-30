"""Contract duty comes from a locked order, never from the material owner's hint."""

from uuid import uuid4

import pytest

from app.features.compliant.modules.nz_alcohol.movement_excise import prepare_dispatch_duty
from app.features.contract_manufacturing.services.orders import ContractOrderService
from tests.factories import ExecutionFactory, InventoryItemFactory, ProcessFactory
from tests.test_compliant_routes import flask_app  # noqa: F401 -- fixture re-export
from tests.test_contract_orders import _customer, _order, world  # noqa: F401 -- fixture re-export


def test_prepared_duty_follows_confirmed_order_and_fails_closed_for_customer_contract(db, world):  # noqa: F811
    org = world["orgs"][0]
    process = ProcessFactory(org_id=org.id)
    execution = ExecutionFactory(org_id=org.id, process_id=process.id)
    item = InventoryItemFactory(org_id=org.id, source_execution_id=execution.id)
    db.commit()

    plain = prepare_dispatch_duty(db, org.id, item.id)
    assert plain["duty_responsibility"] == "producer_licensee"
    assert plain["contract_order_id"] is None
    assert prepare_dispatch_duty(db, world["orgs"][1].id, item.id)["found"] is False

    customer = _customer(world["clients"][0])
    order = _order(
        world["clients"][0],
        customer["id"],
        duty_responsibility="customer_licensee",
        customer_cca_reference="Customer CCA authorisation DOC-17",
    )
    service = ContractOrderService(db, org.id)
    service.link_batch(order["id"], order["lines"][0]["id"], execution.id)
    linked = prepare_dispatch_duty(db, org.id, item.id)
    assert linked["contract_order_id"] == order["id"]
    assert linked["duty_responsibility"] == "customer_licensee"
    assert linked["customer_cca_reference"] == "Customer CCA authorisation DOC-17"

    service.update_order(order["id"], {"status": "cancelled"})
    with pytest.raises(ValueError, match="confirmed order"):
        prepare_dispatch_duty(db, org.id, item.id)
    assert prepare_dispatch_duty(db, org.id, uuid4())["found"] is False
