"""CCA authority decisions use trusted tenant records, not client premises flags."""

import json
from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.features.compliant.models.alcohol_product_profile import AlcoholProductProfile
from app.features.compliant.models.compliance_profile import ComplianceProfile
from app.features.compliant.modules.nz_alcohol import premises
from app.features.compliant.platform.stock_movements import evaluate_stock_movement
from tests.test_customs_premises import coverage_data, licence_data, world  # noqa: F401


@pytest.fixture
def movement(db, world):  # noqa: F811
    orgs, sites, extra, _ = world
    db.add(ComplianceProfile(org_id=orgs[0].id, enabled=True, industry_module="nz_alcohol"))
    db.add(AlcoholProductProfile(org_id=orgs[0].id, inventory_name="Gin", product_type="spirits"))
    first = premises.add_licence(db, orgs[0].id, licence_data())
    second = premises.add_licence(db, orgs[0].id, licence_data(number="CCA-456"))
    premises.add_coverage(db, orgs[0].id, coverage_data(first, sites[0]))
    premises.add_coverage(db, orgs[0].id, coverage_data(second, extra))
    db.flush()
    context = SimpleNamespace(
        operation="dispatch",
        source_site_id=sites[0].id,
        destination_site_id=extra.id,
        source_location_id=None,
        destination_location_id=None,
        source_item_id=uuid4(),
        product_name="Gin",
        inventory_type="FINAL_PRODUCT",
        quantity=Decimal("12"),
        unit="bottles",
        occurred_on=date(2026, 9, 29),
        carrier="Carrier A",
        consignment_reference="CN-123",
        approval={"authority": "same_legal_entity", "evidence_reference": "Registered entity comparison"},
        transfer_id=uuid4(),
        receipt_id=None,
        actor_id=uuid4(),
        source_snapshot={},
        dispatch_evidence=None,
    )
    return orgs[0].id, context, first, second


def test_same_entity_transfer_records_immutable_evidence(db, movement):
    org, context, source, destination = movement
    decision = evaluate_stock_movement(db, org, context)
    assert decision.allowed
    snapshot = json.loads(decision.evidence)
    assert snapshot["source_licence"]["id"] == str(source.id)
    assert snapshot["destination_licence"]["id"] == str(destination.id)
    context.approval["evidence_reference"] = "Changed afterwards"
    assert json.loads(decision.evidence)["authority"]["evidence_reference"] != "Changed afterwards"
    assert snapshot["binding"]["transfer_id"] == str(context.transfer_id)


def test_destination_oss_requires_prior_approval_even_same_entity(db, movement):
    org, context, _, destination = movement
    destination.kind = "oss"
    db.flush()
    assert not evaluate_stock_movement(db, org, context).allowed
    context.approval = {
        "authority": "prior_customs_approval",
        "reference": "NZCS-249",
        "approved_on": "2026-09-28",
        "evidence_reference": "Approval PDF",
    }
    assert evaluate_stock_movement(db, org, context).allowed
    context.approval["approved_on"] = "2026-09-30"
    assert not evaluate_stock_movement(db, org, context).allowed


@pytest.mark.parametrize(
    "change",
    [
        {"quantity": Decimal("NaN")},
        {"quantity": 0},
        {"quantity": -1},
        {"carrier": ""},
        {"consignment_reference": None},
        {"product_name": "Unclassified raw stock"},
        {"occurred_on": "2026-09-29"},
        {"operation": "loss"},
        {"destination_location_id": uuid4()},
        {"approval": {"authority": "same_legal_entity", "evidence_reference": ""}},
        {"approval": {"authority": "same_legal_entity", "evidence_reference": "X", "org_id": "forged"}},
        {"approval": {"authority": "further_manufacture", "evidence_reference": "Unsupported claim"}},
    ],
)
def test_unknown_or_unaccounted_movements_are_blocked(db, movement, change):
    org, context, _, _ = movement
    for key, value in change.items():
        setattr(context, key, value)
    assert not evaluate_stock_movement(db, org, context).allowed


def test_registered_entity_and_licence_dates_are_checked(db, movement):
    org, context, _, destination = movement
    destination.legal_entity_reference = "Different entity"
    db.flush()
    assert not evaluate_stock_movement(db, org, context).allowed
    destination.legal_entity_reference = "NZBN-123"
    context.occurred_on = date(2025, 12, 31)
    assert not evaluate_stock_movement(db, org, context).allowed


def test_receipt_binds_original_dispatch_and_current_coverage(db, movement):
    org, context, _, _ = movement
    dispatch = evaluate_stock_movement(db, org, context)
    context.operation = "receipt"
    context.receipt_id = uuid4()
    context.dispatch_evidence = json.loads(dispatch.evidence)
    context.quantity = Decimal("6")
    assert evaluate_stock_movement(db, org, context).allowed
    context.quantity = Decimal("13")
    assert not evaluate_stock_movement(db, org, context).allowed
    context.quantity = Decimal("6")
    context.source_item_id = uuid4()
    assert not evaluate_stock_movement(db, org, context).allowed


def test_missing_dispatch_proof_cannot_authorise_receipt(db, movement):
    org, context, _, _ = movement
    context.operation = "receipt"
    for bad in (None, "not-json", [], {"policy": "fake"}):
        context.dispatch_evidence = bad
        assert not evaluate_stock_movement(db, org, context).allowed


def test_receipt_date_cannot_precede_dispatch(db, movement):
    org, context, _, _ = movement
    context.dispatch_evidence = evaluate_stock_movement(db, org, context).evidence
    context.operation = "receipt"
    context.occurred_on = date(2026, 9, 28)
    assert not evaluate_stock_movement(db, org, context).allowed


def test_no_module_is_unrestricted_but_unknown_configured_module_is_closed(db, world):  # noqa: F811
    orgs, _, _, _ = world
    assert evaluate_stock_movement(db, orgs[0].id, None).allowed
    db.add(ComplianceProfile(org_id=orgs[0].id, enabled=True, industry_module="unsupported"))
    db.flush()
    assert not evaluate_stock_movement(db, orgs[0].id, None).allowed
