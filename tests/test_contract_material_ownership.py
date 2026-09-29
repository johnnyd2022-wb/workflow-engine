"""Receipt proof, immutable title, owner conservation and atomic execution writes."""

import re
from dataclasses import dataclass
from datetime import date
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import InternalError

from app.core.db.models.entity_event import EntityEvent
from app.core.db.models.execution_step import ExecutionStep, ExecutionStepStatus
from app.core.db.models.inventory_item import InventoryItem
from app.core.db.models.organisation import Organisation
from app.core.db.models.site_transfer import SiteStockReceipt, SiteStockTransfer
from app.core.db.models.user import UserRole
from app.core.db.repositories.execution_repo import ExecutionRepository
from app.core.db.repositories.inventory_repo import InventoryRepository
from app.core.db.repositories.process_repo import ProcessRepository
from app.core.domain.inventory_quantity_guard import InventoryQuantityWriteReason, allow_inventory_quantity_write
from app.features.contract_manufacturing.models import ContractMaterialReceipt
from app.features.contract_manufacturing.services.materials import MaterialScopeError, validate_execution_materials
from app.features.contract_manufacturing.services.orders import ContractOrderService
from app.features.site_transfers import routes as transfer_routes
from tests.factories import InventoryItemFactory, ProcessFactory, UserFactory
from tests.test_compliant_routes import flask_app  # noqa: F401
from tests.test_contract_orders import _customer, _login, _order, world  # noqa: F401


@pytest.fixture
def owned(world, db):  # noqa: F811
    org_id = world["orgs"][0].id
    assert not world["orgs"][0].contract_materials_enabled
    db.query(Organisation).filter(Organisation.id == org_id).update({"contract_materials_enabled": True})
    db.commit()
    world["customers"] = [
        _customer(world["clients"][0], "Brand A"),
        _customer(world["clients"][0], "Brand B"),
        _customer(world["clients"][1], "Brand C"),
    ]
    yield world
    # Explicit isolated-test purge; production never discards owner evidence.
    db.rollback()
    db.execute(text("SELECT set_config('app.migration_mode','1',true)"))
    ids = [org.id for org in world["orgs"]]
    for org in ids:
        db.execute(
            text(
                "UPDATE inventory_items SET contract_customer_id=NULL, material_receipt_id=NULL, transfer_receipt_id=NULL, supplier_batch_number=NULL WHERE org_id=:org"
            ),
            {"org": org},
        )
        db.execute(text("DELETE FROM inventory_movements WHERE org_id=:org"), {"org": org})
        db.execute(text("DELETE FROM inventory_wastage WHERE org_id=:org"), {"org": org})
        for model in (SiteStockReceipt, SiteStockTransfer, ContractMaterialReceipt):
            db.query(model).filter(model.org_id == org).delete(synchronize_session=False)
    db.commit()


def receipt(owned, index=0, **changes):
    client = owned["clients"][0 if index < 2 else 1]
    body = {
        "name": "Botanicals",
        "quantity": "10",
        "unit": "kg",
        "supplier": "Grower",
        "supplier_batch_number": "BATCH",
        "evidence_reference": "Delivery note 123",
        **changes,
    }
    response = client.post(
        f"/api/core/contract-customers/{owned['customers'][index]['id']}/material-receipts",
        json=body,
        headers={"Idempotency-Key": str(uuid4())},
    )
    assert response.status_code == 201, response.get_json()
    return response.get_json()


def lot(db, owned, value):
    db.expire_all()
    return (
        db.query(InventoryItem)
        .filter(InventoryItem.org_id == owned["orgs"][0].id, InventoryItem.id == UUID(value["inventory_item_id"]))
        .one()
    )


def batch(db, owned, policy="mixed"):
    org_id = owned["orgs"][0].id
    order = _order(
        owned["clients"][0],
        owned["customers"][0]["id"],
        lines=[{"product_name": "Finished", "quantity": "2", "unit": "kg", "materials_source": policy}],
    )
    process = ProcessFactory(org_id=org_id)
    ProcessRepository(db).add_step(
        process.id,
        org_id,
        step_number=1,
        position=1000,
        name="Make",
        inputs=[{"name": "Botanicals", "quantity": 2, "unit": "kg"}],
        outputs=[{"name": "Finished", "quantity": 2, "unit": "kg"}],
    )
    execution = ExecutionRepository(db).create_execution(org_id, process.id)
    ContractOrderService(db, org_id).link_batch(order["id"], order["lines"][0]["id"], execution.id)
    db.commit()
    return execution, execution.execution_steps[0]


