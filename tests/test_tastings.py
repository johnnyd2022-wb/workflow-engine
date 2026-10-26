"""Real-Postgres evidence for tasting scheduling, stock conservation, excise and access."""

from concurrent.futures import ThreadPoolExecutor
from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest

from app.core.backend.tasks import assign_task_to_lane
from app.core.db import SessionLocal
from app.core.db.models.user import UserRole
from app.features.compliant.models.alcohol_product_profile import AlcoholProductProfile
from app.features.compliant.models.excise import ExciseRate
from app.features.compliant.modules.nz_alcohol import excise
from app.features.compliant.modules.nz_alcohol.movement_excise import cca_movement_register
from app.features.crm.models.crm_task import CRMTask
from app.features.crm.repositories.crm_task_repo import CRMTaskRepository
from app.features.tastings.models import TastingAllocation, TastingStockLot
from app.features.tastings.services import tasting_service as service
from tests.factories import InventoryItemFactory, OrganisationFactory, UserFactory


@pytest.fixture
def world(db):
    org = OrganisationFactory()
    rep = UserFactory(org_id=org.id, email=f"tasting-{uuid4()}@example.test", role=UserRole.ADMIN)
    item = InventoryItemFactory(
        org_id=org.id,
        name="Sampling Gin",
        unit="bottles",
        quantity="10",
        inventory_type="final_product",
        extra_data={"opening_stock": True, "abv_percent": "40", "batch_number": "BATCH-ONE"},
    )
    profile = AlcoholProductProfile(
        org_id=org.id,
        inventory_name=item.name,
        product_type="spirits",
        pack_volume_ml=700,
        abv_percent=40,
        customs_product_code="TEST-TASTING",
        excise_category="gin",
    )
    rate = ExciseRate(org_id=org.id, tariff_item="TEST-TASTING", rate_per_lal="50", effective_from=date(2026, 1, 1))
    db.add_all([profile, rate])
    db.commit()
    return org, rep, item, profile, rate


def payload(rep, item, quantity="2"):
    return {
        "title": "Friday tasting",
        "venue_name": "Licensed bottle store",
        "venue_address": "100 Sample Road",
        "venue_type": "external",
        "licence_reference": "Venue supplied reference",
        "starts_at": "2026-10-20T14:00:00+13:00",
        "ends_at": "2026-10-20T17:00:00+13:00",
        "rep_id": str(rep.id),
        "notes": "Brand sampling",
        "allocations": [{"source_item_id": str(item.id), "quantity": quantity}],
    }


def create(db, world, quantity="2"):
    org, rep, item, *_ = world
    return service.save_event(db, org.id, rep.id, payload(rep, item, quantity))


def dispatched(db, world, quantity="2", actual_date="2026-10-20"):
    event = create(db, world, quantity)
    org, rep, *_ = world
    service.dispatch(db, org.id, rep.id, event.id, {"actual_date": actual_date}, str(uuid4()))
    db.commit()
    return event


def test_plan_calendar_and_cancel_do_not_remove_stock(db, world):
    org, rep, item, *_ = world
    event = create(db, world)
    db.commit()
    task = db.query(CRMTask).filter_by(id=event.task_id, org_id=org.id).one()
    assert task.due_date == date(2026, 10, 20) and task.assigned_to_user_id == rep.id
    assert db.query(TastingStockLot).filter_by(org_id=org.id).count() == 0
    with pytest.raises(ValueError, match="tasting"):
        CRMTaskRepository(db).update(task, title="Bypass")
    with pytest.raises(ValueError, match="tasting"):
        CRMTaskRepository(db).delete(task)
    with pytest.raises(ValueError, match="tasting"):
        assign_task_to_lane(db, org.id, "crm", task.id, None)
    service.cancel(db, org.id, rep.id, event.id)
    db.commit()
    assert task.status == "cancelled" and item.quantity == 10


