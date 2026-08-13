import logging
from datetime import date, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.core.backend.backend import (
    _dashboard_build_action_board,
    _dashboard_build_compliance_summary,
    _dashboard_count_red_amber,
    _dashboard_open_action_item_dates,
    _dashboard_operations_summary,
    _dashboard_parse_date_like,
    _dashboard_parse_due_date,
    _dashboard_priority_rank,
    _dashboard_series_from_date_counts,
    _dashboard_summarize_tasks,
)
from app.core.db import db_session
from app.core.db.models.audit_log import AuditLog
from app.core.db.models.execution import Execution, ExecutionStatus
from app.core.db.models.organisation import Organisation
from app.core.db.models.process import Process
from app.core.db.models.user import User
from app.core.db.repositories.execution_repo import ExecutionRepository
from app.core.db.repositories.organisation_repo import OrganisationRepository
from app.core.db.repositories.process_repo import ProcessRepository
from app.core.db.repositories.user_repo import UserRepository
from app.core.security.auth_service import AuthService
from app.features.crm.services.crm_service import CRMService
from tests.factories import DEFAULT_TEST_PASSWORD, OrganisationFactory


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


@pytest.mark.parametrize("raw", ["not-a-date", "2026-13-45", 12345, ""])
def test_dashboard_parse_due_date_returns_none_for_unparseable_input(raw):
    assert _dashboard_parse_due_date(raw) is None


def test_dashboard_parse_due_date_returns_none_for_missing_input():
    assert _dashboard_parse_due_date(None) is None


def test_dashboard_parse_due_date_parses_iso_prefix():
    assert _dashboard_parse_due_date("2026-05-16T10:00:00Z") == date(2026, 5, 16)


def test_dashboard_parse_date_like_returns_none_for_none_input():
    assert _dashboard_parse_date_like(None) is None


@pytest.mark.parametrize("raw", ["not-a-date", "2026-13-45", [1, 2, 3]])
def test_dashboard_parse_date_like_returns_none_for_unparseable_input(raw):
    assert _dashboard_parse_date_like(raw) is None


def test_dashboard_parse_date_like_passes_through_date_instance():
    assert _dashboard_parse_date_like(date(2026, 5, 16)) == date(2026, 5, 16)


def test_dashboard_series_from_date_counts_defaults_to_today_for_empty_input():
    today_iso = date.today().isoformat()

    series = _dashboard_series_from_date_counts({})

    assert series["start"] == today_iso
    assert series["end"] == today_iso
    assert series["points"] == [{"date": today_iso, "value": 0}]


def test_dashboard_series_from_date_counts_infers_bounds_from_day_counts():
    day_counts = {date(2026, 6, 3): 2, date(2026, 6, 1): 1}

    series = _dashboard_series_from_date_counts(day_counts)

    assert series["start"] == "2026-06-01"
    assert series["end"] == "2026-06-03"
    assert [p["value"] for p in series["points"]] == [1, 1, 3]


def test_dashboard_series_from_date_counts_non_cumulative_reports_daily_values():
    day_counts = {date(2026, 6, 1): 3, date(2026, 6, 3): 2}

    series = _dashboard_series_from_date_counts(day_counts, cumulative=False)

    assert [p["value"] for p in series["points"]] == [3, 0, 2]


def test_dashboard_series_from_date_counts_clamps_end_before_start():
    series = _dashboard_series_from_date_counts({}, start_day=date(2026, 6, 5), end_day=date(2026, 6, 1))

    assert series["start"] == "2026-06-05"
    assert series["end"] == "2026-06-05"
    assert series["points"] == [{"date": "2026-06-05", "value": 0}]


@pytest.mark.parametrize(
    "priority,expected_rank",
    [("high", 0), ("Medium", 1), ("low", 2), ("urgent", 3), (None, 3), ("", 3)],
)
def test_dashboard_priority_rank(priority, expected_rank):
    assert _dashboard_priority_rank(priority) == expected_rank


def test_dashboard_count_red_amber_skips_non_dict_items():
    red, amber = _dashboard_count_red_amber(
        ["not-a-dict", {"severity": "red"}, None, {"severity": "amber"}, {"severity": "amber"}]
    )

    assert red == 1
    assert amber == 2


