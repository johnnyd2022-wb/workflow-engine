"""Real PostgreSQL dispatch/receipt conservation and transaction boundaries."""

from dataclasses import dataclass
from datetime import date
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, OperationalError

from app.core.db import SessionLocal
from app.core.db.models.inventory_item import InventoryItem
from app.core.db.models.inventory_movement import InventoryMovement
from app.core.db.models.organisation import Organisation
from app.core.db.models.site_transfer import SiteStockReceipt, SiteStockTransfer
from app.core.db.models.user import User, UserRole
from app.core.db.repositories.inventory_repo import InventoryRepository
from app.core.db.site_guard import SiteScopeError
from app.core.db.site_operations import resolve_site
from app.core.db.transfer_guard import allow_transfer_accounting
from app.core.security.tenant_scope import unscoped
from app.features.site_transfers import routes, service
from app.features.sites.service import configure
from tests.factories import InventoryItemFactory
from tests.test_site_operations import released  # noqa: F401
from tests.test_sites import flask_app, world  # noqa: F401


@dataclass(frozen=True)
class Decision:
    allowed: bool = True
    reason: str = "Test decision"
    evidence: str = '{"test_policy":"producer"}'


def permit(_session, _org_id, context):
    assert context.source_snapshot["contract_customer_id"] is None
    with pytest.raises(TypeError):
        context.source_snapshot["name"] = "Forged"
    return Decision()


@pytest.fixture
def transfers(released, db, monkeypatch):  # noqa: F811
    monkeypatch.setattr(routes, "_policy", permit)
    monkeypatch.setattr(routes, "_requirements", lambda: {"fields": [], "authority_permission": None})
    org, admin, other, neighbour, default, additional = released
    with unscoped():
        stock = InventoryItemFactory(
            org_id=org.id,
            name="House Gin",
            quantity="20",
            unit="bottles",
            inventory_type="final_product",
            barcode="TRANSFER-" + str(uuid4()),
            supplier_batch_number="ORIGINAL-BATCH",
        )
        actor = db.query(User).filter(User.org_id == org.id, User.role == UserRole.ADMIN).one()
        actor_id, stock_id = actor.id, stock.id
    yield org, admin, other, neighbour, default, additional, stock_id, actor_id
    db.rollback()
    with unscoped():
        # Test-only evidence purge; production receipt proof is immutable.
        db.execute(text("SELECT set_config('app.migration_mode','1',true)"))
        db.query(InventoryMovement).filter(InventoryMovement.org_id == org.id).delete(synchronize_session=False)
        db.execute(
            text(
                "UPDATE inventory_items SET supplier_batch_number = CASE WHEN transfer_receipt_id IS NOT NULL THEN NULL ELSE supplier_batch_number END, transfer_receipt_id = NULL WHERE org_id = :org"
            ),
            {"org": org.id},
        )
        db.query(SiteStockReceipt).filter(SiteStockReceipt.org_id == org.id).delete(synchronize_session=False)
        db.query(SiteStockTransfer).filter(SiteStockTransfer.org_id == org.id).delete(synchronize_session=False)
        from app.features.compliant.models.alcohol_product_profile import AlcoholProductProfile
        from app.features.compliant.models.compliance_profile import ComplianceProfile
        from app.features.compliant.models.customs_premises import CustomsCoverage, CustomsLicence

        for model in (CustomsCoverage, CustomsLicence, AlcoholProductProfile, ComplianceProfile):
            db.query(model).filter(model.org_id == org.id).delete(synchronize_session=False)
        db.commit()


def payload(fixture, **changes):
    return {
        "source_item_id": str(fixture[6]),
        "destination_site_id": fixture[5]["id"],
        "quantity": "10",
        "carrier": "Courier",
        "consignment_reference": "DOCKET-123",
        "occurred_on": date.today().isoformat(),
        **changes,
    }


def post(client, path, data, key=None):
    return client.post(path, json=data, headers={"Idempotency-Key": key or str(uuid4())})


