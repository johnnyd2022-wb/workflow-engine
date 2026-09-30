"""Destination activity is explicit and registration findings stay module-owned."""

import json
from datetime import date
from pathlib import Path
from uuid import uuid4

import pytest

from app.features.compliant.models.licensing import LiquorLicence
from app.features.compliant.modules.nz_alcohol import food_registrations, movement_registrations
from app.features.compliant.modules.nz_alcohol.module import run_movement_registration_check
from app.features.compliant.platform.stock_movements import evaluate_stock_movement, movement_requirements
from tests.test_customs_premises import world  # noqa: F401
from tests.test_food_registrations import registration_data
from tests.test_stock_movement_policy import movement  # noqa: F401


def scope(db, org, context, activity="storage", **changes):
    row = food_registrations.add_registration(db, org, registration_data(**changes), context.occurred_on)
    food_registrations.add_scope(
        db,
        org,
        {
            "registration_id": str(row.id),
            "site_id": str(context.destination_site_id),
            "activity": activity,
            "evidence_reference": "Premises schedule",
        },
    )
    return row


def test_unknown_activity_is_not_inferred_from_site_kind(db, movement):  # noqa: F811
    org, context, _, _ = movement
    decision = evaluate_stock_movement(db, org, context)
    assert decision.allowed
    alerts = json.loads(decision.evidence)["system_alerts"]
    assert len(alerts) == 1 and alerts[0]["id"].endswith("-activity")
    assert "activity" in alerts[0]["title"]
    fields = movement_requirements(db, org)["fields"]
    assert next(f for f in fields if f["name"] == "destination_activity")["required"]


def test_dated_activity_scope_and_snapshot_do_not_change_after_dispatch(db, movement):  # noqa: F811
    org, context, _, _ = movement
    context.approval["destination_activity"] = "storage"
    before = evaluate_stock_movement(db, org, context)
    assert json.loads(before.evidence)["system_alerts"][0]["id"].endswith("-food")
    scope(db, org, context)
    assert json.loads(evaluate_stock_movement(db, org, context).evidence)["system_alerts"] == []
    assert json.loads(before.evidence)["system_alerts"]  # append-only original decision
    context.approval["destination_activity"] = "manufacturing"
    assert json.loads(evaluate_stock_movement(db, org, context).evidence)["system_alerts"]


@pytest.mark.parametrize("activity", ["invented", "", "Storage", [], False])
def test_invalid_activity_is_controlled(db, movement, activity):  # noqa: F811
    org, context, _, _ = movement
    context.approval["destination_activity"] = activity
    assert not evaluate_stock_movement(db, org, context).allowed


def test_receipt_rechecks_expired_food_scope_and_uses_original_activity(db, movement):  # noqa: F811
    org, context, _, _ = movement
    scope(db, org, context, valid_until="2026-09-29")
    context.approval["destination_activity"] = "storage"
    dispatch = evaluate_stock_movement(db, org, context)
    assert json.loads(dispatch.evidence)["system_alerts"] == []
    context.dispatch_evidence, context.operation, context.receipt_id = dispatch.evidence, "receipt", uuid4()
    context.occurred_on = date(2026, 9, 30)
    context.approval = {"destination_activity": "selling"}  # receipt cannot replace dispatch authority/activity
    decision = evaluate_stock_movement(db, org, context)
    assert decision.allowed
    evidence = json.loads(decision.evidence)
    assert evidence["destination_activity"] == "storage"
    assert len(evidence["system_alerts"]) == 1


