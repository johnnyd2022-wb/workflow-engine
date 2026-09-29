"""Core Tasks: durable work records, board lanes, and due-date findings."""

from datetime import date, timedelta
from uuid import UUID, uuid4

import pytest

from app.core.backend.tasks import (
    TaskError,
    assign_task_to_lane,
    create_lane,
    create_task,
    delete_lane,
    list_lanes,
    list_tasks,
    reorder_lanes,
    task_due_summary,
    update_config,
)
from app.core.db.models.core_task import CoreTask
from app.core.db.models.organisation import Organisation
from app.core.db.models.user import User
from app.core.utils.time import utc_now
from app.features.compliance_checks.checks.tasks_due import run_tasks_due_check
from app.features.compliance_checks.system_status import _signals_from_results, derive_health_state
from app.features.crm.models.crm_task import CRMTask
from app.features.crm.models.xero_contact import XeroContact
from tests.factories import OrganisationFactory, UserFactory

# CRMTask's optional contact relationship references this table. Import it before tests
# construct CRMTask directly, as the production CRM blueprint does at application startup.
_ = XeroContact


@pytest.fixture
def task_world(db):
    """Isolated task data that remains safe after an interrupted local test run."""
    org_a = OrganisationFactory()
    org_b = OrganisationFactory()
    suffix = uuid4().hex
    user_a = UserFactory(org_id=org_a.id, email=f"core-task-a-{suffix}@example.test")
    user_b = UserFactory(org_id=org_b.id, email=f"core-task-b-{suffix}@example.test")
    db.commit()
    yield {"org_a": org_a, "org_b": org_b, "user_a": user_a, "user_b": user_b}
    db.query(User).filter(User.org_id.in_([org_a.id, org_b.id])).delete(synchronize_session=False)
    db.query(Organisation).filter(Organisation.id.in_([org_a.id, org_b.id])).delete(synchronize_session=False)
    db.commit()


def test_core_task_is_org_scoped_and_serialises_assignee(task_world, db):
    world = task_world
    task = create_task(
        db,
        world["org_a"].id,
        world["user_a"].id,
        {"title": "Prepare still", "description": "Check seals", "priority": "high", "assigned_to_user_id": str(world["user_a"].id)},
    )

    assert task["source"] == "core"
    assert task["source_label"] == "System"
    assert task["assigned_to_user_id"] == str(world["user_a"].id)
    assert [row["id"] for row in list_tasks(db, world["org_b"].id)] == []


def test_lanes_are_durable_per_board_and_reject_cross_org_assignment(task_world, db):
    world = task_world
    task = create_task(db, world["org_a"].id, world["user_a"].id, {"title": "Inspect tank"})
    lane = create_lane(db, world["org_a"].id, "core", world["user_a"].id, {"title": "Waiting on supplier"})
    lane_two = create_lane(db, world["org_a"].id, "core", world["user_a"].id, {"title": "Needs review"})
    reordered = reorder_lanes(db, world["org_a"].id, "core", [UUID(lane_two["id"]), UUID(lane["id"])])
    assert [row["title"] for row in reordered] == ["Needs review", "Waiting on supplier"]

    placement = assign_task_to_lane(db, world["org_a"].id, "core", UUID(task["id"]), UUID(lane["id"]))
    assert placement["board_lane_id"] == lane["id"]
    assert [row["title"] for row in list_lanes(db, world["org_a"].id, "core")] == ["Needs review", "Waiting on supplier"]
    assert list_lanes(db, world["org_b"].id, "core") == []

    other_lane = create_lane(db, world["org_b"].id, "core", world["user_b"].id, {"title": "Other org"})
    with pytest.raises(TaskError, match="lane not found"):
        assign_task_to_lane(
            db, world["org_a"].id, "core", UUID(task["id"]), UUID(other_lane["id"])
        )

    assert delete_lane(db, world["org_a"].id, "core", UUID(lane["id"])) is True
    refreshed = next(row for row in list_tasks(db, world["org_a"].id) if row["id"] == task["id"])
    assert refreshed["board_lane_id"] is None

    crm_task = CRMTask(org_id=world["org_a"].id, title="Customer follow-up")
    db.add(crm_task)
    db.commit()
    crm_lane = create_lane(db, world["org_a"].id, "crm", world["user_a"].id, {"title": "Awaiting customer"})
    crm_lane_two = create_lane(db, world["org_a"].id, "crm", world["user_a"].id, {"title": "Ready to call"})
    assert [row["title"] for row in reorder_lanes(db, world["org_a"].id, "crm", [UUID(crm_lane_two["id"]), UUID(crm_lane["id"])])] == [
        "Ready to call",
        "Awaiting customer",
    ]
    crm_placement = assign_task_to_lane(db, world["org_a"].id, "crm", crm_task.id, UUID(crm_lane["id"]))
    assert crm_placement["board_lane_id"] == crm_lane["id"]
    crm_row = next(row for row in list_tasks(db, world["org_a"].id, source="crm") if row["id"] == str(crm_task.id))
    assert crm_row["board_lane_id"] == crm_lane["id"]


