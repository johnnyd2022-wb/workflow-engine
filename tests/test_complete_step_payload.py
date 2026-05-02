"""complete_step HTTP payload validation (Pydantic + JSON shape guards)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.core.backend.complete_step_payload import MAX_JSON_DEPTH, CompleteStepRequestBody, validate_json_blob
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