def test_selling_requires_dated_assigned_current_liquor_record(db, movement):  # noqa: F811
    org, context, _, _ = movement
    scope(db, org, context, "selling")
    context.approval["destination_activity"] = "selling"
    licence = LiquorLicence(
        org_id=org,
        site_id=context.destination_site_id,
        kind="off",
        licence_number="OFF-123",
        issued_on=date(2026, 1, 1),
        expires_on=date(2026, 9, 28),
        status="current",
    )
    db.add(licence)
    db.flush()
    assert json.loads(evaluate_stock_movement(db, org, context).evidence)["system_alerts"][0]["id"].endswith("-liquor")
    licence.expires_on = date(2026, 9, 29)
    db.flush()
    assert json.loads(evaluate_stock_movement(db, org, context).evidence)["system_alerts"] == []
    licence.status = "cancelled"
    db.flush()
    assert json.loads(evaluate_stock_movement(db, org, context).evidence)["system_alerts"]
    licence.status = "current"
    licence.site_id = None
    db.flush()
    assert json.loads(evaluate_stock_movement(db, org, context).evidence)["system_alerts"]


def test_foreign_tenant_sites_and_records_are_not_used(db, movement):  # noqa: F811
    org, context, _, _ = movement
    assert (
        movement_registrations.coverage_findings(
            db, uuid4(), context.destination_site_id, "selling", context.occurred_on, context.transfer_id
        )
        == []
    )


def test_module_contract_has_stable_internal_actions_without_core_product_branches(db, movement, monkeypatch):  # noqa: F811
    org, context, _, _ = movement
    alerts = movement_registrations.coverage_findings(
        db, org, context.destination_site_id, "selling", context.occurred_on, context.transfer_id
    )
    monkeypatch.setattr(movement_registrations, "transfer_findings", lambda _db, _org: alerts)
    result = run_movement_registration_check(org, db)
    assert result.flagged and result.data["system_alerts"] == alerts
    assert result.data["system_finding"]["details"] == alerts
    assert len({a["id"] for a in alerts}) == len(alerts) == 2
    assert all(a["href"].startswith("/") and not a["href"].startswith("//") for a in alerts)
    for filename in ("system-findings-banner.js", "system-findings-notifications.js"):
        assert "movement_registrations" not in Path("app/core/frontend/js", filename).read_text()


def test_persisted_transfer_and_receipt_findings_use_their_dates(db, movement):  # noqa: F811
    from app.core.db.models.site_transfer import SiteStockReceipt, SiteStockTransfer
    from app.core.db.models.user import User, UserRole
    from app.core.db.repositories.inventory_repo import InventoryRepository
    from app.core.db.transfer_guard import allow_transfer_accounting

    org, context, _, _ = movement
    scope(db, org, context, valid_until="2026-09-29")
    context.approval["destination_activity"] = "storage"
    dispatch = evaluate_stock_movement(db, org, context)
    actor = User(
        id=uuid4(), org_id=org, email=f"movement-{uuid4()}@test.invalid", password_hash="unused", role=UserRole.ADMIN
    )
    db.add(actor)
    db.flush()
    item = InventoryRepository(db).create_inventory_item(
        org_id=org, name="Gin", quantity="20", unit="bottles", inventory_type="final_product", commit=False
    )
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
        carrier="Carrier",
        consignment_reference="CN",
        occurred_on=context.occurred_on,
        source_snapshot={},
        decision_snapshot=json.loads(dispatch.evidence),
        idempotency_key=str(uuid4()),
        request_hash="x" * 64,
        created_by_user_id=actor.id,
    )
    receipt = SiteStockReceipt(
        id=uuid4(),
        org_id=org,
        transfer_id=transfer.id,
        quantity=6,
        damaged_quantity=0,
        short_quantity=0,
        occurred_on=date(2026, 9, 30),
        decision_snapshot={"receipt": {"policy": "nz_alcohol_cca_1", "destination_activity": "storage"}},
        idempotency_key=str(uuid4()),
        request_hash="y" * 64,
        created_by_user_id=actor.id,
    )
    with allow_transfer_accounting():
        db.add(transfer)
        db.flush()
        db.add(receipt)
        db.flush()
    findings = movement_registrations.transfer_findings(db, org)
    assert len(findings) == 1
    assert str(receipt.id) in findings[0]["id"] and findings[0]["due_date"] == "2026-09-30"
    assert movement_registrations.transfer_findings(db, uuid4()) == []
    result = run_movement_registration_check(org, db)
    assert result.flagged and result.data["system_alerts"] == findings