def start(fixture, **changes):
    response = post(fixture[1], "/api/core/site-transfers", payload(fixture, **changes))
    assert response.status_code == 201, response.get_json()
    return response.get_json()["transfer"]


def test_partial_receipt_exact_conservation_and_fifo(transfers, db):
    org, admin, _, _, _, additional, stock_id, _ = transfers
    transfer = start(transfers)
    with unscoped():
        db.expire_all()
        assert db.get(InventoryItem, stock_id).quantity == 10
        assert db.query(InventoryItem).filter(InventoryItem.org_id == org.id).count() == 1
        # Transit is not a candidate for either shipping site's FIFO.
        with pytest.raises(ValueError, match="Insufficient stock"):
            InventoryRepository(db).consume_final_product_fifo(org.id, "House Gin", "1", site_id=UUID(additional["id"]))
        db.rollback()
    with unscoped():
        service.receive(db, org.id, transfers[7], transfer["id"], str(uuid4()), {"quantity": "4"}, permit)
        db.commit()
    with unscoped():
        db.expire_all()
        original = db.get(InventoryItem, stock_id)
        fragment = (
            db.query(InventoryItem)
            .filter(InventoryItem.org_id == org.id, InventoryItem.transfer_receipt_id.is_not(None))
            .one()
        )
        ledger = db.get(SiteStockTransfer, UUID(transfer["id"]))
        assert (
            original.quantity + fragment.quantity + ledger.quantity - ledger.received_quantity - ledger.loss_quantity
            == 20
        )
        assert fragment.quantity == 4 and fragment.site_id == UUID(additional["id"])
        assert fragment.barcode is None and fragment.extra_data["original_barcode"] == original.barcode
        assert fragment.supplier_batch_number == original.supplier_batch_number
        assert InventoryRepository(db).consume_final_product_lot(org.id, fragment.id, "1", site_id=fragment.site_id)[
            "inventory_item_id"
        ] == str(fragment.id)
        db.rollback()
    assert admin.get(f"/core/site-transfers/{transfer['id']}/docket").status_code == 200
    assert (
        admin.get(f"/api/core/site-transfers/{transfer['id']}").get_json()["transfer"]["transit_quantity"] == "6.0000"
    )


def test_idempotent_dispatch_receipt_and_conflicting_payload(transfers, db):
    admin = transfers[1]
    key = str(uuid4())
    response = post(admin, "/api/core/site-transfers", payload(transfers), key)
    transfer = response.get_json()["transfer"]
    assert post(admin, "/api/core/site-transfers", payload(transfers), key).get_json()["idempotent_replay"]
    assert post(admin, "/api/core/site-transfers", payload(transfers, quantity="9"), key).status_code == 400
    path = f"/api/core/site-transfers/{transfer['id']}/receipts"
    key = str(uuid4())
    assert post(admin, path, {"quantity": "3"}, key).status_code == 201
    assert post(admin, path, {"quantity": "3"}, key).get_json()["idempotent_replay"]
    assert post(admin, path, {"quantity": "4"}, key).status_code == 400
    with unscoped():
        db.expire_all()
        assert db.get(InventoryItem, transfers[6]).quantity == 10
        assert db.query(SiteStockReceipt).filter(SiteStockReceipt.org_id == transfers[0].id).count() == 1