def test_due_soon_notifications_can_be_disabled_but_overdue_is_fixed(task_world, db):
    world = task_world
    today = date.today()
    create_task(db, world["org_a"].id, world["user_a"].id, {"title": "Due soon", "due_date": (today + timedelta(days=3)).isoformat()})
    overdue = create_task(db, world["org_a"].id, world["user_a"].id, {"title": "Overdue", "due_date": (today - timedelta(days=1)).isoformat()})
    crm = CRMTask(org_id=world["org_a"].id, title="CRM due soon", due_date=today + timedelta(days=2))
    db.add(crm)
    db.commit()

    before = task_due_summary(db, world["org_a"].id, today)
    assert {row["title"] for row in before["due_soon_tasks"]} == {"Due soon", "CRM due soon"}
    assert [row["id"] for row in before["overdue_tasks"]] == [overdue["id"]]

    update_config(db, world["org_a"].id, {"due_notifications_enabled": False})
    after = task_due_summary(db, world["org_a"].id, today)
    assert after["due_soon_tasks"] == []
    assert [row["id"] for row in after["overdue_tasks"]] == [overdue["id"]]
    result = run_tasks_due_check(world["org_a"].id, db)
    assert result.flagged is True
    assert derive_health_state(_signals_from_results([result])) == "degraded"


def test_completed_tasks_load_from_archive_only_after_configured_period(task_world, db):
    world = task_world
    old_task = create_task(db, world["org_a"].id, world["user_a"].id, {"title": "Old completed task"})
    recent_task = create_task(db, world["org_a"].id, world["user_a"].id, {"title": "Recent completed task"})
    old_row = db.get(CoreTask, UUID(old_task["id"]))
    recent_row = db.get(CoreTask, UUID(recent_task["id"]))
    old_row.status = recent_row.status = "completed"
    old_row.completed_at = old_row.updated_at = utc_now() - timedelta(days=2)
    recent_row.completed_at = recent_row.updated_at = utc_now() - timedelta(hours=12)
    db.commit()

    saved = update_config(
        db,
        world["org_a"].id,
        {"done_archive_value": 1, "done_archive_unit": "days", "lane_order": ["done", "todo"], "hidden_default_lanes": ["cancelled"]},
    )
    assert saved["done_archive_value"] == 1
    assert saved["done_archive_unit"] == "days"
    assert saved["lane_order"] == ["done", "todo"]
    assert saved["hidden_default_lanes"] == ["cancelled"]

    active = list_tasks(db, world["org_a"].id)
    archived = list_tasks(db, world["org_a"].id, archive="archived")
    assert [row["id"] for row in active] == [recent_task["id"]]
    assert [row["id"] for row in archived] == [old_task["id"]]
    assert archived[0]["archived"] is True
