"""complete_step HTTP payload validation (Pydantic + JSON shape guards)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.core.backend.complete_step_payload import MAX_JSON_DEPTH, CompleteStepRequestBody, validate_json_blob
from app.core.backend.execution_routes import _strip_incoming_execution_trace_keys
from app.core.domain.execution_entry_timing import entry_timing
from app.core.utils.internal_counters import inc_counter, reset_counters_for_tests


def test_complete_step_body_forbids_extra_keys():
    with pytest.raises(ValidationError):
        CompleteStepRequestBody.model_validate(
            {
                "actual_inputs": [],
                "actual_outputs": [],
                "execution_data": {},
                "surprise": True,
            }
        )


def test_complete_step_body_accepts_occurrence_time_with_timezone():
    body = CompleteStepRequestBody.model_validate({"occurred_at": "2026-09-25T08:30:00+12:00"})
    assert body.occurred_at.isoformat() == "2026-09-25T08:30:00+12:00"


def test_entry_timing_marks_only_more_than_one_day_late():
    from datetime import UTC, datetime, timedelta

    happened = datetime(2026, 9, 25, 8, 0, tzinfo=UTC)
    assert not entry_timing(happened, {"entered_at": (happened + timedelta(days=1)).isoformat()})["entered_later"]
    later = entry_timing(happened, {"entered_at": (happened + timedelta(days=1, seconds=1)).isoformat()})
    assert later["entered_later"] is True
    assert later["entered_at"] == "2026-09-26T08:00:01+00:00"


def test_client_cannot_set_server_entry_time():
    assert _strip_incoming_execution_trace_keys({"entered_at": "fake", "prompt": "real"}) == {"prompt": "real"}


def test_validate_json_blob_depth():
    nested: dict = {"x": 1}
    cur = nested
    for i in range(MAX_JSON_DEPTH + 2):
        cur["n"] = {}
        cur = cur["n"]
    with pytest.raises(ValueError, match="nesting"):
        validate_json_blob(nested)


def test_validate_json_blob_dict_width():
    wide = {str(i): i for i in range(250)}
    with pytest.raises(ValueError, match="too many keys"):
        validate_json_blob(wide)


def test_validate_json_blob_node_budget(monkeypatch):
    monkeypatch.setattr("app.core.backend.complete_step_payload.MAX_JSON_NODES", 30)
    # Each validate_json_blob entry increments nodes; this tree exceeds 30 visits before depth/key limits.
    payload = {str(i): {f"k{j}": 1 for j in range(6)} for i in range(5)}
    with pytest.raises(ValueError, match="too large"):
        validate_json_blob(payload)


def test_counters_increment():
    reset_counters_for_tests()
    inc_counter("inventory_hydration_failures", 2)
    from app.core.utils.internal_counters import get_counter_snapshot

    assert get_counter_snapshot().get("inventory_hydration_failures") == 2
    reset_counters_for_tests()