def test_pending_loss_overage_and_policy_denial_are_atomic(transfers, db, monkeypatch):
    transfer = start(transfers)
    path = f"/api/core/site-transfers/{transfer['id']}/receipts"
    for data in (
        {"quantity": "11"},
        {"short_quantity": "2"},
        {"short_quantity": "2", "confirm_loss": True},
        {"quantity": "2", "approval": {"authority": "forged"}},
    ):
        assert post(transfers[1], path, data).status_code == 400
    monkeypatch.setattr(routes, "_policy", lambda *_: Decision(False, "Loss accounting pending"))
    assert (
        post(
            transfers[1],
            path,
            {"quantity": "4", "short_quantity": "2", "confirm_loss": True, "loss_reason": "Seal broken"},
        ).status_code
        == 400
    )
    with unscoped():
        db.expire_all()
        ledger = db.get(SiteStockTransfer, UUID(transfer["id"]))
        assert ledger.received_quantity == ledger.loss_quantity == 0
        assert db.query(SiteStockReceipt).filter(SiteStockReceipt.org_id == transfers[0].id).count() == 0
    monkeypatch.setattr(routes, "_policy", permit)
    assert (
        post(
            transfers[1],
            path,
            {
                "quantity": "4",
                "damaged_quantity": "1",
                "short_quantity": "2",
                "confirm_loss": True,
                "loss_reason": "Seal broken",
            },
        ).status_code
        == 201
    )
    result = transfers[1].get(f"/api/core/site-transfers/{transfer['id']}").get_json()
    assert result["transfer"]["confirmed_loss_quantity"] == "3.0000"
    assert result["transfer"]["transit_quantity"] == "3.0000"
    assert result["receipts"][0]["loss_reason"] == "Seal broken"


@pytest.mark.parametrize("quantity", ["NaN", "Infinity", "-1", "0", "1.5", "1.00001", "100000000000000"])
def test_invalid_count_dispatch_keeps_stock(transfers, db, quantity):
    assert post(transfers[1], "/api/core/site-transfers", payload(transfers, quantity=quantity)).status_code == 400
    with unscoped():
        db.expire_all()
        assert db.get(InventoryItem, transfers[6]).quantity == 20


def test_tenant_tags_gate_and_unknown_fields(transfers, db):
    org, admin, _, neighbour, _, _, stock_id, _ = transfers
    foreign = neighbour.put("/api/core/sites/settings", json={"enabled": True}).get_json()["sites"][0]
    for change in (
        {"destination_site_id": foreign["id"]},
        {"source_item_id": str(uuid4())},
        {"org_id": str(org.id)},
        {"destination_location_id": str(uuid4())},
    ):
        assert post(admin, "/api/core/site-transfers", payload(transfers, **change)).status_code == 400
    transfer = start(transfers)
    assert neighbour.get(f"/api/core/site-transfers/{transfer['id']}").status_code == 404
    assert post(neighbour, f"/api/core/site-transfers/{transfer['id']}/receipts", {"quantity": "1"}).status_code == 404
    with unscoped():
        db.get(Organisation, org.id).multiple_site_operations_enabled = False
        db.commit()
    assert post(admin, "/api/core/site-transfers", payload(transfers)).status_code == 400
    assert admin.get("/api/core/site-transfers").get_json()["operations_available"] is False
    with unscoped():
        db.expire_all()
        assert db.get(InventoryItem, stock_id).quantity == 10


def test_receipt_fragment_proof_and_ledger_immutability(transfers, db):
    transfer = start(transfers)
    assert (
        post(transfers[1], f"/api/core/site-transfers/{transfer['id']}/receipts", {"quantity": "2"}).status_code == 201
    )
    with unscoped():
        fragment = (
            db.query(InventoryItem)
            .filter(InventoryItem.org_id == transfers[0].id, InventoryItem.transfer_receipt_id.is_not(None))
            .one()
        )
        for attr, value in (
            ("unit", "kg"),
            ("supplier_batch_number", "SWAPPED"),
            ("barcode", "COPIED"),
            ("transfer_receipt_id", None),
            ("site_id", UUID(transfers[4]["id"])),
        ):
            setattr(fragment, attr, value)
            with pytest.raises(SiteScopeError):
                db.flush()
            db.rollback()
        ledger = db.get(SiteStockTransfer, UUID(transfer["id"]))
        ledger.carrier = "Changed"
        with allow_transfer_accounting(), pytest.raises(ValueError, match="immutable"):
            db.flush()
        db.rollback()


