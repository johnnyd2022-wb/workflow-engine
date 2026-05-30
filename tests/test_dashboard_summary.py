from datetime import date, datetime, timedelta
from types import SimpleNamespace

import pytest

from app.core.backend.backend import (
    _dashboard_build_action_board,
    _dashboard_build_compliance_summary,
    _dashboard_operations_summary,
    _dashboard_summarize_tasks,
)
from app.core.db import db_session
from app.core.db.models.execution import Execution, ExecutionStatus
from app.core.db.models.organisation import Organisation
from app.core.db.models.process import Process
from app.core.db.repositories.execution_repo import ExecutionRepository
from app.core.db.repositories.organisation_repo import OrganisationRepository
from app.core.db.repositories.process_repo import ProcessRepository


@pytest.fixture
def db():
    session = db_session()
    try:
        yield session
    finally:
        session.close()
        db_session.remove()


def test_dashboard_task_bucketing_due_today_and_overdue():
    today = date(2026, 5, 16)
    tasks = [
        {"id": "1", "title": "Overdue", "status": "pending", "due_date": "2026-05-14", "priority": "high"},
        {"id": "2", "title": "Today", "status": "in_progress", "due_date": "2026-05-16", "priority": "medium"},
        {"id": "3", "title": "Future", "status": "pending", "due_date": "2026-05-20", "priority": "low"},
        {"id": "4", "title": "Done", "status": "completed", "due_date": "2026-05-16", "priority": "high"},
    ]

    summary = _dashboard_summarize_tasks(
        tasks,
        today,
        week_start=date(2026, 5, 12),
        week_end_exclusive=date(2026, 5, 19),
    )

    assert summary["enabled"] is True
    assert summary["open_count"] == 3
    assert summary["due_today_count"] == 1
    assert summary["overdue_count"] == 1
    assert summary["due_this_week_count"] == 2
    assert [t["id"] for t in summary["top_tasks"]] == ["1", "2", "3"]


def test_dashboard_compliance_score_formula_v1():
    results = [
        SimpleNamespace(
            check_id="expired_materials",
            data={"expired_raw_materials": [{"id": "a"}], "impacted_items": [{"id": "i1"}, {"id": "i2"}, {"id": "i3"}]},
        ),
        SimpleNamespace(check_id="untracked_items", data={"untracked_items": [{"id": "u1"}, {"id": "u2"}]}),
        SimpleNamespace(
            check_id="output_expiry",
            data={"output_expiry_items": [{"severity": "red"}, {"severity": "red"}, {"severity": "amber"}]},
        ),
        SimpleNamespace(
            check_id="output_ready_date",
            data={"output_ready_date_items": [{"severity": "red"}, {"severity": "amber"}, {"severity": "amber"}]},
        ),
    ]
    system_status = {
        "mode": "health",
        "state": "critical",
        "signals": [
            {"has_issue": True, "in_active_use": True},
            {"has_issue": True, "in_active_use": False},
        ],
    }

    summary = _dashboard_build_compliance_summary(results, system_status)

    assert summary["score"] == 50
    assert summary["score_version"] == "v1"
    assert summary["state"] == "critical"
    assert summary["findings"]["expired_materials"]["count"] == 1
    assert summary["findings"]["expired_materials"]["impacted_count"] == 3
    assert summary["findings"]["active_use_risk_count"] == 1
    assert summary["top_drivers"][0]["key"] == "expired_materials"


def test_dashboard_action_board_excludes_stalled_batches():
    tasks_summary = {"overdue_count": 3}
    compliance = {
        "findings": {
            "expired_materials": {"count": 2},
            "untracked_items": {"count": 4},
            "output_expiry": {"red_count": 1, "amber_count": 2},
            "output_ready_date": {"red_count": 5, "amber_count": 0},
        }
    }

    board = _dashboard_build_action_board(tasks_summary, compliance)

    keys = [item["key"] for item in board["items"]]
    assert "stalled_executions" not in keys
    assert board["critical_actions_total"] == 10


def test_dashboard_operations_summary_org_isolated(db):
    org_repo = OrganisationRepository(db)
    process_repo = ProcessRepository(db)
    execution_repo = ExecutionRepository(db)

    org_a = org_repo.create_org("Dashboard Org A")
    org_b = org_repo.create_org("Dashboard Org B")
    process_a = process_repo.create_process(org_id=org_a.id, name="Proc A", description="", is_draft=False)
    process_b = process_repo.create_process(org_id=org_b.id, name="Proc B", description="", is_draft=False)
    day_start = datetime.combine(date.today(), datetime.min.time())
    next_day_start = day_start + timedelta(days=1)

    try:
        ex_active = execution_repo.create_execution(org_id=org_a.id, process_id=process_a.id)
        ex_active.status = ExecutionStatus.IN_PROGRESS

        ex_completed = execution_repo.create_execution(org_id=org_a.id, process_id=process_a.id)
        ex_completed.status = ExecutionStatus.COMPLETED
        ex_completed.completed_at = day_start + timedelta(hours=1)

        ex_failed = execution_repo.create_execution(org_id=org_a.id, process_id=process_a.id)
        ex_failed.status = ExecutionStatus.FAILED
        ex_failed.updated_at = day_start + timedelta(hours=2)

        ex_other_org = execution_repo.create_execution(org_id=org_b.id, process_id=process_b.id)
        ex_other_org.status = ExecutionStatus.COMPLETED
        ex_other_org.completed_at = day_start + timedelta(hours=1)

        db.commit()

        summary_a = _dashboard_operations_summary(org_a.id, db, day_start, next_day_start)
        summary_b = _dashboard_operations_summary(org_b.id, db, day_start, next_day_start)

        assert summary_a == {"active_executions": 1, "completed_today": 1, "failed_or_cancelled_today": 1}
        assert summary_b["active_executions"] == 0
        assert summary_b["completed_today"] == 1
    finally:
        db.query(Execution).filter(Execution.org_id.in_([org_a.id, org_b.id])).delete(synchronize_session=False)
        db.query(Process).filter(Process.org_id.in_([org_a.id, org_b.id])).delete(synchronize_session=False)
        db.query(Organisation).filter(Organisation.id.in_([org_a.id, org_b.id])).delete(synchronize_session=False)
        db.commit()
