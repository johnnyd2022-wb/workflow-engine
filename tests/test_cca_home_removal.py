"""A real dispatch freezes producer-liable CCA removal once; receipt does not tax it again."""

from datetime import date, timedelta
from decimal import Decimal
from types import SimpleNamespace
from uuid import UUID, uuid4

from app.core.db.models.inventory_item import InventoryItem
from app.core.db.models.site_transfer import SiteStockTransfer
from app.core.security.tenant_scope import unscoped
from app.features.compliant.models.alcohol_product_profile import AlcoholProductProfile
from app.features.compliant.models.compliance_profile import ComplianceProfile
from app.features.compliant.models.excise import ExciseRate
from app.features.compliant.modules.nz_alcohol import premises
from app.features.compliant.modules.nz_alcohol.movement_excise import cca_movement_register
from app.features.compliant.platform.stock_movements import evaluate_stock_movement
from app.features.site_transfers import routes
from tests.test_customs_premises import coverage_data, licence_data
from tests.test_site_operations import released  # noqa: F401 -- fixture re-export
from tests.test_site_transfers import payload, post, transfers  # noqa: F401 -- fixture re-export
from tests.test_sites import flask_app, world  # noqa: F401 -- fixture re-export


def _configure(db, fixture):
    org, _, _, _, default, _, _, _ = fixture
    db.add(ComplianceProfile(org_id=org.id, enabled=True, industry_module="nz_alcohol"))
    db.add(
        AlcoholProductProfile(
            org_id=org.id,
            inventory_name="House Gin",
            product_type="spirits",
            pack_volume_ml=Decimal("700"),
            customs_product_code="TEST-SPIRITS-LAL",
        )
    )
    db.add(
        ExciseRate(
            org_id=org.id,
            tariff_item="TEST-SPIRITS-LAL",
            rate_per_lal=Decimal("42.50"),
            effective_from=date(2026, 7, 1),
        )
    )
    licence = premises.add_licence(db, org.id, licence_data())
    premises.add_coverage(db, org.id, coverage_data(licence, SimpleNamespace(id=UUID(default["id"]))))
    db.commit()
    return licence


def _approval(**changes):
    return {
        "authority": "home_consumption",
        "destination_activity": "selling",
        "evidence_reference": "Producer CCA removal record",
        "measured_abv_percent": "45",
        "measurement_method": "hydrometric",
        "measured_on": date.today().isoformat(),
        "measurement_reference": "Signed hydrometer report",
        "volume_reference": "700 mL pack record",
        **changes,
    }


def test_home_removal_is_one_frozen_dispatch_fact_and_partial_receipt_is_not_a_second_charge(
    transfers, db, monkeypatch  # noqa: F811 -- imported fixture
):
    org, admin, _, _, _, _, item_id, _ = transfers
    licence = _configure(db, transfers)
    monkeypatch.setattr(routes, "_policy", evaluate_stock_movement)
    monkeypatch.setattr(routes, "_requirements", lambda: {"fields": [], "authority_permission": None})
    try:
        response = post(admin, "/api/core/site-transfers", payload(transfers, approval=_approval()), str(uuid4()))
        assert response.status_code == 201, response.get_json()
        transfer_id = response.json["transfer"]["id"]
        with unscoped():
            transfer = db.get(SiteStockTransfer, UUID(transfer_id))
            assert transfer.decision_snapshot["tax_status"] == "home_consumption_excise_due"
            assert transfer.decision_snapshot["source_licence"]["id"] == str(licence.id)
            assert transfer.decision_snapshot["duty_responsibility"] == "producer_licensee"
            basis = transfer.decision_snapshot["removal_basis"]
            assert basis["source_cca"]["id"] == str(licence.id)
            assert Decimal(basis["lal"]) == Decimal("3.15")
            assert Decimal(basis["excise_duty_only"]) == Decimal("133.88")
            assert db.get(InventoryItem, item_id).quantity == 10
        receipt = post(admin, f"/api/core/site-transfers/{transfer_id}/receipts", {"quantity": "4"})
        assert receipt.status_code == 201, receipt.get_json()
        with unscoped():
            db.expire_all()
            transfer = db.get(SiteStockTransfer, UUID(transfer_id))
            assert transfer.received_quantity == 4
            assert transfer.decision_snapshot["removal_basis"] == basis
            assert db.get(InventoryItem, item_id).quantity == 10
            register = cca_movement_register(db, org.id, date.today(), date.today() + timedelta(days=1))
            (group,) = register["licences"]
            assert len(group["movements"]) == 1
            assert group["movements"][0]["treatment"] == "recorded_producer_home_consumption"
            assert Decimal(group["observed_excise_duty"]) == Decimal("133.88")
            assert register["total_duty"] is None and register["nil_return"] is None
    finally:
        with unscoped():
            db.query(ExciseRate).filter(ExciseRate.org_id == org.id).delete(synchronize_session=False)
            db.commit()


def test_unverified_home_removal_cannot_debit_stock(transfers, db, monkeypatch):  # noqa: F811 -- imported fixture
    org, admin, _, _, _, _, item_id, _ = transfers
    _configure(db, transfers)
    monkeypatch.setattr(routes, "_policy", evaluate_stock_movement)
    monkeypatch.setattr(routes, "_requirements", lambda: {"fields": [], "authority_permission": None})
    try:
        for approval in (
            _approval(measured_abv_percent="NaN"),
            _approval(measurement_reference=""),
            _approval(authority="same_legal_entity"),
        ):
            response = post(admin, "/api/core/site-transfers", payload(transfers, approval=approval))
            assert response.status_code == 400
        with unscoped():
            db.expire_all()
            assert db.get(InventoryItem, item_id).quantity == 20
            assert db.query(SiteStockTransfer).filter(SiteStockTransfer.org_id == org.id).count() == 0
    finally:
        with unscoped():
            db.query(ExciseRate).filter(ExciseRate.org_id == org.id).delete(synchronize_session=False)
            db.commit()