def test_dispatch_outcomes_and_reuse_conserve_partial_bottles(db, world):
    org, rep, item, *_ = world
    event = dispatched(db, world, "1")
    lot = db.query(TastingStockLot).filter_by(org_id=org.id).one()
    line = db.query(TastingAllocation).filter_by(tasting_id=event.id, org_id=org.id).one()
    assert item.quantity == 9 and lot.reserved_volume_ml == 700
    body = {
        "usage": [{"allocation_id": str(line.id), "used_volume_ml": "150"}],
        "samples_count": 15,
        "notes": "150 mL sampled",
    }
    service.finalise(db, org.id, rep.id, event.id, body)
    db.commit()
    service.finalise(db, org.id, rep.id, event.id, body)
    db.commit()
    assert lot.remaining_volume_ml == 550 and lot.reserved_volume_ml == 0
    with pytest.raises(service.TastingError, match="immutable"):
        service.finalise(db, org.id, rep.id, event.id, {**body, "samples_count": 16})
    data = payload(rep, item)
    data["allocations"] = [{"source_pool_id": str(lot.id), "quantity": "300"}]
    next_event = service.save_event(db, org.id, rep.id, data)
    service.dispatch(db, org.id, rep.id, next_event.id, {"actual_date": "2026-10-21"}, str(uuid4()))
    db.commit()
    assert lot.reserved_volume_ml == 300 and item.quantity == 9
    assert len(excise.removals_between(db, org.id, date(2026, 10, 1), date(2026, 11, 1))) == 1
    service.cancel(db, org.id, rep.id, next_event.id)
    db.commit()
    assert lot.remaining_volume_ml == 550 and lot.reserved_volume_ml == 0 and item.quantity == 9
    assert lot.purpose == "tasting"


def test_dispatch_replay_and_changed_request(db, world):
    org, rep, item, *_ = world
    event = create(db, world)
    key = str(uuid4())
    service.dispatch(db, org.id, rep.id, event.id, {"actual_date": "2026-10-20"}, key)
    db.commit()
    service.dispatch(db, org.id, rep.id, event.id, {"actual_date": "2026-10-20"}, key)
    db.commit()
    assert item.quantity == 8
    with pytest.raises(service.TastingError, match="different"):
        service.dispatch(db, org.id, rep.id, event.id, {"actual_date": "2026-10-21"}, key)
    with pytest.raises(service.TastingError, match="planned"):
        service.save_event(db, org.id, rep.id, {"title": "Change"}, event.id)


def test_excise_frozen_date_rate_and_period_identity(db, world):
    org, rep, item, profile, rate = world
    dispatched(db, world, actual_date="2026-09-30")
    before = excise.draft(db, org.id, date(2026, 9, 1), "monthly", today=date(2026, 11, 1))
    assert len(before["lines"]) == 1 and before["lines"][0]["duty"] == "28.00"
    assert before["entry"]["complete"] and before["entry"]["lines"][0]["rate_date"] == "2026-09-30"
    profile.pack_volume_ml = 1000
    profile.abv_percent = 10
    rate.rate_per_lal = 999
    item.name = "Edited name"
    item.extra_data = {"abv_percent": "1"}
    db.commit()
    after = excise.draft(db, org.id, date(2026, 9, 1), "monthly", today=date(2026, 11, 1))
    assert after["lines"] == before["lines"] and after["entry"] == before["entry"]
    assert excise.draft(db, org.id, date(2026, 10, 1), "monthly")["lines"] == []
    register = cca_movement_register(db, org.id, date(2026, 9, 1), date(2026, 10, 1))
    assert len(register["unresolved_movements"]) == 1  # legacy source deliberately has no modern CCA
    assert register["complete_lodgement"] is False and register["nil_return"] is None


def test_missing_basis_persists_visible_problem_never_false_nil(db, world):
    org, rep, item, profile, rate = world
    profile.abv_percent = None
    item.extra_data = {"opening_stock": True}
    db.commit()
    dispatched(db, world)
    draft = excise.draft(db, org.id, date(2026, 10, 1), "monthly", today=date(2026, 11, 1))
    assert draft["problems"] and not draft["entry"]["complete"]
    with pytest.raises(ValueError, match="Resolve"):
        excise.lodge(
            db, org.id, date(2026, 10, 1), "monthly", date(2026, 11, 1), "TEST", rep.id, today=date(2026, 11, 1)
        )
    profile.abv_percent = 40
    db.commit()
    assert not excise.draft(db, org.id, date(2026, 10, 1), "monthly")["entry"]["complete"]


def test_late_backdated_removal_keeps_lodged_snapshot_and_identity(db, world):
    org, rep, *_ = world
    excise.lodge(
        db, org.id, date(2026, 9, 1), "monthly", date(2026, 10, 15), "NIL-REF", rep.id, today=date(2026, 10, 20)
    )
    db.commit()
    dispatched(db, world, actual_date="2026-09-25")
    sept = excise.draft(db, org.id, date(2026, 9, 1), "monthly")
    octdraft = excise.draft(db, org.id, date(2026, 10, 1), "monthly")
    assert sept["nil_return"] and sept["lines"] == []
    assert len(octdraft["adjustments"]) == 1
    assert octdraft["adjustments"][0]["reference"].startswith("tasting-stock:")
    assert octdraft["adjustments"][0]["belongs_to"] == "2026-09-01"


