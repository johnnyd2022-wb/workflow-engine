"""Rough capacity detects site overload without granting production clearance."""

from datetime import date, timedelta
from uuid import uuid4

import pytest

from app.core.db.models.site import Site
from app.core.db.models.step import Step
from app.core.security.access_policy import requirement_for
from app.features.planning.capacity_models import PlanningCapacitySetting
from app.features.planning.capacity_service import review, save_setting
from tests.features.planning import test_batches as batch_fixtures

demand_world = batch_fixtures.demand_world
base_demand_world = batch_fixtures.base_demand_world
demand_clients = batch_fixtures.demand_clients
flask_app = batch_fixtures.flask_app


def _payload(step_id, capacity=120, **changes):
    group_id = str(uuid4())
    return {
        "groups": [{"id": group_id, "name": "Bottling line", "minutes_per_day": capacity}],
        "assignments": [{"step_id": str(step_id), "group_id": group_id}],
        "expected_revision": 0,
        **changes,
    }


def test_three_batches_overload_one_day_and_suggest_low_priority_unpinned(db, demand_world):
    org_id = demand_world[0]
    site = Site(org_id=org_id, name="Main", is_default=True)
    db.add(site)
    db.flush()
    _, _, _, rows = batch_fixtures.planned(db, demand_world)
    step = db.query(Step).filter(Step.org_id == org_id).one()
    saved = save_setting(db, org_id, site.id, _payload(step.id))
    assert saved.revision == 1
    result = review(db, org_id, date.today(), date.today())
    assert len(result["days"]) == 1
    day = result["days"][0]
    assert day["load_minutes"] == 180 and day["capacity_minutes"] == 120 and day["overloaded"]
    assert day["suggest_move_batch_id"] in {str(row.id) for row in rows}
    assert result["unresolved"] == []
    assert not result["complete_capacity_clearance"] and result["forecast_ready_date"] is None
    assert not result["reservations_created"]
    rows[0].pinned = True
    db.flush()
    assert review(db, org_id, date.today(), date.today())["days"][0]["suggest_move_batch_id"] != str(rows[0].id)


def test_unassigned_or_missing_site_capacity_is_explicitly_unresolved(db, demand_world):
    org_id = demand_world[0]
    _, _, _, rows = batch_fixtures.planned(db, demand_world)
    result = review(db, org_id, date.today(), date.today())
    assert not result["days"] and len(result["unresolved"]) == len(rows)
    assert result["complete_capacity_clearance"] is False


def test_capacity_setting_is_tenant_scoped_and_revision_checked(db, demand_world):
    ours, foreign = demand_world[:2]
    our_site = Site(org_id=ours, name="Main", is_default=True)
    foreign_site = Site(org_id=foreign, name="Other", is_default=True)
    db.add_all([our_site, foreign_site])
    db.flush()
    step = db.query(Step).filter(Step.org_id == ours).one()
    with pytest.raises(ValueError, match="this business"):
        save_setting(db, ours, foreign_site.id, _payload(step.id))
    row = save_setting(db, ours, our_site.id, _payload(step.id))
    with pytest.raises(ValueError, match="changed"):
        save_setting(db, ours, our_site.id, _payload(step.id))
    assert row.revision == 1
    assert db.query(PlanningCapacitySetting).filter(PlanningCapacitySetting.org_id == foreign).count() == 0


@pytest.mark.parametrize(
    "change",
    [
        {"groups": [{"id": str(uuid4()), "name": "Still", "minutes_per_day": 0}]},
        {"groups": [{"id": str(uuid4()), "name": "Still", "minutes_per_day": True}]},
        {"groups": [{"id": str(uuid4()), "name": "Still", "minutes_per_day": 1441}]},
        {"assignments": [{"step_id": str(uuid4()), "group_id": str(uuid4())}]},
        {"expected_revision": True},
    ],
)
def test_bad_capacity_config_never_persists(db, demand_world, change):
    org_id = demand_world[0]
    site = Site(org_id=org_id, name="Main", is_default=True)
    db.add(site)
    db.flush()
    step = db.query(Step).filter(Step.org_id == org_id).one()
    with pytest.raises(ValueError):
        save_setting(db, org_id, site.id, _payload(step.id, **change))
    assert db.query(PlanningCapacitySetting).count() == 0


def test_capacity_period_is_bounded(db, demand_world):
    org_id = demand_world[0]
    with pytest.raises(ValueError):
        review(db, org_id, date.today(), date.today() + timedelta(days=31))
    with pytest.raises(ValueError):
        review(db, org_id, date.today(), date.today() - timedelta(days=1))