def complete(client, execution, step, item, outputs=None):
    return client.post(
        f"/api/core/executions/{execution.id}/steps/{step.id}/complete",
        json={
            "actual_inputs": [{"inventory_item_id": str(item.id), "name": "Botanicals", "quantity": 2, "unit": "kg"}],
            "actual_outputs": outputs if outputs is not None else [{"name": "Finished", "quantity": 2, "unit": "kg"}],
            "allow_consumption_override": True,
        },
    )


def test_distinct_receipts_free_issue_projection_and_idempotency(owned, db):
    first = receipt(owned, barcode="SUPPLIER-UPC")
    second = receipt(owned)
    other = receipt(owned, 1)
    a, b, c = [lot(db, owned, row) for row in (first, second, other)]
    assert len({a.id, b.id, c.id}) == 3
    assert a.contract_customer_id == UUID(owned["customers"][0]["id"])
    assert a.barcode is None and a.extra_data["original_barcode"] == "SUPPLIER-UPC"
    producer = InventoryItemFactory(org_id=a.org_id, name="Producer stock", quantity="4")
    assert [row.id for row in InventoryRepository(db).list_inventory_items(a.org_id, producer_owned_only=True)] == [
        producer.id
    ]
    projection = (
        owned["clients"][0]
        .get(f"/api/core/contract-customers/{a.contract_customer_id}/materials")
        .get_json()["materials"]
    )
    assert len(projection) == 2 and all(
        row["free_issue_acquisition_cost"] == "0" and not row["producer_acquisition_value_included"]
        for row in projection
    )
    key = str(uuid4())
    body = {"name": "Extra", "quantity": "1", "unit": "kg", "evidence_reference": "Docket"}
    path = f"/api/core/contract-customers/{a.contract_customer_id}/material-receipts"
    assert owned["clients"][0].post(path, json=body, headers={"Idempotency-Key": key}).status_code == 201
    replay = owned["clients"][0].post(path, json=body, headers={"Idempotency-Key": key})
    assert replay.status_code == 200 and replay.get_json()["idempotent_replay"]
    assert (
        owned["clients"][0].post(path, json={**body, "quantity": "2"}, headers={"Idempotency-Key": key}).status_code
        == 409
    )


def test_receipt_gate_scope_permissions_and_forged_generic_owner(owned, db):
    client = owned["clients"][0]
    customer = owned["customers"][0]["id"]
    body = {"name": "Botanicals", "quantity": "2", "unit": "kg", "evidence_reference": "Docket"}
    db.query(Organisation).filter(Organisation.id == owned["orgs"][0].id).update({"contract_materials_enabled": False})
    db.commit()
    assert (
        client.post(
            f"/api/core/contract-customers/{customer}/material-receipts",
            json=body,
            headers={"Idempotency-Key": str(uuid4())},
        ).status_code
        == 409
    )
    db.query(Organisation).filter(Organisation.id == owned["orgs"][0].id).update({"contract_materials_enabled": True})
    db.commit()
    assert (
        client.post(
            f"/api/core/contract-customers/{owned['customers'][2]['id']}/material-receipts",
            json=body,
            headers={"Idempotency-Key": str(uuid4())},
        ).status_code
        == 404
    )
    assert client.get(f"/api/core/contract-customers/{owned['customers'][2]['id']}/materials").status_code == 404
    sales = UserFactory(org_id=owned["orgs"][0].id, role=UserRole.SALES, email=f"sales-{uuid4()}@test.com")
    restricted = _login(owned["app"], sales)
    assert restricted.post(f"/api/core/contract-customers/{customer}/material-receipts", json=body).status_code == 403
    assert client.post("/api/core/inventory", json={**body, "contract_customer_id": customer}).status_code == 400
    assert (
        client.post("/api/core/inventory", json={**body, "extra_data": {"contract_customer_id": customer}}).status_code
        == 400
    )