@pytest.mark.parametrize(
    "field,value",
    [
        ("rep_id", str(uuid4())),
        ("contact_id", str(uuid4())),
        ("starts_at", "2026-10-20T14:00:00"),
        ("starts_at", "2026-10-20T14:00:00+12:00"),
        ("ends_at", "2026-10-20T13:00:00+13:00"),
        ("title", "x" * 161),
        ("venue_type", "other"),
    ],
)
def test_validation_and_reference_isolation(db, world, field, value):
    org, rep, item, *_ = world
    data = payload(rep, item)
    data[field] = value
    with pytest.raises(service.TastingError):
        service.save_event(db, org.id, rep.id, data)


def test_all_lines_rollback_on_insufficient_stock(db, world):
    org, rep, item, *_ = world
    second = InventoryItemFactory(
        org_id=org.id,
        name=item.name,
        quantity="1",
        unit="bottles",
        inventory_type="final_product",
        extra_data={"opening_stock": True},
    )
    db.commit()
    data = payload(rep, item)
    data["allocations"].append({"source_item_id": str(second.id), "quantity": "2"})
    event = service.save_event(db, org.id, rep.id, data)
    db.commit()
    with pytest.raises(service.TastingError):
        service.dispatch(db, org.id, rep.id, event.id, {"actual_date": "2026-10-20"}, str(uuid4()))
    db.rollback()
    db.refresh(item)
    db.refresh(second)
    assert item.quantity == 10 and second.quantity == 1
    assert db.query(TastingStockLot).filter_by(org_id=org.id).count() == 0


def test_concurrent_warehouse_dispatch_prevents_oversell(db, world):
    org, rep, item, *_ = world
    a = create(db, world, "7")
    b = create(db, world, "7")
    db.commit()
    ids = [a.id, b.id]
    org_id = org.id
    rep_id = rep.id
    db.rollback()  # release identity refresh transactions before worker locks

    def run(event_id):
        worker = SessionLocal()
        try:
            service.dispatch(worker, org_id, rep_id, event_id, {"actual_date": "2026-10-20"}, str(uuid4()))
            worker.commit()
            return "ok"
        except service.TastingError:
            worker.rollback()
            return "insufficient"
        finally:
            worker.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(run, ids))
    assert sorted(results) == ["insufficient", "ok"]
    db.refresh(item)
    assert item.quantity == 3


def test_api_subscription_roles_csrf_and_hostile_ids(db, world):
    from app.api.app_factory import create_app
    from app.core.db.repositories.feature_subscription_repo import FeatureSubscriptionRepository
    from app.features.compliant.models.compliance_profile import ComplianceProfile
    from tests.factories import DEFAULT_TEST_PASSWORD

    org, rep, item, *_ = world
    app = create_app()
    app.config.update(TESTING=True, WTF_CSRF_ENABLED=False)

    def login(user):
        client = app.test_client()
        client.environ_base["wsgi.url_scheme"] = "https"
        client.environ_base["HTTP_X_FORWARDED_PROTO"] = "https"
        response = client.post("/auth/login", json={"email": user.email, "password": DEFAULT_TEST_PASSWORD})
        assert response.status_code == 200
        return client

    admin = login(rep)
    assert admin.get("/api/crm/tastings").status_code == 404
    assert admin.get("/crm/tastings").status_code == 404
    FeatureSubscriptionRepository(db).grant(org.id, "compliant")
    db.add(ComplianceProfile(org_id=org.id, enabled=True, industry_module="nz_alcohol"))
    db.commit()
    # Request-scoped entitlements are freshly read on every subsequent request.
    assert admin.get("/api/crm/tastings").status_code == 200
    response = admin.post("/api/crm/tastings", json=payload(rep, item))
    assert response.status_code == 201, response.get_json()
    event_id = response.get_json()["tasting"]["id"]
    sales = UserFactory(org_id=org.id, email=f"sales-{uuid4()}@example.test", role=UserRole.SALES)
    auditor = UserFactory(org_id=org.id, email=f"audit-{uuid4()}@example.test", role=UserRole.AUDITOR)
    hostile_org = OrganisationFactory()
    hostile_rep = UserFactory(org_id=hostile_org.id, email=f"hostile-{uuid4()}@example.test", role=UserRole.ADMIN)
    FeatureSubscriptionRepository(db).grant(hostile_org.id, "compliant")
    db.add(ComplianceProfile(org_id=hostile_org.id, enabled=True, industry_module="nz_alcohol"))
    db.commit()
    sales_client = login(sales)
    audit_client = login(auditor)
    hostile_client = login(hostile_rep)
    assert (
        sales_client.post(
            f"/api/crm/tastings/{event_id}/dispatch",
            json={"actual_date": "2026-10-20"},
            headers={"Idempotency-Key": "sales-not-allowed"},
        ).status_code
        == 403
    )
    assert audit_client.post("/api/crm/tastings", json=payload(rep, item)).status_code == 403
    assert hostile_client.get(f"/api/crm/tastings/{event_id}").status_code == 404
    assert hostile_client.get("/api/crm/tastings/choices").get_json()["stock"] == []
    assert hostile_client.post("/api/crm/tastings", json=payload(rep, item)).status_code == 400
    app.config["WTF_CSRF_ENABLED"] = True
    assert admin.post(f"/api/crm/tastings/{event_id}/cancel", json={}).status_code == 400