def test_dashboard_open_action_item_dates_skips_non_dict_items():
    today = date(2026, 5, 16)
    check_results = [
        SimpleNamespace(
            check_id="expired_materials",
            data={"expired_raw_materials": ["not-a-dict", {"expiry_date": "2026-05-01"}]},
        ),
        SimpleNamespace(
            check_id="untracked_items",
            data={"untracked_items": [123, {"created_at": "2026-05-02"}]},
        ),
        SimpleNamespace(
            check_id="output_expiry",
            data={
                "output_expiry_items": [
                    None,
                    {"severity": "red", "detected_at": "2026-05-03"},
                    {"severity": "amber", "detected_at": "2026-05-09"},
                ]
            },
        ),
    ]
    open_tasks = [
        "not-a-dict",
        {"status": "pending", "due_date": "2026-05-10"},
        {"status": "completed", "due_date": "2026-05-11"},
    ]

    dates = _dashboard_open_action_item_dates(check_results, open_tasks, today)

    assert sorted(dates) == [date(2026, 5, 1), date(2026, 5, 2), date(2026, 5, 3), date(2026, 5, 10)]


@pytest.fixture
def flask_app():
    """A real app instance, built during fixture setup (not inside a test body) so
    create_app()'s unconditional root-logger handler replacement runs before pytest's
    caplog handler attaches — see the identical fixture/comment in test_executions.py."""
    from app.api.app_factory import create_app

    app = create_app()
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    return app


def _authed_dashboard_client(flask_app, db, org_id):
    email = f"user_{uuid4()}@test.com"
    UserRepository(db).create_user(
        org_id=org_id,
        email=email,
        password_hash=AuthService.hash_password(DEFAULT_TEST_PASSWORD),
        is_active=True,
    )
    db.commit()

    client = flask_app.test_client()
    client.environ_base["wsgi.url_scheme"] = "https"
    client.environ_base["HTTP_X_FORWARDED_PROTO"] = "https"
    login_resp = client.post("/auth/login", json={"email": email, "password": DEFAULT_TEST_PASSWORD})
    assert login_resp.status_code == 200, login_resp.data
    return client


def test_dashboard_summary_crm_failure_is_caught_and_logged_not_propagated(db, flask_app, monkeypatch, caplog):
    """AC5: a raising CRMService must not take the whole dashboard summary down with it —
    the route's `except Exception: logger.exception(...)` block (app/core/backend/backend.py
    around line 4766) is only reachable through the route itself, not a standalone helper,
    so this has to be a route-level test rather than a direct call to a `_dashboard_*` fn."""
    org = OrganisationFactory()
    db.commit()
    client = _authed_dashboard_client(flask_app, db, org.id)

    def _raise(self, org_id):
        raise RuntimeError("simulated CRM outage")

    monkeypatch.setattr(CRMService, "get_overview", _raise)

    try:
        with caplog.at_level(logging.ERROR):
            resp = client.get("/api/core/dashboard/summary")

        assert resp.status_code == 200, resp.data
        body = resp.get_json()

        assert body["sales"] == {
            "enabled": False,
            "current_month_revenue": 0.0,
            "outstanding_receivables": 0.0,
            "revenue_vs_last_month_pct": None,
            "baseline_target_mtd": None,
            "baseline_variance_mtd": None,
            "baseline_attainment_pct": None,
        }
        assert body["tasks"]["enabled"] is False
        assert body["tasks"]["open_count"] == 0

        failures = [r for r in caplog.records if "Failed to assemble CRM summary" in r.getMessage()]
        assert failures, f"CRM failure was not logged: {[r.getMessage() for r in caplog.records]}"
    finally:
        db.query(AuditLog).filter(AuditLog.org_id == org.id).delete(synchronize_session=False)
        db.query(User).filter(User.org_id == org.id).delete(synchronize_session=False)
        db.query(Organisation).filter(Organisation.id == org.id).delete(synchronize_session=False)
        db.commit()


def test_dashboard_summary_baseline_target_value_error_falls_back_to_null(db, flask_app, monkeypatch):
    """AC13's baseline math wraps `float(baseline_target)` in a `except (TypeError,
    ValueError): baseline_target = None` (backend.py ~4755-4756) -- a non-numeric
    configured baseline must degrade to null fields, not 500 the whole route."""
    org = OrganisationFactory()
    db.commit()
    client = _authed_dashboard_client(flask_app, db, org.id)

    def _fake_overview(self, org_id):
        return {
            "open_tasks": [],
            "current_month_revenue": 500.0,
            "outstanding_receivables": 0.0,
            "revenue_vs_last_month_pct": None,
        }

    def _fake_traceability_config(self, org_id):
        return {"revenue_baseline_target_mtd": "not-a-number"}

    def _fake_daily_sales(self, org_id, start, end):
        return []

    monkeypatch.setattr(CRMService, "get_overview", _fake_overview)
    monkeypatch.setattr(CRMService, "get_traceability_config", _fake_traceability_config)
    monkeypatch.setattr(CRMService, "daily_sales_for_period", _fake_daily_sales)

    try:
        resp = client.get("/api/core/dashboard/summary")

        assert resp.status_code == 200, resp.data
        sales = resp.get_json()["sales"]
        assert sales["enabled"] is True
        assert sales["current_month_revenue"] == 500.0
        assert sales["baseline_target_mtd"] is None
        assert sales["baseline_variance_mtd"] is None
        assert sales["baseline_attainment_pct"] is None
    finally:
        db.query(AuditLog).filter(AuditLog.org_id == org.id).delete(synchronize_session=False)
        db.query(User).filter(User.org_id == org.id).delete(synchronize_session=False)
        db.query(Organisation).filter(Organisation.id == org.id).delete(synchronize_session=False)
        db.commit()