@pytest.mark.parametrize(
    "field,value",
    [("contract_customer_id", None), ("material_receipt_id", None), ("name", "Another product"), ("unit", "litres")],
)
def test_owner_and_identity_immutable_orm_and_database(owned, db, field, value):
    item = lot(db, owned, receipt(owned))
    item_id, org_id = item.id, item.org_id
    setattr(item, field, value)
    with pytest.raises(ValueError):
        db.flush()
    db.rollback()
    statements = {
        "contract_customer_id": "UPDATE inventory_items SET contract_customer_id=NULL WHERE org_id=:org AND id=:id",
        "material_receipt_id": "UPDATE inventory_items SET material_receipt_id=NULL WHERE org_id=:org AND id=:id",
        "name": "UPDATE inventory_items SET name='Another product' WHERE org_id=:org AND id=:id",
        "unit": "UPDATE inventory_items SET unit='litres' WHERE org_id=:org AND id=:id",
    }
    with pytest.raises(InternalError):
        db.execute(text(statements[field]), {"org": org_id, "id": item_id})
    db.rollback()
    assert (
        db.query(InventoryItem)
        .filter(InventoryItem.org_id == org_id, InventoryItem.id == item_id)
        .one()
        .contract_customer_id
        is not None
    )


def test_owned_stock_deposits_manual_debits_and_receipt_edits_closed(owned, db):
    saved = receipt(owned)
    item = lot(db, owned, saved)
    with pytest.raises(MaterialScopeError):
        InventoryRepository(db).add_quantity_to_inventory_item(item.id, item.org_id, "3")
    db.rollback()
    with pytest.raises(MaterialScopeError):
        InventoryRepository(db).set_inventory_item_quantity(item.id, item.org_id, "1")
    db.rollback()
    proof = (
        db.query(ContractMaterialReceipt)
        .filter(ContractMaterialReceipt.org_id == item.org_id, ContractMaterialReceipt.id == UUID(saved["receipt_id"]))
        .one()
    )
    proof.evidence_reference = "Forged"
    with pytest.raises(MaterialScopeError):
        db.flush()
    db.rollback()
    with pytest.raises(InternalError):
        db.execute(
            text("UPDATE contract_material_receipts SET evidence_reference='Forged' WHERE id=:id"),
            {"id": UUID(saved["receipt_id"])},
        )
    db.rollback()
    assert lot(db, owned, saved).quantity == 10


@pytest.mark.parametrize(
    "policy,customer_index,accepted",
    [("customer", 0, True), ("mixed", 0, True), ("producer", 0, False), ("mixed", 1, False)],
)
def test_complete_step_only_consumes_permitted_owner_and_keeps_output_title_separate(
    owned, db, policy, customer_index, accepted
):
    saved = receipt(owned, customer_index)
    item = lot(db, owned, saved)
    execution, step = batch(db, owned, policy)
    result = complete(owned["clients"][0], execution, step, item)
    assert result.status_code == (200 if accepted else 400), result.get_json()
    assert lot(db, owned, saved).quantity == (8 if accepted else 10)
    db.expire_all()
    outputs = (
        db.query(InventoryItem)
        .filter(InventoryItem.org_id == item.org_id, InventoryItem.source_execution_id == execution.id)
        .all()
    )
    assert len(outputs) == int(accepted)
    assert all(row.contract_customer_id is None for row in outputs)


def test_transaction_bound_preflight_cannot_authorize_later_manual_debit(owned, db):
    saved = receipt(owned)
    item = lot(db, owned, saved)
    execution, _ = batch(db, owned)
    validate_execution_materials(db, item.org_id, execution.id, [{"inventory_item_id": str(item.id)}], [])
    db.commit()
    item = lot(db, owned, saved)
    with allow_inventory_quantity_write(InventoryQuantityWriteReason.EXECUTION_STEP_INVENTORY):
        item.quantity = 7
        with pytest.raises(MaterialScopeError):
            db.flush()
    db.rollback()
    assert lot(db, owned, saved).quantity == 10


