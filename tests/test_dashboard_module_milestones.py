"""The Dashboard transports module dates without knowing their check IDs."""

from types import SimpleNamespace

import pytest

from app.features.dashboard.routes.dashboard_routes import _dashboard_module_workspace_summaries


def _project(milestone):
    result = SimpleNamespace(
        check_id="any.future.module",
        data={
            "workspace_summary": {
                "workspace": "compliant",
                "module_name": "Future module",
                "href": "/compliant/future",
                "score": 80,
                "milestone": milestone,
            }
        },
    )
    return _dashboard_module_workspace_summaries([result], "compliant")[0]


@pytest.mark.parametrize("due", ["2026-10-22", "2028-02-29", None])
@pytest.mark.parametrize("overdue", [False, True])
def test_projects_valid_module_milestone(due, overdue):
    milestone = {"label": "Next verification", "date": due, "overdue": overdue, "detail": "2 open actions"}
    assert _project(milestone)["milestone"] == milestone


@pytest.mark.parametrize(
    "milestone",
    [
        None,
        [],
        "deadline",
        {"label": "", "date": None, "overdue": False},
        {"label": "   ", "date": None, "overdue": False},
        {"label": 1, "date": None, "overdue": False},
        {"label": "Due", "date": None, "overdue": "false"},
        {"label": "Due", "date": None, "overdue": 1},
        {"label": "Due", "date": "2026-02-29", "overdue": False},
        {"label": "Due", "date": "2026-13-01", "overdue": False},
        {"label": "Due", "date": "20261022", "overdue": False},
        {"label": "Due", "date": "2026-W43-4", "overdue": False},
        {"label": "Due", "date": "2026-10-22T00:00:00", "overdue": False},
        {"label": "Due", "date": 123, "overdue": False},
        {"label": "Due", "date": "", "overdue": False},
    ],
)
def test_invalid_milestone_does_not_discard_module(milestone):
    summary = _project(milestone)
    assert "milestone" not in summary
    assert summary["score"] == 80
    assert summary["href"] == "/compliant/future"


def test_invalid_optional_detail_is_omitted():
    assert _project({"label": " Due ", "date": None, "overdue": False, "detail": {"html": "bad"}})["milestone"] == {
        "label": "Due",
        "date": None,
        "overdue": False,
    }
