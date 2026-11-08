"""GL-P07 B4: capacity units and placement, the real start check, and automatic replanning."""

from datetime import timedelta
from uuid import uuid4

import pytest

from app.core.db.models.execution import Execution
from app.core.db.models.execution_step import ExecutionStep, ExecutionStepStatus
from app.core.db.models.site import Site
from app.core.db.models.step import Step
from app.core.security.access_policy import requirement_for
from app.core.services.lot_holds import place_hold
from app.features.compliant.models.compliance_profile import ComplianceProfile
from app.features.compliant.models.food_registration import FoodRegistration, FoodRegistrationSite
from app.features.planning import batch_service, capacity_service, demand_service, start_service
from app.features.planning import material_adapter as adapter
from app.features.planning.batch_models import PlanningBatch, PlanningReplanEvent
from app.features.planning.forecast_models import PlanningMaterialCommitment
from app.features.planning.replan import replan
from tests.features.planning import test_batches as fixtures
from tests.features.planning import test_material_adapter as materials

demand_world = fixtures.demand_world
base_demand_world = fixtures.base_demand_world
TODAY = fixtures.TODAY


def _site(db, org_id):
    site = db.query(Site).filter(Site.org_id == org_id, Site.is_default.is_(True)).one_or_none()
    if site is None:
        site = Site(org_id=org_id, name="Main distillery", is_default=True)
        db.add(site)
        db.flush()
    return site


def _capacity(db, org_id, site, *, minutes=60, units=1, revision=0):
    """One still; the workflow's single step (60 minutes of work) runs on it."""
    step = db.query(Step).filter(Step.org_id == org_id).first()
    group = str(uuid4())
    return capacity_service.save_setting(
        db,
        org_id,
        site.id,
        {
            "groups": [{"id": group, "name": "Still", "minutes_per_day": minutes, "units": units}],
            "assignments": [{"step_id": str(step.id), "group_id": group}],
            "expected_revision": revision,
        },
    )


def _demand(db, org_id, output_id, quantity, due_in_days, reference="ORDER", priority=0):
    return demand_service.create_demand(
        db,
        org_id,
        fixtures.payload(
            output_id,
            reference=reference,
            quantity=str(quantity),
            due_date=(TODAY + timedelta(days=due_in_days)).isoformat(),
            priority=priority,
        ),
    )


def _setup(db, world, **capacity):
    """250-bottle batches, 60 minutes on the still then a 2-day wait; a default site with a still."""
    org_id, _, outputs = world
    step = db.query(Step).filter(Step.org_id == org_id).first()
    fixtures.native_recipe(db, org_id, step.process_id)
    batch_service.save_setting(db, org_id, step.process_id, fixtures.setting_payload(db, org_id, outputs[org_id]))
    site = _site(db, org_id)
    if capacity is not None:
        _capacity(db, org_id, site, **capacity)
    return org_id, outputs[org_id], site


# --- capacity units -----------------------------------------------------------------------


@pytest.mark.parametrize("units", [0, 51, True, "2", 1.5])
def test_units_must_be_a_whole_number_from_1_to_50(db, demand_world, units):
    org_id = demand_world[0]
    site = _site(db, org_id)
    with pytest.raises(ValueError, match="Units"):
        _capacity(db, org_id, site, units=units)


def test_units_multiply_a_groups_daily_capacity(db, demand_world):
    org_id, output_id, site = _setup(db, demand_world, minutes=60, units=3)
    _demand(db, org_id, output_id, 750, 2)
    review = capacity_service.review(db, org_id, TODAY, TODAY + timedelta(days=3))
    assert review["settings"][0]["groups"][0]["units"] == 3
    # Planning hasn't happened yet: nothing loaded. Plan and look again.
    demand = db.query(batch_service.PlanningDemand).filter_by(org_id=org_id).one()
    batch_service.plan_demand(db, org_id, demand.id, {}, today=TODAY)
    days = capacity_service.review(db, org_id, TODAY, TODAY + timedelta(days=3))["days"]
    assert [(row["day"], row["load_minutes"], row["capacity_minutes"], row["overloaded"]) for row in days] == [
        (TODAY.isoformat(), 180, 180, False)
    ]


# --- placement ------------------------------------------------------------------------------


def test_batches_are_placed_one_a_day_on_a_single_still_latest_on_time_first(db, demand_world):
    org_id, output_id, _ = _setup(db, demand_world, units=1)
    demand = _demand(db, org_id, output_id, 750, 6)  # 3 batches, due in 6 days, 2 days to make
    rows, _ = batch_service.plan_demand(db, org_id, demand.id, {}, today=TODAY)
    starts = [(row.proposed_start_date - TODAY).days for row in rows]
    assert starts == [4, 3, 2]  # latest start that is still on time, one still, one at a time
    assert all(row.theoretical_ready_date <= demand.due_date for row in rows)