def test_receipt_rolls_back_if_fragment_creation_fails(transfers, db, monkeypatch):
    transfer = start(transfers)

    def fail(*_args, **_kwargs):
        raise ValueError("Creation failed")

    monkeypatch.setattr(InventoryRepository, "create_inventory_item", fail)
    assert (
        post(transfers[1], f"/api/core/site-transfers/{transfer['id']}/receipts", {"quantity": "4"}).status_code == 400
    )
    with unscoped():
        db.expire_all()
        assert db.get(SiteStockTransfer, UUID(transfer["id"])).received_quantity == 0
        assert db.query(SiteStockReceipt).filter(SiteStockReceipt.org_id == transfers[0].id).count() == 0


def test_concurrent_receipts_lock_remaining_budget(transfers, db):
    org, _, _, _, _, _, _, actor = transfers
    transfer = start(transfers)
    with SessionLocal() as first, SessionLocal() as second, unscoped():
        service.receive(first, org.id, actor, transfer["id"], str(uuid4()), {"quantity": "7"}, permit)
        second.execute(text("SET LOCAL statement_timeout = '400ms'"))
        with pytest.raises(OperationalError) as blocked:
            service.receive(second, org.id, actor, transfer["id"], str(uuid4()), {"quantity": "7"}, permit)
        assert blocked.value.orig.pgcode == "57014"
        second.rollback()
        first.commit()
        with pytest.raises(ValueError, match="remaining transit"):
            service.receive(second, org.id, actor, transfer["id"], str(uuid4()), {"quantity": "7"}, permit)
        second.rollback()
        service.receive(second, org.id, actor, transfer["id"], str(uuid4()), {"quantity": "3"}, permit)
        second.commit()
    with unscoped():
        db.expire_all()
        assert db.get(SiteStockTransfer, UUID(transfer["id"])).received_quantity == 10


def test_shipping_off_mode_holds_flags_until_commit(world, db):  # noqa: F811
    org, admin, _, _ = world
    with SessionLocal() as shipping, SessionLocal() as settings, unscoped():
        assert resolve_site(shipping, org.id) is None
        settings.execute(text("SET LOCAL statement_timeout = '400ms'"))
        with pytest.raises(OperationalError) as blocked:
            configure(settings, org.id, True)
        assert blocked.value.orig.pgcode == "57014"
        settings.rollback()
        shipping.commit()
        configure(settings, org.id, True)
        settings.commit()
        assert resolve_site(shipping, org.id) is not None
        shipping.rollback()


def test_receipt_fk_and_settings_do_not_deadlock(transfers):
    org, _, _, _, _, _, _, actor = transfers
    transfer = start(transfers)
    with SessionLocal() as receipt, SessionLocal() as settings, unscoped():
        # Flushing the fragment obtains tenant FK KEY SHARE, compatible with the
        # transaction's SHARE mode lock; settings waits on NO KEY UPDATE.
        service.receive(receipt, org.id, actor, transfer["id"], str(uuid4()), {"quantity": "1"}, permit)
        settings.execute(text("SET LOCAL statement_timeout = '400ms'"))
        with pytest.raises(OperationalError) as blocked:
            configure(settings, org.id, False)
        assert blocked.value.orig.pgcode == "57014"
        settings.rollback()
        receipt.commit()
        with pytest.raises(SiteScopeError):
            configure(settings, org.id, False)
        settings.rollback()