def test_dashboard_summary_baseline_target_variance_and_attainment_computed(db, flask_app, monkeypatch):
    """The success path of the same baseline block (backend.py ~4750-4754): a valid,
    positive numeric baseline must produce a computed variance and attainment percentage,
    not just survive the failure modes covered by the ValueError test above."""
    org = OrganisationFactory()
    db.commit()
    client = _authed_dashboard_client(flask_app, db, org.id)

    def _fake_overview(self, org_id):
        return {
            "open_tasks": [],
            "current_month_revenue": 750.0,
            "outstanding_receivables": 0.0,
            "revenue_vs_last_month_pct": None,
        }

    def _fake_traceability_config(self, org_id):
        return {"revenue_baseline_target_mtd": "500"}

    def _fake_daily_sales(self, org_id, start, end):
        return []

    monkeypatch.setattr(CRMService, "get_overview", _fake_overview)
    monkeypatch.setattr(CRMService, "get_traceability_config", _fake_traceability_config)
    monkeypatch.setattr(CRMService, "daily_sales_for_period", _fake_daily_sales)

    try:
        resp = client.get("/api/core/dashboard/summary")

        assert resp.status_code == 200, resp.data
        sales = resp.get_json()["sales"]
        assert sales["baseline_target_mtd"] == 500.0
        assert sales["baseline_variance_mtd"] == 250.0
        assert sales["baseline_attainment_pct"] == 150.0
    finally:
        db.query(AuditLog).filter(AuditLog.org_id == org.id).delete(synchronize_session=False)
        db.query(User).filter(User.org_id == org.id).delete(synchronize_session=False)
        db.query(Organisation).filter(Organisation.id == org.id).delete(synchronize_session=False)
        db.commit()


def test_dashboard_summary_route_skips_non_dict_task_and_revenue_rows(db, flask_app, monkeypatch):
    """The route's own tasks-due and revenue-day loops (backend.py ~4804, ~4823) guard
    against a non-dict row from CRMService the same way `_dashboard_open_action_item_dates`
    does -- only reachable with CRM enabled returning malformed rows, hence route-level."""
    org = OrganisationFactory()
    db.commit()
    client = _authed_dashboard_client(flask_app, db, org.id)
    today = date.today()

    def _fake_overview(self, org_id):
        return {
            "open_tasks": [
                "not-a-dict",
                {
                    "id": "t1",
                    "title": "Valid task",
                    "status": "pending",
                    "due_date": today.isoformat(),
                    "priority": "high",
                },
            ],
            "current_month_revenue": 100.0,
            "outstanding_receivables": 10.0,
            "revenue_vs_last_month_pct": None,
        }

    def _fake_traceability_config(self, org_id):
        return {}

    def _fake_daily_sales(self, org_id, start, end):
        return [
            "not-a-dict",
            {"day": "not-a-date", "total": 999},
            {"day": today.isoformat(), "total": 50},
        ]

    monkeypatch.setattr(CRMService, "get_overview", _fake_overview)
    monkeypatch.setattr(CRMService, "get_traceability_config", _fake_traceability_config)
    monkeypatch.setattr(CRMService, "daily_sales_for_period", _fake_daily_sales)

    try:
        resp = client.get("/api/core/dashboard/summary")

        assert resp.status_code == 200, resp.data
        body = resp.get_json()
        assert body["tasks"]["enabled"] is True
        assert body["tasks"]["open_count"] == 1
        assert body["sales"]["current_month_revenue"] == 100.0
    finally:
        db.query(AuditLog).filter(AuditLog.org_id == org.id).delete(synchronize_session=False)
        db.query(User).filter(User.org_id == org.id).delete(synchronize_session=False)
        db.query(Organisation).filter(Organisation.id == org.id).delete(synchronize_session=False)
        db.commit()