def test_pool_concurrent_reservations_do_not_double_allocate(db, world):
    org, rep, *_ = world
    event = dispatched(db, world, "1")
    service.cancel(db, org.id, rep.id, event.id)
    db.commit()
    lot = db.query(TastingStockLot).filter_by(org_id=org.id).one()
    data = payload(rep, world[2])
    data["allocations"] = [{"source_pool_id": str(lot.id), "quantity": "500"}]
    a = service.save_event(db, org.id, rep.id, data)
    b = service.save_event(db, org.id, rep.id, data)
    db.commit()
    org_id = org.id
    rep_id = rep.id
    ids = [a.id, b.id]
    db.rollback()

    def reserve(event_id):
        worker = SessionLocal()
        try:
            service.dispatch(worker, org_id, rep_id, event_id, {"actual_date": "2026-10-21"}, str(uuid4()))
            worker.commit()
            return "ok"
        except service.TastingError:
            worker.rollback()
            return "insufficient"
        finally:
            worker.close()

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(reserve, ids))
    assert sorted(results) == ["insufficient", "ok"]
    db.refresh(lot)
    assert lot.reserved_volume_ml == 500 and lot.remaining_volume_ml == 700


def test_own_venue_records_removal_and_pack_volume_blocks_unknown_conversion(db, world):
    org, rep, item, profile, *_ = world
    data = payload(rep, item)
    data["venue_type"] = "own"
    event = service.save_event(db, org.id, rep.id, data)
    profile.pack_volume_ml = None
    db.commit()
    with pytest.raises(service.TastingError, match="pack size"):
        service.dispatch(db, org.id, rep.id, event.id, {"actual_date": "2026-10-20"}, str(uuid4()))
    db.rollback()
    db.refresh(profile)
    profile.pack_volume_ml = 700
    db.commit()
    service.dispatch(db, org.id, rep.id, event.id, {"actual_date": "2026-10-20"}, str(uuid4()))
    db.commit()
    assert len(excise.removals_between(db, org.id, date(2026, 10, 1), date(2026, 11, 1))) == 1


def test_modern_cca_register_and_source_period_review_use_same_removal(db, world):
    from app.core.db.models.site import Site
    from app.features.compliant.models.customs_premises import CustomsCoverage, CustomsLicence
    from app.features.compliant.modules.nz_alcohol.movement_excise import cca_period_review

    org, rep, item, *_ = world
    site = db.query(Site).filter(Site.org_id == org.id, Site.is_default.is_(True)).one()
    licence = CustomsLicence(
        org_id=org.id,
        name="Producer LMA",
        number="CCA-TASTING",
        kind="lma",
        legal_entity_reference="Producer legal entity",
        valid_from=date(2026, 1, 1),
        evidence_reference="CCA evidence",
    )
    db.add(licence)
    db.flush()
    db.add(
        CustomsCoverage(
            org_id=org.id,
            licence_id=licence.id,
            site_id=site.id,
            location_id=None,
            valid_from=date(2026, 1, 1),
            evidence_reference="Dated area plan",
        )
    )
    item.site_id = site.id
    db.commit()
    dispatched(db, world)
    register = cca_movement_register(db, org.id, date(2026, 10, 1), date(2026, 11, 1))
    assert register["unresolved_movements"] == []
    assert register["licences"][0]["observed_excise_duty"] == "28.00"
    row = register["licences"][0]["movements"][0]
    assert (
        row["treatment"] == "recorded_tasting_home_consumption"
        and "tasting_stock_lot_id" in row
        and "transfer_id" not in row
    )
    review = cca_period_review(db, org.id, licence.id, date(2026, 10, 1), date(2026, 11, 1))
    assert review["movements"] == register["licences"][0]["movements"]
    assert review["total_duty"] is None and review["nil_return"] is None and not review["complete_lodgement"]