def test_ordinary_batch_dedup_and_independent_receipt_identity(transfers, db):
    org, admin, _, _, _, additional, stock_id, _ = transfers
    with unscoped():
        with pytest.raises(IntegrityError):
            InventoryItemFactory(
                org_id=org.id, name="House Gin", quantity="3", unit="bottles", supplier_batch_number="ORIGINAL-BATCH"
            )
        db.rollback()
        remote = InventoryItemFactory(
            org_id=org.id,
            name="House Gin",
            quantity="3",
            unit="bottles",
            supplier_batch_number="ORIGINAL-BATCH",
            site_id=UUID(additional["id"]),
        )
        assert remote.id != stock_id
    transfer = start(transfers)
    path = f"/api/core/site-transfers/{transfer['id']}/receipts"
    assert post(admin, path, {"quantity": "2"}).status_code == 201
    assert post(admin, path, {"quantity": "3"}).status_code == 201
    with unscoped():
        fragments = (
            db.query(InventoryItem)
            .filter(InventoryItem.org_id == org.id, InventoryItem.transfer_receipt_id.is_not(None))
            .all()
        )
        assert len(fragments) == 2 and sum(row.quantity for row in fragments) == 5
        assert remote.quantity == 3


def test_lineage_survives_transfer_and_cannot_be_retagged(transfers, db):
    from app.core.db.repositories.execution_repo import ExecutionRepository
    from tests.factories import ProcessFactory

    org, admin, _, _, _, _, stock_id, _ = transfers
    with unscoped():
        process = ProcessFactory(org_id=org.id)
        execution = ExecutionRepository(db).create_execution(org.id, process.id)
        stock = db.get(InventoryItem, stock_id)
        stock.source_execution_id = execution.id
        stock.source_step_name = "Bottling"
        db.commit()
    transfer = start(transfers)
    assert post(admin, f"/api/core/site-transfers/{transfer['id']}/receipts", {"quantity": "2"}).status_code == 201
    with unscoped():
        db.expire_all()
        fragment = (
            db.query(InventoryItem)
            .filter(InventoryItem.org_id == org.id, InventoryItem.transfer_receipt_id.is_not(None))
            .one()
        )
        assert fragment.source_execution_id == execution.id and fragment.source_step_name == "Bottling"
        assert fragment.site_id != execution.site_id
        fragment.source_execution_id = None
        with pytest.raises(SiteScopeError):
            db.flush()
        db.rollback()


def test_configured_module_dispatch_and_inventory_staff_receipt(transfers, db, monkeypatch):
    from app.core.db.models.site import Site
    from app.features.compliant.models.alcohol_product_profile import AlcoholProductProfile
    from app.features.compliant.models.compliance_profile import ComplianceProfile
    from app.features.compliant.modules.nz_alcohol import premises
    from app.features.compliant.platform.stock_movements import evaluate_stock_movement, movement_requirements
    from tests.factories import DEFAULT_TEST_PASSWORD, UserFactory
    from tests.test_customs_premises import coverage_data, licence_data

    org, admin, _, _, default, additional, _, _ = transfers
    monkeypatch.setattr(routes, "_policy", evaluate_stock_movement)
    monkeypatch.setattr(routes, "_requirements", lambda: movement_requirements(db, org.id))
    with unscoped():
        db.add(ComplianceProfile(org_id=org.id, enabled=True, industry_module="nz_alcohol"))
        db.add(AlcoholProductProfile(org_id=org.id, inventory_name="House Gin", product_type="spirits"))
        for index, site in enumerate((default, additional)):
            licence = premises.add_licence(db, org.id, licence_data(number=f"CCA-{index}"))
            premises.add_coverage(db, org.id, coverage_data(licence, db.get(Site, UUID(site["id"]))))
        staff = UserFactory(org_id=org.id, email=f"receiver-{uuid4()}@test.com", role=UserRole.PRODUCTION)
        db.commit()
    client = admin.application.test_client()
    client.environ_base.update({"wsgi.url_scheme": "https", "HTTP_X_FORWARDED_PROTO": "https"})
    assert client.post("/auth/login", json={"email": staff.email, "password": DEFAULT_TEST_PASSWORD}).status_code == 200
    approval = {"authority": "same_legal_entity", "evidence_reference": "Same registered entity"}
    assert post(client, "/api/core/site-transfers", payload(transfers, approval=approval)).status_code == 400
    assert client.get("/api/core/site-transfers/options").get_json()["requirements"]["can_authorise"] is False
    transfer = start(transfers, approval=approval)
    path = f"/api/core/site-transfers/{transfer['id']}/receipts"
    assert post(client, path, {"quantity": "3", "approval": {"authority": "changed"}}).status_code == 400
    result = post(client, path, {"quantity": "3"})
    assert result.status_code == 201, result.get_json()
    # Current NZ provider keeps unaccounted losses closed even to authorised staff.
    assert (
        post(client, path, {"short_quantity": "1", "confirm_loss": True, "loss_reason": "Missing"}).status_code == 400
    )