def test_later_output_failure_rolls_back_inputs_outputs_steps_and_events(owned, db, monkeypatch):
    saved = receipt(owned)
    item = lot(db, owned, saved)
    execution, step = batch(db, owned)
    before = db.query(EntityEvent).filter(EntityEvent.org_id == item.org_id).count()
    original = InventoryRepository.create_inventory_item
    calls = []

    def fail_second(self, *args, **kwargs):
        calls.append(kwargs)
        assert kwargs["commit"] is False
        if len(calls) == 2:
            raise ValueError("Deliberate later deposit failure")
        return original(self, *args, **kwargs)

    monkeypatch.setattr(InventoryRepository, "create_inventory_item", fail_second)
    result = complete(
        owned["clients"][0],
        execution,
        step,
        item,
        [{"name": "Finished", "quantity": 2, "unit": "kg"}, {"name": "Second output", "quantity": 1, "unit": "kg"}],
    )
    assert result.status_code == 500 and len(calls) == 2
    assert lot(db, owned, saved).quantity == 10
    assert (
        db.query(InventoryItem)
        .filter(InventoryItem.org_id == item.org_id, InventoryItem.source_execution_id == execution.id)
        .count()
        == 0
    )
    db.expire_all()
    assert (
        db.query(ExecutionStep).filter(ExecutionStep.org_id == item.org_id, ExecutionStep.id == step.id).one().status
        != ExecutionStepStatus.COMPLETED
    )
    assert db.query(EntityEvent).filter(EntityEvent.org_id == item.org_id).count() == before


@dataclass(frozen=True)
class Decision:
    allowed: bool = True
    reason: str = "Raw ownership conservation test"
    evidence: str = '{"raw_title_only":true}'


def test_transfer_conserves_customer_owner_and_receipt_origin(owned, db, monkeypatch):
    saved = receipt(owned)
    item = lot(db, owned, saved)
    client, org_id = owned["clients"][0], item.org_id
    assert client.put("/api/core/sites/settings", json={"enabled": True}).status_code == 200
    remote = client.post("/api/core/sites", json={"name": "Remote", "kind": "warehouse"}).get_json()
    db.query(Organisation).filter(Organisation.id == org_id).update({"multiple_site_operations_enabled": True})
    db.commit()

    def permit(_db, _org, context):
        assert context.source_snapshot["contract_customer_id"] == str(item.contract_customer_id)
        return Decision()

    monkeypatch.setattr(transfer_routes, "_policy", permit)
    monkeypatch.setattr(transfer_routes, "_requirements", lambda: {"fields": [], "authority_permission": None})
    sent = client.post(
        "/api/core/site-transfers",
        json={
            "source_item_id": str(item.id),
            "destination_site_id": remote["id"],
            "quantity": "6",
            "carrier": "Van",
            "consignment_reference": "Docket",
            "occurred_on": str(date.today()),
        },
        headers={"Idempotency-Key": str(uuid4())},
    )
    assert sent.status_code == 201, sent.get_json()
    transfer = sent.get_json()["transfer"]
    for quantity in ("2", "3"):
        response = client.post(
            f"/api/core/site-transfers/{transfer['id']}/receipts",
            json={"quantity": quantity},
            headers={"Idempotency-Key": str(uuid4())},
        )
        assert response.status_code == 201, response.get_json()
    db.expire_all()
    fragments = (
        db.query(InventoryItem)
        .filter(InventoryItem.org_id == org_id, InventoryItem.transfer_receipt_id.is_not(None))
        .all()
    )
    ledger = (
        db.query(SiteStockTransfer)
        .filter(SiteStockTransfer.org_id == org_id, SiteStockTransfer.id == UUID(transfer["id"]))
        .one()
    )
    assert (
        lot(db, owned, saved).quantity
        + sum(row.quantity for row in fragments)
        + ledger.quantity
        - ledger.received_quantity
        == 10
    )
    assert len(fragments) == 2 and all(
        row.contract_customer_id == item.contract_customer_id
        and row.barcode is None
        and row.material_receipt_id is None
        and row.extra_data["origin_material_receipt_id"] == saved["receipt_id"]
        for row in fragments
    )
    assert all(row.supplier_batch_number == item.supplier_batch_number and row.unit == item.unit for row in fragments)
    # A raw SQL/bulk insert must not turn a customer dispatch into producer title.
    for owner in (None, UUID(owned["customers"][1]["id"])):
        with pytest.raises(InternalError, match="conserve customer title"):
            db.execute(
                text("""INSERT INTO inventory_items
                (id,org_id,name,quantity,unit,inventory_type,transfer_receipt_id,contract_customer_id)
                VALUES (:id,:org,'Botanicals',2,'kg','raw_material',:proof,:owner)"""),
                {"id": uuid4(), "org": org_id, "proof": fragments[0].transfer_receipt_id, "owner": owner},
            )
        db.rollback()
    with pytest.raises(InternalError, match="immutable"):
        db.execute(
            text("UPDATE inventory_items SET transfer_receipt_id=NULL WHERE org_id=:org AND id=:id"),
            {"org": org_id, "id": fragments[0].id},
        )
    db.rollback()
    with pytest.raises(InternalError, match="immutable"):
        db.execute(
            text(
                "UPDATE site_stock_transfers SET source_snapshot=source_snapshot - 'contract_customer_id' WHERE org_id=:org AND id=:id"
            ),
            {"org": org_id, "id": ledger.id},
        )
    db.rollback()