def test_two_stills_run_two_batches_a_day(db, demand_world):
    org_id, output_id, _ = _setup(db, demand_world, units=2)
    demand = _demand(db, org_id, output_id, 750, 6)
    rows, _ = batch_service.plan_demand(db, org_id, demand.id, {}, today=TODAY)
    assert sorted((row.proposed_start_date - TODAY).days for row in rows) == [3, 4, 4]


def test_when_nothing_fits_on_time_the_batch_is_late_and_says_capacity(db, demand_world):
    org_id, output_id, _ = _setup(db, demand_world, units=1)
    demand = _demand(db, org_id, output_id, 750, 2)  # due in 2 days: only today is on time
    rows, _ = batch_service.plan_demand(db, org_id, demand.id, {}, today=TODAY)
    assert [(row.proposed_start_date - TODAY).days for row in rows] == [0, 1, 2]
    assert rows[1].snapshot["timing_reason"].startswith("Capacity is full until then; ready")
    assert rows[1].snapshot["timing_reason"].endswith("(late)")


def test_a_site_without_capacity_settings_is_not_constrained(db, demand_world):
    org_id, output_id, site = _setup(db, demand_world, units=1)
    db.query(capacity_service.PlanningCapacitySetting).filter_by(org_id=org_id).delete()
    demand = _demand(db, org_id, output_id, 750, 6)
    rows, _ = batch_service.plan_demand(db, org_id, demand.id, {}, today=TODAY)
    assert {(row.proposed_start_date - TODAY).days for row in rows} == {4}


# --- the start check ------------------------------------------------------------------------


def _assessed(db, world, monkeypatch, **capacity):
    """B2's material fixture (2 kg sugar per batch from a 5 kg bound lot), checked."""
    _site(db, world[0])  # the default site exists before planning, as in a real business
    org_id, *_, own, _, _, setting, batches = materials.prepare(db, world)
    materials.trusted_boundary(monkeypatch)
    adapter.assess(db, org_id, {}, today=TODAY)
    return org_id, own, batches


def test_a_batch_whose_materials_were_never_checked_cannot_start(db, demand_world):
    org_id, *_, batches = materials.prepare(db, demand_world)
    batches[0].blockers = []  # a cleared flag is not a check
    assert start_service.evaluate_start(db, org_id, batches[0]).blockers == ("Materials have not been checked",)


def test_a_short_batch_cannot_start(db, demand_world, monkeypatch):
    org_id, _, batches = _assessed(db, demand_world, monkeypatch)
    assert start_service.evaluate_start(db, org_id, batches[2]).blockers == ("Not enough materials to start",)


def test_held_and_on_hand_materials_clear_the_start_and_start_consumes_them(db, demand_world, monkeypatch):
    org_id, own, batches = _assessed(db, demand_world, monkeypatch)
    assert start_service.evaluate_start(db, org_id, batches[0]).blockers == ()
    result, changed = start_service.start_batch(db, org_id, batches[0].id, {"expected_revision": 1}, "b4-start-1")
    assert changed and batches[0].status == "started"
    execution = db.query(Execution).filter(Execution.id == batches[0].execution_id).one()
    assert execution.site_id == batches[0].site_id
    statuses = {
        row.status
        for row in db.query(PlanningMaterialCommitment).filter(PlanningMaterialCommitment.batch_id == batches[0].id)
    }
    assert statuses == {"consumed"}


def test_a_lot_put_on_quality_hold_after_the_check_blocks_the_start(db, demand_world, monkeypatch):
    org_id, own, batches = _assessed(db, demand_world, monkeypatch)
    place_hold(db, org_id, own.id, "Off smell", None)
    db.flush()
    assert start_service.evaluate_start(db, org_id, batches[0]).blockers == (
        "The Sugar lot is on quality hold: Off smell",
    )
    with pytest.raises(batch_service.PlanningConflictError, match="quality hold"):
        start_service.start_batch(db, org_id, batches[0].id, {"expected_revision": 1}, "b4-start-2")


