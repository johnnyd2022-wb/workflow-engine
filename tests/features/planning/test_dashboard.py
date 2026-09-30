"""Today's priorities follow current planning state and production permission."""

from datetime import timedelta
from decimal import Decimal

from app.core.db.models.user import User, UserRole
from app.features.planning import batch_service
from app.features.planning.dashboard_service import MAX_DASHBOARD_BATCHES, today_work
from tests.features.planning import test_batches as fixtures

board_clients = fixtures.board_clients
demand_clients = fixtures.demand_clients
flask_app = fixtures.flask_app
demand_world = fixtures.demand_world
base_demand_world = fixtures.base_demand_world
TODAY = fixtures.TODAY


def test_today_priorities_exclude_other_org_future_closed_and_cancelled_work(db, demand_world):
    org_id, _, demand, rows = fixtures.planned(db, demand_world)
    rows[0].priority = 80
    rows[0].pinned = True
    rows[0].proposed_start_date = TODAY - timedelta(days=1)
    rows[1].proposed_start_date = TODAY + timedelta(days=1)
    rows[2].status = "cancelled"
    other, _, _ = demand_world
    _, foreign, outputs = demand_world
    fixtures.planned(db, (foreign, other, outputs))
    db.flush()
    result = today_work(db, org_id, TODAY)
    assert result["total"] == 1 and not result["truncated"]
    item = result["items"][0]
    assert item["id"] == str(rows[0].id) and item["priority"] == 80
    assert item["pinned"] and item["overdue"] and item["status"] == "blocked"
    assert "snapshot" not in item and "forecast_ready_date" not in item
    demand.status = "cancelled"
    db.flush()
    assert today_work(db, org_id, TODAY)["items"] == []


def test_today_priorities_are_bounded_and_ordered_by_current_priority(db, demand_world):
    org_id, _, demand = fixtures.configured(db, demand_world)
    demand.quantity = Decimal("5500")
    db.flush()
    rows, _ = batch_service.plan_demand(db, org_id, demand.id, {}, today=TODAY)
    rows[-1].priority = 100
    db.flush()
    result = today_work(db, org_id, TODAY)
    assert result["total"] == 22 and result["truncated"]
    assert len(result["items"]) == MAX_DASHBOARD_BATCHES
    assert result["items"][0]["id"] == str(rows[-1].id)
    assert [row["batch_number"] for row in result["items"][1:]] == list(range(1, 20))


def test_dashboard_does_not_read_planning_or_render_cards_without_permission(board_clients, db, monkeypatch):
    from app.features.planning import dashboard_service

    client, org_id, output = board_clients[0]
    demand = fixtures.configure_http(db, client, output)
    planned = client.post(f"/api/core/planner/demands/{demand['id']}/plan", json={})
    assert planned.status_code == 201
    summary = client.get("/api/core/dashboard/summary")
    assert summary.status_code == 200, summary.get_json()
    assert summary.get_json()["planned_work"]["total"] == 3
    assert "data-planned-work-list" in client.get("/core/dashboard").get_data(as_text=True)
    user = db.query(User).filter_by(org_id=org_id).one()
    user.role = UserRole.SALES
    db.commit()

    def forbidden(*args, **kwargs):
        raise AssertionError("Sales-only staff must never query planned production")

    monkeypatch.setattr(dashboard_service, "today_work", forbidden)
    response = client.get("/api/core/dashboard/summary")
    assert response.status_code == 200 and response.get_json()["planned_work"] is None
    assert "data-planned-work-list" not in client.get("/core/dashboard").get_data(as_text=True)
