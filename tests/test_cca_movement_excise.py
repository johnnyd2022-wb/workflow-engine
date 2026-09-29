"""Reviewed movement measurement is bounded, immutable and not tax authorisation."""

import json
from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest

from app.core.db.models.stock_location import StockLocation
from app.features.compliant.models.alcohol_product_profile import AlcoholProductProfile
from app.features.compliant.models.excise import ExciseRate
from app.features.compliant.modules.nz_alcohol.movement_excise import (
    capture_spirits_removal_basis,
    cca_movement_register,
)
from app.features.compliant.platform.stock_movements import evaluate_stock_movement
from app.features.contract_manufacturing.models.orders import ContractCustomer  # noqa: F401 -- FK mapper registration
from tests.test_compliant_routes import flask_app  # noqa: F401
from tests.test_customs_premises import world  # noqa: F401
from tests.test_food_registrations import clients  # noqa: F401
from tests.test_stock_movement_policy import movement  # noqa: F401


@pytest.fixture
def measured(db, movement):  # noqa: F811
    org, context, source, _ = movement
    product = db.query(AlcoholProductProfile).filter(AlcoholProductProfile.org_id == org).one()
    product.pack_volume_ml, product.customs_product_code = Decimal("700"), "TEST-LAL-SPIRITS"
    rates = [
        ExciseRate(org_id=org, tariff_item="TEST-LAL-SPIRITS", rate_per_lal="42.50", effective_from=date(2026, 7, 1)),
        ExciseRate(org_id=org, tariff_item="TEST-LAL-SPIRITS", rate_per_lal="999", effective_from=date(2027, 7, 1)),
    ]
    db.add_all(rates)
    db.flush()
    context.source_snapshot = {"contract_customer_id": None}
    context.approval = {
        "measured_abv_percent": "45",
        "measurement_method": "hydrometric",
        "measured_on": "2026-09-28",
        "measurement_reference": "Test and calibration report",
        "volume_reference": "700mL pack specification",
    }
    return org, context, product, source, rates[0]


def test_tested_basis_freezes_the_source_cca_measurement_and_applicable_rate(db, measured):
    org, context, product, source, rate = measured
    decision = capture_spirits_removal_basis(db, org, context, product, source)
    assert decision.valid
    fact = json.loads(decision.evidence)
    assert Decimal(fact["litres"]) == Decimal("8.4")
    assert Decimal(fact["lal"]) == Decimal("3.78")
    assert Decimal(fact["excise_duty_only"]) == Decimal("160.65")
    assert fact["source_cca"]["id"] == str(source.id)
    assert fact["rate"]["id"] == str(rate.id)
    assert fact["duty_payer"] is None and fact["authorises_physical_removal"] is False
    assert fact["levy"] is None and fact["gst"] is None
    product.pack_volume_ml = 1000
    rate.rate_per_lal = 1
    context.approval["measurement_reference"] = "Edited later"
    assert json.loads(decision.evidence) == fact


def test_home_removal_policy_requires_prelocked_producer_duty_and_exact_source(db, measured):
    org, context, _product, _source, _rate = measured
    shop = db.query(StockLocation).filter(StockLocation.org_id == org, StockLocation.name == "Cellar door").one()
    context.destination_site_id = context.source_site_id
    context.destination_location_id = shop.id
    context.source_snapshot.update(source_execution_id=None, source_execution_step_id=None)
    context.prepared_context = {
        "found": True,
        "source_item_id": str(context.source_item_id),
        "source_execution_id": None,
        "source_execution_step_id": None,
        "contract_order_id": None,
        "duty_responsibility": "producer_licensee",
    }
    context.approval.update(
        authority="home_consumption",
        destination_activity="selling",
        evidence_reference="Reviewed excise removal",
    )
    decision = evaluate_stock_movement(db, org, context)
    assert decision.allowed
    recorded = json.loads(decision.evidence)
    assert recorded["tax_status"] == "home_consumption_excise_due"
    assert recorded["removal_basis"]["source_cca"]["id"] == recorded["source_licence"]["id"]

    context.operation = "receipt"
    context.receipt_id = uuid4()
    context.quantity = Decimal("6")
    context.dispatch_evidence = recorded
    assert evaluate_stock_movement(db, org, context).allowed
    context.dispatch_evidence = {**recorded, "removal_basis": {}}
    assert not evaluate_stock_movement(db, org, context).allowed

    context.operation = "dispatch"
    context.quantity = Decimal("12")
    context.prepared_context["duty_responsibility"] = "customer_licensee"
    assert not evaluate_stock_movement(db, org, context).allowed
    context.prepared_context["duty_responsibility"] = "producer_licensee"
    context.prepared_context["source_execution_step_id"] = str(uuid4())
    assert not evaluate_stock_movement(db, org, context).allowed