def test_receipt_requires_actual_https_csrf(owned, monkeypatch):
    monkeypatch.setitem(owned["app"].config, "WTF_CSRF_ENABLED", True)
    client = owned["clients"][0]
    path = f"/api/core/contract-customers/{owned['customers'][0]['id']}/material-receipts"
    body = {"name": "Raw", "quantity": "1", "unit": "kg", "evidence_reference": "Docket"}
    assert client.post(path, json=body, headers={"Idempotency-Key": str(uuid4())}).status_code == 400
    page = client.get("/core/contracts/materials")
    token = re.search(r'<meta name="csrf-token" content="([^"]+)"', page.text).group(1)
    result = client.post(
        path,
        json=body,
        headers={
            "Idempotency-Key": str(uuid4()),
            "X-CSRFToken": token,
            "Referer": "https://localhost/core/contracts/materials",
        },
    )
    assert result.status_code == 201, result.get_json()


def test_wrong_later_input_rejects_entire_mixed_consumption(owned, db):
    good = lot(db, owned, receipt(owned))
    foreign = lot(db, owned, receipt(owned, 1))
    execution, step = batch(db, owned)
    inputs = [
        {"inventory_item_id": str(row.id), "name": row.name, "quantity": 2, "unit": "kg"} for row in (good, foreign)
    ]
    response = owned["clients"][0].post(
        f"/api/core/executions/{execution.id}/steps/{step.id}/complete",
        json={"actual_inputs": inputs, "actual_outputs": [], "allow_consumption_override": True},
    )
    assert response.status_code == 400, response.get_json()
    db.expire_all()
    assert db.get(InventoryItem, good.id).quantity == db.get(InventoryItem, foreign.id).quantity == 10
    assert db.get(ExecutionStep, step.id).status != ExecutionStepStatus.COMPLETED


def test_material_gate_off_blocks_existing_customer_consumption(owned, db):
    item = lot(db, owned, receipt(owned))
    execution, step = batch(db, owned)
    db.query(Organisation).filter(Organisation.id == item.org_id).update({"contract_materials_enabled": False})
    db.commit()
    result = complete(owned["clients"][0], execution, step, item)
    assert result.status_code == 400, result.get_json()
    db.expire_all()
    assert db.get(InventoryItem, item.id).quantity == 10


def test_customer_evidence_cannot_be_deleted_or_relabelled_untracked(owned, db):
    item = lot(db, owned, receipt(owned))
    item_id, org_id = item.id, item.org_id
    item.extra_data = {**item.extra_data, "untracked": True}
    with pytest.raises(MaterialScopeError):
        db.flush()
    db.rollback()
    with pytest.raises(InternalError):
        db.execute(text("DELETE FROM inventory_items WHERE org_id=:org AND id=:id"), {"org": org_id, "id": item_id})
    db.rollback()
    with pytest.raises(ValueError, match="ownership-aware"):
        InventoryRepository(db).move_lot(org_id, item_id, "1", uuid4(), date.today())
    db.rollback()
    assert db.get(InventoryItem, item_id).quantity == 10


