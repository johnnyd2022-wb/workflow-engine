"""Completed-step correction history keeps original and amended answers visible."""

from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

from app.core.backend import execution_record_routes as records


def test_prompt_data_excludes_server_owned_audit_fields():
    step = SimpleNamespace(execution_data={"temperature": "18 C", "entered_at": "server", "completed_by": "staff"})
    assert records._prompt_data(step) == {"temperature": "18 C"}


def test_history_shows_original_answers_and_reasoned_correction(monkeypatch):
    now = datetime(2026, 9, 28, 0, 0, tzinfo=UTC)
    events = [
        SimpleNamespace(
            event_type="execution.step_completed",
            created_at=now,
            actor_label="Maker",
            payload={"execution_data": {"temperature": "18 C", "entered_at": "server"}},
        ),
        SimpleNamespace(
            event_type="execution.step_amended",
            created_at=now,
            actor_label="Reviewer",
            payload={
                "reason": "Thermometer reading transcribed incorrectly",
                "before": {"prompts": {"temperature": "18 C"}},
                "after": {"prompts": {"temperature": "19 C"}},
            },
        ),
    ]

    class Query:
        def filter(self, *_args):
            return self

        def order_by(self, *_args):
            return self

        def all(self):
            return events

    monkeypatch.setattr(records.db_session, "query", lambda _model: Query())
    history = records._history(uuid4(), uuid4(), uuid4())
    assert history[0]["changes"] == [{"field": "temperature", "before": None, "after": "18 C"}]
    assert history[1]["actor"] == "Reviewer"
    assert history[1]["reason"] == "Thermometer reading transcribed incorrectly"
    assert history[1]["changes"] == [{"field": "temperature", "before": "18 C", "after": "19 C"}]