def test_capacity_routes_scope_settings_to_staff_and_tenant(db, demand_clients):
    assert requirement_for("planning.get_capacity", "GET") == "production.view"
    assert requirement_for("planning.save_capacity", "POST") == "production.record"
    producer, org_id, _ = demand_clients[0]
    neighbour = demand_clients[1][0]
    auditor = demand_clients[2][0]
    site = Site(org_id=org_id, name="Main", is_default=True)
    db.add(site)
    db.commit()
    try:
        step = db.query(Step).filter(Step.org_id == org_id).one()
        path = f"/api/core/planner/capacity/sites/{site.id}"
        assert neighbour.post(path, json=_payload(step.id)).status_code == 400
        assert auditor.post(path, json=_payload(step.id)).status_code == 403
        saved = producer.post(path, json=_payload(step.id))
        assert saved.status_code == 200
        assert saved.get_json()["setting"]["site_id"] == str(site.id)
        response = producer.get(
            "/api/core/planner/capacity",
            query_string={"start": "2026-09-01", "end": "2026-09-07"},
        )
        assert response.status_code == 200
        assert response.get_json()["settings"][0]["site_id"] == str(site.id)
        assert (
            neighbour.get(
                "/api/core/planner/capacity", query_string={"start": "2026-09-01", "end": "2026-09-07"}
            ).get_json()["settings"]
            == []
        )
        assert (
            producer.get(
                "/api/core/planner/capacity", query_string={"start": "2026-09-01", "end": "2027-09-01"}
            ).status_code
            == 400
        )
    finally:
        db.rollback()
        db.query(PlanningCapacitySetting).filter(PlanningCapacitySetting.org_id == org_id).delete()
        db.query(Site).filter(Site.org_id == org_id).delete()
        db.commit()


def test_resource_calendar_closes_weekdays_and_specific_dates_without_moving_batches(db, demand_world):
    org_id = demand_world[0]
    site = Site(org_id=org_id, name="Main", is_default=True)
    db.add(site)
    db.flush()
    _, _, _, rows = batch_fixtures.planned(db, demand_world)
    step = db.query(Step).filter(Step.org_id == org_id).one()
    data = _payload(step.id, capacity=240)
    data["groups"][0].update(working_days=list(range(7)), closed_dates=[date.today().isoformat()])
    saved = save_setting(db, org_id, site.id, data)
    closed = review(db, org_id, date.today(), date.today())["days"][0]
    assert closed["capacity_minutes"] == 0 and closed["calendar_closed"] and closed["overloaded"]
    assert closed["load_minutes"] == 180
    assert all(row.proposed_start_date == date.today() for row in rows)
    data["expected_revision"] = saved.revision
    data["groups"][0]["closed_dates"] = []
    data["groups"][0]["working_days"] = [day for day in range(7) if day != date.today().weekday()]
    saved = save_setting(db, org_id, site.id, data)
    assert review(db, org_id, date.today(), date.today())["days"][0]["calendar_closed"]
    data["expected_revision"] = saved.revision
    data["groups"][0]["working_days"] = list(range(7))
    save_setting(db, org_id, site.id, data)
    opened = review(db, org_id, date.today(), date.today())["days"][0]
    assert opened["capacity_minutes"] == 240 and not opened["calendar_closed"] and not opened["overloaded"]


@pytest.mark.parametrize(
    "calendar",
    [
        {"working_days": [True]},
        {"working_days": [7]},
        {"working_days": [1, 1]},
        {"working_days": "Monday"},
        {"closed_dates": ["2026-02-30"]},
        {"closed_dates": ["20260101"]},
        {"closed_dates": ["2026-01-01", "2026-01-01"]},
        {"closed_dates": [True]},
        {"closed_dates": "2026-01-01"},
    ],
)
def test_invalid_resource_calendars_do_not_persist(db, demand_world, calendar):
    org_id = demand_world[0]
    site = Site(org_id=org_id, name="Main", is_default=True)
    db.add(site)
    db.flush()
    step = db.query(Step).filter(Step.org_id == org_id).one()
    data = _payload(step.id)
    data["groups"][0].update(calendar)
    with pytest.raises(ValueError):
        save_setting(db, org_id, site.id, data)
    assert db.query(PlanningCapacitySetting).filter_by(org_id=org_id).count() == 0


def test_empty_work_week_and_legacy_calendar_defaults(db, demand_world):
    org_id = demand_world[0]
    site = Site(org_id=org_id, name="Main", is_default=True)
    db.add(site)
    db.flush()
    _, _, _, _ = batch_fixtures.planned(db, demand_world)
    step = db.query(Step).filter(Step.org_id == org_id).one()
    data = _payload(step.id, capacity=240)
    saved = save_setting(db, org_id, site.id, data)
    assert saved.config["groups"][0]["working_days"] == list(range(7))
    # Old persisted configurations have no calendar fields and keep all-day capacity.
    saved.config = {"groups": data["groups"], "assignments": data["assignments"]}
    db.flush()
    assert not review(db, org_id, date.today(), date.today())["days"][0]["overloaded"]
    data["expected_revision"] = saved.revision
    data["groups"][0]["working_days"] = []
    save_setting(db, org_id, site.id, data)
    assert review(db, org_id, date.today(), date.today())["days"][0]["calendar_closed"]