def test_stock_used_since_the_check_blocks_the_start(db, demand_world, monkeypatch):
    from app.core.db.repositories.inventory_repo import InventoryRepository

    org_id, own, batches = _assessed(db, demand_world, monkeypatch)
    InventoryRepository(db).set_inventory_item_quantity(own.id, org_id, "1", commit=False)
    db.flush()
    assert start_service.evaluate_start(db, org_id, batches[0]).blockers == (
        "Only 1 kg of Sugar is left on hand; this batch holds 2 kg",
    )


def test_started_batch_commitment_is_reserved_until_its_inputs_are_recorded(db, demand_world, monkeypatch):
    """A 3 kg lot cannot start two batches each holding 2 kg, including before input capture."""
    from app.core.db.repositories.inventory_repo import InventoryRepository

    org_id, own, batches = _assessed(db, demand_world, monkeypatch)
    InventoryRepository(db).set_inventory_item_quantity(own.id, org_id, "3", commit=False)
    db.flush()

    assert start_service.evaluate_start(db, org_id, batches[0]).blockers == ()
    start_service.start_batch(db, org_id, batches[0].id, {"expected_revision": 1}, "b4-start-commitment")
    assert start_service.evaluate_start(db, org_id, batches[1]).blockers == (
        "Only 1 kg of Sugar is left on hand; this batch holds 2 kg",
    )

    execution_step = (
        db.query(ExecutionStep)
        .filter(ExecutionStep.org_id == org_id, ExecutionStep.execution_id == batches[0].execution_id)
        .one()
    )
    execution_step.status = ExecutionStepStatus.IN_PROGRESS
    execution_step.actual_inputs = [{"inventory_item_id": str(own.id), "quantity": "2", "unit": "kg"}]
    db.flush()
    # Pending actual inputs take over from the consumed reservation; they are not charged twice.
    assert start_service.evaluate_start(db, org_id, batches[1]).blockers == (
        "Only 1 kg of Sugar is left on hand; this batch holds 2 kg",
    )


def test_a_full_still_blocks_the_start(db, demand_world, monkeypatch):
    org_id, own, batches = _assessed(db, demand_world, monkeypatch)
    site = _site(db, org_id)
    _capacity(db, org_id, site, minutes=60, units=1)
    for row in batches:
        row.site_id = site.id
        row.proposed_start_date = TODAY
    db.flush()
    # Three batches on one still today: each sees the other two taking its minutes.
    assert start_service.evaluate_start(db, org_id, batches[0]).blockers == (
        f"Still is full on {TODAY.day} {TODAY:%b} (180 of 60 minutes)",
    )


def test_the_sites_compliance_module_can_block_the_start(db, demand_world, monkeypatch):
    org_id, own, batches = _assessed(db, demand_world, monkeypatch)
    site = _site(db, org_id)
    batches[0].site_id = site.id
    db.add(ComplianceProfile(org_id=org_id, enabled=True, industry_module="nz_alcohol", settings={}))
    db.flush()
    assert start_service.evaluate_start(db, org_id, batches[0]).blockers == (
        f"No food registration covers manufacturing at Main distillery on {TODAY.day} {TODAY:%b}; "
        "record it under Compliance, Food registrations",
    )
    registration = FoodRegistration(
        org_id=org_id,
        reference="NP3-1",
        name="Distillery",
        programme="np3",
        registered_on=TODAY - timedelta(days=30),
        registered_as="existing",
        evidence_reference="MPI letter",
    )
    db.add(registration)
    db.flush()
    db.add(
        FoodRegistrationSite(
            org_id=org_id,
            registration_id=registration.id,
            site_id=site.id,
            activity="manufacturing",
            evidence_reference="MPI letter",
        )
    )
    db.flush()
    assert start_service.evaluate_start(db, org_id, batches[0]).blockers == ()


# --- replanning ---------------------------------------------------------------------------


def _events(db, org_id):
    return (
        db.query(PlanningReplanEvent)
        .filter(PlanningReplanEvent.org_id == org_id)
        .order_by(PlanningReplanEvent.created_at, PlanningReplanEvent.id)
        .all()
    )