@pytest.mark.parametrize(
    "value", [None, False, "NaN", "Infinity", "-1", "0", "23", "100.0001", "1e99999999", "1" * 101]
)
def test_unverified_or_invalid_strength_cannot_form_a_basis(db, measured, value):
    org, context, product, source, _ = measured
    context.approval["measured_abv_percent"] = value
    assert not capture_spirits_removal_basis(db, org, context, product, source).valid


@pytest.mark.parametrize(
    "changes",
    [
        {"measurement_method": "label"},
        {"measurement_method": []},
        {"measurement_reference": ""},
        {"measured_on": "2026-09-30"},
        {"measured_on": None},
        {"volume_reference": ""},
    ],
)
def test_documented_testing_and_volume_are_required(db, measured, changes):
    org, context, product, source, _ = measured
    context.approval.update(changes)
    assert not capture_spirits_removal_basis(db, org, context, product, source).valid


@pytest.mark.parametrize("owner", [str(uuid4()), False, {}])
def test_contract_duty_is_not_inferred_from_material_owner(db, measured, owner):
    org, context, product, source, _ = measured
    context.source_snapshot = {"contract_customer_id": owner}
    assert not capture_spirits_removal_basis(db, org, context, product, source).valid
    context.source_snapshot = {}
    assert not capture_spirits_removal_basis(db, org, context, product, source).valid


def test_foreign_and_uncovered_source_or_wrong_product_are_blocked(db, measured):
    org, context, product, source, _ = measured
    assert not capture_spirits_removal_basis(db, uuid4(), context, product, source).valid
    context.source_location_id = uuid4()
    assert not capture_spirits_removal_basis(db, org, context, product, source).valid
    context.source_location_id = None
    context.product_name = "Different product"
    assert not capture_spirits_removal_basis(db, org, context, product, source).valid


@pytest.mark.parametrize("unit,quantity,expected", [("L", "10", "10"), ("mL", "1000", "1"), ("bottles", "2", "1.4")])
def test_supported_physical_volume_bases(db, measured, unit, quantity, expected):
    org, context, product, source, _ = measured
    context.unit, context.quantity = unit, Decimal(quantity)
    decision = capture_spirits_removal_basis(db, org, context, product, source)
    assert decision.valid
    assert Decimal(json.loads(decision.evidence)["litres"]) == Decimal(expected)


@pytest.mark.parametrize("unit,quantity", [("cases", "2"), ("kg", "10"), ("bottles", "1.5"), ("L", "NaN")])
def test_unknown_pack_conversion_or_fractional_counts_are_blocked(db, measured, unit, quantity):
    org, context, product, source, _ = measured
    context.unit, context.quantity = unit, Decimal(quantity)
    assert not capture_spirits_removal_basis(db, org, context, product, source).valid


def test_missing_rate_does_not_become_zero_duty(db, measured):
    org, context, product, source, _ = measured
    product.customs_product_code = "NO-RATE"
    decision = capture_spirits_removal_basis(db, org, context, product, source)
    assert not decision.valid and "rate" in decision.reason.lower()


def test_empty_register_never_claims_complete_or_nil(db, world):  # noqa: F811
    org = world[0][0].id
    current = cca_movement_register(db, org, date(2026, 9, 1), date(2026, 10, 1))
    assert current["licences"] == [] and current["total_duty"] is None
    assert current["complete_lodgement"] is False and current["nil_return"] is None
    assert current["remaining_sources"]
    with pytest.raises(ValueError):
        cca_movement_register(db, org, date(2026, 9, 1), date(2026, 9, 1))