def test_dispatch_signed_movement_and_livesync_events_are_atomic_and_replay_safe(db, world):
    from sqlalchemy import func

    from app.core.db.models.entity_event import EntityEvent
    from app.core.db.models.inventory_movement import InventoryMovement

    org, rep, item, *_ = world
    event = create(db, world)
    db.commit()
    key = str(uuid4())
    body = {"actual_date": "2026-10-20"}
    before = (
        db.query(func.coalesce(func.sum(InventoryMovement.quantity), 0))
        .filter(InventoryMovement.org_id == org.id, InventoryMovement.inventory_item_id == item.id)
        .scalar()
    )
    service.dispatch(db, org.id, rep.id, event.id, body, key)
    db.commit()
    service.dispatch(db, org.id, rep.id, event.id, body, key)
    db.commit()
    movements = (
        db.query(InventoryMovement)
        .filter(
            InventoryMovement.org_id == org.id,
            InventoryMovement.movement_metadata["reason"].astext == "tasting_dispatch",
        )
        .all()
    )
    assert len(movements) == 1 and movements[0].quantity == -2
    assert movements[0].unit == "bottles"
    assert movements[0].movement_metadata["tasting_id"] == str(event.id)
    after = (
        db.query(func.sum(InventoryMovement.quantity))
        .filter(InventoryMovement.org_id == org.id, InventoryMovement.inventory_item_id == item.id)
        .scalar()
    )
    assert after - before == Decimal("-2")
    assert (
        db.query(EntityEvent)
        .filter(EntityEvent.org_id == org.id, EntityEvent.event_type == "tasting.dispatched")
        .count()
        == 1
    )
    events = (
        db.query(EntityEvent)
        .filter(
            EntityEvent.org_id == org.id,
            EntityEvent.event_type == "inventory_item.quantity_adjusted",
            EntityEvent.payload["reason"].astext == "tasting_dispatch",
        )
        .all()
    )
    assert len(events) == 1 and events[0].actor_id == rep.id and Decimal(events[0].payload["delta"]) == Decimal("-2")


def test_frozen_removal_facts_are_database_immutable(db, world):
    from sqlalchemy import text
    from sqlalchemy.exc import DBAPIError

    org, rep, *_ = world
    dispatched(db, world)
    lot = db.query(TastingStockLot).filter_by(org_id=org.id).one()
    with pytest.raises(DBAPIError, match="immutable"):
        db.execute(text("UPDATE tasting_stock_lots SET snapshot = '{}'::jsonb WHERE id = :id"), {"id": lot.id})
    db.rollback()


def test_stock_sources_remain_same_org_and_library_is_never_tasting_pool(db, world):
    org, rep, item, *_ = world
    hostile = OrganisationFactory()
    foreign = InventoryItemFactory(
        org_id=hostile.id,
        name="Foreign Gin",
        unit="bottles",
        inventory_type="final_product",
        extra_data={"opening_stock": True},
    )
    library = InventoryItemFactory(
        org_id=org.id,
        name="Sampling Gin - Library Stock",
        unit="bottles",
        inventory_type="final_product",
        extra_data={"opening_stock": True},
    )
    raw = InventoryItemFactory(org_id=org.id, name="Spirit ingredient", unit="L", inventory_type="raw_material")
    db.commit()
    for source in (foreign, library, raw):
        data = payload(rep, source)
        with pytest.raises(service.TastingError, match="producer-owned"):
            service.save_event(db, org.id, rep.id, data)


def test_backdated_unresolved_capture_blocks_next_period_nil(db, world):
    org, rep, item, profile, rate = world
    excise.lodge(
        db, org.id, date(2026, 9, 1), "monthly", date(2026, 10, 10), "NIL-BEFORE", rep.id, today=date(2026, 10, 20)
    )
    db.commit()
    rate.rate_per_lal = 100
    rate.effective_from = date(2026, 10, 1)
    profile.abv_percent = None
    item.extra_data = {"opening_stock": True}
    db.commit()
    dispatched(db, world, actual_date="2026-09-25")
    current = excise.draft(db, org.id, date(2026, 10, 1), "monthly", today=date(2026, 11, 1))
    assert current["adjustments"][0]["unresolved"] and current["problems"] and not current["entry"]["complete"]
    with pytest.raises(ValueError, match="Resolve"):
        excise.lodge(
            db, org.id, date(2026, 10, 1), "monthly", date(2026, 11, 1), "BLOCKED", rep.id, today=date(2026, 11, 1)
        )