def test_concurrent_dispatch_idempotency_and_source_budget(transfers):
    org, _, _, _, _, _, stock_id, actor = transfers
    details, key = payload(transfers, quantity="15"), str(uuid4())
    with SessionLocal() as first, SessionLocal() as second, unscoped():
        original, replay = service.dispatch(first, org.id, actor, key, details, permit)
        assert not replay
        second.execute(text("SET LOCAL statement_timeout = '400ms'"))
        with pytest.raises(OperationalError) as blocked:
            service.dispatch(second, org.id, actor, key, details, permit)
        assert blocked.value.orig.pgcode == "57014"
        second.rollback()
        first.commit()
        again, replay = service.dispatch(second, org.id, actor, key, details, permit)
        assert replay and again.id == original.id
        assert second.get(InventoryItem, stock_id).quantity == 5
        second.rollback()
        with pytest.raises(ValueError, match="available shelf stock"):
            service.dispatch(second, org.id, actor, str(uuid4()), payload(transfers, quantity="6"), permit)
        second.rollback()


def test_legacy_move_cannot_cross_site_or_merge_incompatible_lots(transfers, db):
    from app.core.db.models.stock_location import StockLocation

    org, _, _, _, _, additional, stock_id, _ = transfers
    with unscoped():
        location = StockLocation(org_id=org.id, name="Remote place", site_id=UUID(additional["id"]))
        db.add(location)
        db.commit()
        with pytest.raises(ValueError, match="between sites"):
            InventoryRepository(db).move_lot(org.id, stock_id, "2", location.id, date.today())
        db.rollback()
        assert db.get(InventoryItem, stock_id).quantity == 20


def test_transfer_owned_metadata_is_closed(transfers, db):
    with unscoped():
        stock = db.get(InventoryItem, transfers[6])
        # Historical metadata is not a supported new ownership write. Simulate an
        # already stored legacy hint without using the now-closed ORM/API path.
        db.execute(
            text(
                "UPDATE inventory_items SET extra_data = jsonb_build_object('contract_customer_id', :owner) WHERE org_id=:org AND id=:id"
            ),
            {"owner": str(uuid4()), "org": stock.org_id, "id": stock.id},
        )
        db.commit()
    result = post(transfers[1], "/api/core/site-transfers", payload(transfers))
    assert result.status_code == 400 and "Legacy customer ownership" in result.get_json()["error"]
    options = transfers[1].get("/api/core/site-transfers/options").get_json()
    assert not options["stock"]


def test_legacy_incompatible_identity_is_rejected_before_debit(transfers, db):
    from app.core.db.models.stock_location import StockLocation

    org, _, _, _, default, _, stock_id, _ = transfers
    with unscoped():
        db.get(Organisation, org.id).multiple_site_operations_enabled = False
        location = StockLocation(org_id=org.id, name="Default tank", site_id=UUID(default["id"]))
        db.add(location)
        db.commit()
        incompatible = InventoryItemFactory(
            org_id=org.id,
            name="House Gin",
            quantity="5",
            unit="kg",
            location_id=location.id,
            supplier_batch_number="ORIGINAL-BATCH",
        )
        with pytest.raises(ValueError, match="different lot identity"):
            InventoryRepository(db).move_lot(org.id, stock_id, "2", location.id, date.today())
        assert db.get(InventoryItem, stock_id).quantity == 20
        assert incompatible.quantity == 5
        db.rollback()