def test_register_api_has_bounded_dates_and_trusted_org(clients):  # noqa: F811
    _, client, _, neighbour = clients
    path = "/api/compliant/nz-alcohol/excise/cca-movements"
    assert client.get(path).status_code == 400
    assert client.get(path, query_string={"start": "2020-01-01", "end": "2026-01-01"}).status_code == 400
    for actor in (client, neighbour):
        response = actor.get(path, query_string={"start": "2026-09-01", "end": "2026-10-01", "org_id": str(uuid4())})
        assert response.status_code == 200 and response.get_json()["licences"] == []


@pytest.mark.parametrize("bad_fact", [None, "dispatched_quantity", "dispatched_on"])
def test_register_groups_immutable_cca_dispatch_once_despite_partial_receipts(db, movement, bad_fact):  # noqa: F811
    from app.core.db.models.site_transfer import SiteStockReceipt, SiteStockTransfer
    from app.core.db.models.user import User, UserRole
    from app.core.db.repositories.inventory_repo import InventoryRepository
    from app.core.db.transfer_guard import allow_transfer_accounting
    from app.features.compliant.platform.stock_movements import evaluate_stock_movement

    org, context, source, destination = movement
    actor = User(
        id=uuid4(), org_id=org, email=f"cca-{uuid4()}@test.invalid", password_hash="unused", role=UserRole.ADMIN
    )
    db.add(actor)
    db.flush()
    item = InventoryRepository(db).create_inventory_item(
        org_id=org, name="Gin", quantity="20", unit="bottles", inventory_type="final_product", commit=False
    )
    context.source_item_id = item.id
    evidence = json.loads(evaluate_stock_movement(db, org, context).evidence)
    if bad_fact:
        evidence[bad_fact] = "13" if bad_fact == "dispatched_quantity" else "2026-09-28"
    transfer = SiteStockTransfer(
        id=context.transfer_id,
        org_id=org,
        source_item_id=item.id,
        source_site_id=context.source_site_id,
        destination_site_id=context.destination_site_id,
        quantity=12,
        received_quantity=6,
        loss_quantity=0,
        unit="bottles",
        carrier=context.carrier,
        consignment_reference=context.consignment_reference,
        occurred_on=context.occurred_on,
        source_snapshot={},
        decision_snapshot=evidence,
        idempotency_key=str(uuid4()),
        request_hash="x" * 64,
        created_by_user_id=actor.id,
    )
    with allow_transfer_accounting():
        db.add(transfer)
        db.flush()
        for _ in range(2):
            db.add(
                SiteStockReceipt(
                    id=uuid4(),
                    org_id=org,
                    transfer_id=transfer.id,
                    quantity=3,
                    damaged_quantity=0,
                    short_quantity=0,
                    occurred_on=context.occurred_on,
                    decision_snapshot={},
                    idempotency_key=str(uuid4()),
                    request_hash="y" * 64,
                    created_by_user_id=actor.id,
                )
            )
        db.flush()
    current = cca_movement_register(db, org, date(2026, 9, 1), date(2026, 10, 1))
    assert len(current["licences"]) == 1
    if bad_fact:
        assert current["licences"][0]["movements"] == []
        assert current["unresolved_movements"][0]["transfer_id"] == str(transfer.id)
        assert current["total_duty"] is None and current["nil_return"] is None
        return
    assert current["unresolved_movements"] == []
    group = current["licences"][0]
    assert group["source_cca"]["id"] == str(source.id)
    assert len(group["movements"]) == 1
    assert group["movements"][0]["destination_cca"]["id"] == str(destination.id)
    assert group["movements"][0]["treatment"] == "recorded_excise_unpaid_transfer"
    assert current["nil_return"] is None and current["total_duty"] is None
    assert cca_movement_register(db, uuid4(), date(2026, 9, 1), date(2026, 10, 1))["licences"] == []