def test_rate_rollover_uses_each_physical_dispatch_date_and_metadata_library_is_excluded(db, world):
    org, rep, item, *_ = world
    db.add(ExciseRate(org_id=org.id, tariff_item="TEST-TASTING", rate_per_lal="100", effective_from=date(2026, 10, 1)))
    library = InventoryItemFactory(
        org_id=org.id,
        name="Custom Quality Room",
        unit="bottles",
        inventory_type="final_product",
        extra_data={"opening_stock": True, "library_stock": True},
    )
    db.commit()
    with pytest.raises(service.TastingError, match="producer-owned"):
        service.save_event(db, org.id, rep.id, payload(rep, library))
    dispatched(db, world, actual_date="2026-09-30")
    dispatched(db, world, actual_date="2026-10-01")
    lots = db.query(TastingStockLot).filter_by(org_id=org.id).order_by(TastingStockLot.removed_on).all()
    assert [Decimal(lot.snapshot["duty"]) for lot in lots] == [Decimal("28"), Decimal("56")]
    assert all(lot.snapshot["recorded_by"] == str(rep.id) for lot in lots)


def test_booking_without_stock_does_not_allow_dispatch(db, world):
    org, rep, item, *_ = world
    data = payload(rep, item)
    data["allocations"] = []
    event = service.save_event(db, org.id, rep.id, data)
    db.commit()
    with pytest.raises(service.TastingError, match="Allocate stock before dispatch"):
        service.dispatch(db, org.id, rep.id, event.id, {"actual_date": "2026-10-20"}, str(uuid4()))
    db.rollback()
    assert event.status == "planned"
    assert item.quantity == 10
    assert db.query(TastingStockLot).filter_by(org_id=org.id).count() == 0


@pytest.mark.parametrize("notes", [None, "Customers liked the citrus finish"])
def test_outcome_keeps_plan_instructions_and_separate_outcome_notes(db, world, notes):
    org, rep, *_ = world
    event = dispatched(db, world, "1")
    line = db.query(TastingAllocation).filter_by(org_id=org.id, tasting_id=event.id).one()
    body = {"usage": [{"allocation_id": str(line.id), "used_volume_ml": "100"}]}
    if notes is not None:
        body["notes"] = notes
    service.finalise(db, org.id, rep.id, event.id, body)
    db.commit()
    service.finalise(db, org.id, rep.id, event.id, body)
    db.commit()
    detail = service.event_dict(db, event)
    assert detail["notes"] == "Brand sampling"
    assert detail["outcome_notes"] == (notes or "")
    assert db.query(TastingStockLot).filter_by(org_id=org.id).one().remaining_volume_ml == 600


@pytest.mark.parametrize("balance", ["4", "1"])
def test_coalesced_prior_removals_reject_ambiguity_without_server_error_or_debit(db, world, balance):
    from app.core.db.models.stock_location import StockLocation
    from app.core.db.repositories.inventory_repo import InventoryRepository

    org, rep, item, *_ = world
    item.supplier_batch_number = "REPEATED-REMOVAL-BATCH"
    location = StockLocation(org_id=org.id, name="Rep's existing stock", inside_licensed_area=False)
    db.add(location)
    db.commit()
    inventory = InventoryRepository(db)
    moved, _ = inventory.move_lot(org.id, item.id, "2", location.id, date(2026, 10, 19), user_id=rep.id)
    repeated, _ = inventory.move_lot(org.id, item.id, "2", location.id, date(2026, 10, 19), user_id=rep.id)
    assert moved.id == repeated.id
    inventory.set_inventory_item_quantity(moved.id, org.id, balance)
    data = payload(rep, moved, "1")
    event = service.save_event(db, org.id, rep.id, data)
    db.commit()
    with pytest.raises(service.TastingError, match="one attributable prior removal") as caught:
        service.dispatch(db, org.id, rep.id, event.id, {"actual_date": "2026-10-20"}, str(uuid4()))
    assert caught.value.status == 400
    db.rollback()
    assert moved.quantity == Decimal(balance)
    assert db.query(TastingStockLot).filter_by(org_id=org.id).count() == 0