def test_customer_wastage_requires_recorded_reason_and_conserves_title(owned, db):
    from app.core.db.models.inventory_wastage import InventoryWastage

    item = lot(db, owned, receipt(owned))
    result = owned["clients"][0].post(
        "/api/core/inventory/wastage",
        json={"entries": [{"inventory_item_id": str(item.id), "quantity_wasted": "2", "reason": "Damaged packaging"}]},
    )
    assert result.status_code == 201, result.get_json()
    db.expire_all()
    assert db.get(InventoryItem, item.id).quantity == 8
    proof = (
        db.query(InventoryWastage)
        .filter(InventoryWastage.org_id == item.org_id, InventoryWastage.inventory_item_id == item.id)
        .one()
    )
    assert proof.quantity_wasted == "2.0000" and proof.reason == "Damaged packaging"
    assert db.get(InventoryItem, item.id).contract_customer_id == UUID(owned["customers"][0]["id"])


def test_unresolved_legacy_final_stock_excluded_from_sales_and_reversal(owned, db):
    from app.features.crm.services.crm_service import CRMService
    from app.features.crm.services.sales_traceability_service import SalesTraceabilityService

    org_id = owned["orgs"][0].id
    item = InventoryItemFactory(
        org_id=org_id, name="Legacy finished", inventory_type="final_product", quantity="4", unit="kg"
    )
    # Simulate unresolved historical metadata without permitting new owner hints.
    db.execute(
        text(
            "UPDATE inventory_items SET extra_data=jsonb_build_object('contract_customer_id',:owner) WHERE org_id=:org AND id=:id"
        ),
        {"owner": owned["customers"][0]["id"], "org": org_id, "id": item.id},
    )
    db.commit()
    assert CRMService(db).list_final_products(org_id) == []
    assert SalesTraceabilityService(db).lot_candidates(org_id, item.name) == []
    repo = InventoryRepository(db)
    with pytest.raises(ValueError):
        repo.consume_final_product_fifo(org_id, item.name, "1")
    db.rollback()
    with pytest.raises(ValueError):
        repo.consume_final_product_lot(org_id, item.id, "1")
    db.rollback()
    with pytest.raises(ValueError):
        repo.reverse_final_product_fifo_consumption(org_id, item.id, "1")
    db.rollback()
    assert db.get(InventoryItem, item.id).quantity == 4


def test_reconciliation_debit_rolls_back_when_later_output_fails(owned, db, monkeypatch):
    from decimal import Decimal

    from app.features.reconciliation.service import reconcile_output_to_untracked_reduce_only

    item = lot(db, owned, receipt(owned))
    execution, step = batch(db, owned)
    untracked = InventoryItemFactory(
        org_id=item.org_id,
        name="Finished",
        quantity="1",
        unit="kg",
        extra_data={"untracked": True, "remaining_balance_to_reconcile": "1"},
    )
    db.commit()
    original = InventoryRepository.create_inventory_item
    calls = []

    def later_failure(self, *args, **kwargs):
        calls.append(kwargs)
        if len(calls) == 2:
            raise ValueError("Later output failure after reconciliation")
        return original(self, *args, **kwargs)

    monkeypatch.setattr(InventoryRepository, "create_inventory_item", later_failure)
    result = complete(
        owned["clients"][0],
        execution,
        step,
        item,
        [
            {"name": "Finished", "quantity": 2, "unit": "kg", "untracked_item_id": str(untracked.id)},
            {"name": "Second", "quantity": 1, "unit": "kg"},
        ],
    )
    assert result.status_code == 500 and len(calls) == 2, result.get_json()
    db.expire_all()
    assert db.get(InventoryItem, item.id).quantity == 10
    restored = db.get(InventoryItem, untracked.id)
    assert restored.quantity == 1 and "reconciliation_history" not in restored.extra_data
    assert db.get(ExecutionStep, step.id).status != ExecutionStepStatus.COMPLETED
    assert (
        db.query(InventoryItem)
        .filter(InventoryItem.org_id == item.org_id, InventoryItem.source_execution_id == execution.id)
        .count()
        == 0
    )

    # The helper itself leaves commit authority with its completion caller.
    result = reconcile_output_to_untracked_reduce_only(
        item.org_id, db, None, None, untracked.id, Decimal("1"), "kg", "Finished", execution.id, step.id
    )
    assert result["reconciled_amount"] == "1.0000"
    db.rollback()
    db.expire_all()
    assert db.get(InventoryItem, untracked.id).quantity == 1