def test_replan_moves_the_unpinned_batch_off_a_full_day_and_keeps_the_pinned_one(db, demand_world):
    org_id, output_id, site = _setup(db, demand_world, units=2)
    first = _demand(db, org_id, output_id, 250, 6, "FIRST", priority=50)
    second = _demand(db, org_id, output_id, 250, 6, "SECOND", priority=10)
    (a,), _ = batch_service.plan_demand(db, org_id, first.id, {}, today=TODAY)
    (b,), _ = batch_service.plan_demand(db, org_id, second.id, {}, today=TODAY)
    assert a.proposed_start_date == b.proposed_start_date == TODAY + timedelta(days=4)
    a.pinned = True
    db.flush()
    _capacity(db, org_id, site, units=1, revision=1)  # one still is out of service
    events = replan(db, org_id, today=TODAY, trigger="test")
    assert a.proposed_start_date == TODAY + timedelta(days=4)  # pinned: stays
    assert b.proposed_start_date == TODAY + timedelta(days=3)
    assert [(event.kind, event.batch_id, event.reason) for event in events] == [
        (
            "moved",
            b.id,
            f"Still was full on {(TODAY + timedelta(days=4)).day} {(TODAY + timedelta(days=4)):%b} (120 of 60 minutes)",
        )
    ]
    assert replan(db, org_id, today=TODAY, trigger="test") == []  # nothing changed: nothing to do


def test_replan_leaves_a_batch_a_person_placed(db, demand_world):
    org_id, output_id, site = _setup(db, demand_world, units=2)
    first = _demand(db, org_id, output_id, 250, 6, "FIRST", priority=50)
    second = _demand(db, org_id, output_id, 250, 6, "SECOND", priority=10)
    (a,), _ = batch_service.plan_demand(db, org_id, first.id, {}, today=TODAY)
    (b,), _ = batch_service.plan_demand(db, org_id, second.id, {}, today=TODAY)
    batch_service.update_batch(
        db,
        org_id,
        b.id,
        {"action": "reschedule", "expected_revision": 1, "start_date": (TODAY + timedelta(days=4)).isoformat()},
        today=TODAY,
    )
    _capacity(db, org_id, site, units=1, revision=1)
    events = replan(db, org_id, today=TODAY, trigger="test")
    assert b.proposed_start_date == TODAY + timedelta(days=4)  # someone chose it
    assert [(event.kind, event.batch_id) for event in events] == [("moved", a.id)]


def test_replan_cancels_batches_stock_now_covers_and_adds_them_back_when_it_goes(db, demand_world):
    org_id, output_id, site = _setup(db, demand_world, units=5)
    demand = _demand(db, org_id, output_id, 500, 6)
    rows, _ = batch_service.plan_demand(db, org_id, demand.id, {}, today=TODAY)
    assert len(rows) == 2
    from tests.features.planning.test_demand_sources import _stock

    lot = _stock(db, org_id, output_id, 300, site_id=site.id)
    events = replan(db, org_id, today=TODAY, trigger="test")
    assert [event.kind for event in events] == ["cancelled"]
    assert sorted(row.status for row in rows) == ["blocked", "cancelled"]
    assert events[0].reason == "Stock on hand and other batches now cover it"
    place_hold(db, org_id, lot.id, "Failed QC", None)  # the stock can't be used after all
    db.flush()
    events = replan(db, org_id, today=TODAY, trigger="test")
    assert [event.kind for event in events] == ["added"]
    live = db.query(PlanningBatch).filter(PlanningBatch.demand_id == demand.id, PlanningBatch.status != "cancelled")
    assert live.count() == 2


def test_replan_moves_a_batch_whose_start_day_passed_but_not_a_pinned_one(db, demand_world):
    org_id, output_id, _ = _setup(db, demand_world, units=5)
    demand = _demand(db, org_id, output_id, 500, 6)
    first, second = batch_service.plan_demand(db, org_id, demand.id, {}, today=TODAY)[0]
    yesterday = TODAY - timedelta(days=1)
    first.proposed_start_date = second.proposed_start_date = yesterday
    second.pinned = True
    db.flush()
    events = replan(db, org_id, today=TODAY, trigger="test")
    assert first.proposed_start_date == TODAY and second.proposed_start_date == yesterday
    assert [(event.kind, event.reason) for event in events] == [
        ("moved", f"Its start day ({yesterday.day} {yesterday:%b}) passed")
    ]


def test_replan_never_touches_another_org(db, demand_world):
    org_id, output_id, _ = _setup(db, demand_world, units=5)
    demand = _demand(db, org_id, output_id, 500, 6)
    rows, _ = batch_service.plan_demand(db, org_id, demand.id, {}, today=TODAY)
    for row in rows:
        row.proposed_start_date = TODAY - timedelta(days=3)
    db.flush()
    assert replan(db, demand_world[1], today=TODAY, trigger="test") == []
    assert {row.proposed_start_date for row in rows} == {TODAY - timedelta(days=3)}
    assert _events(db, demand_world[1]) == []


def test_replan_routes_need_planner_permissions():
    assert requirement_for("planning.replan_now", "POST") == "production.record"
    assert requirement_for("planning.get_replan_events", "GET") == "production.view"
