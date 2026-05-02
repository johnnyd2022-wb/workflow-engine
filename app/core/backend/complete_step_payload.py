"""
HTTP contract for POST .../executions/<id>/steps/<id>/complete.

Pydantic boundary (forbid extra top-level keys) + JSON shape limits to cap memory/CPU.
Trace/audit keys in execution_data are still stripped in backend after validation (server-owned fields).
"""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

# Request body: stay below common proxy limits; large prompts should still fit.
MAX_COMPLETE_STEP_CONTENT_LENGTH = 768 * 1024

# Nested JSON in actual_inputs / actual_outputs / execution_data
MAX_JSON_DEPTH = 8
MAX_DICT_KEYS_PER_LEVEL = 200
MAX_LIST_LENGTH = 500
MAX_STRING_LENGTH = 100_000
MAX_KEY_LENGTH = 256


class CompleteStepRequestBody(BaseModel):
    """Strict top-level shape. Dynamic step prompts live inside execution_data as string values."""

    model_config = ConfigDict(extra="forbid")

    actual_inputs: list[Any] = Field(default_factory=list)
    actual_outputs: list[Any] = Field(default_factory=list)
    execution_data: dict[str, Any] = Field(default_factory=dict)
    allow_consumption_override: bool = False


def validate_json_blob(obj: Any, *, depth: int = 0, path: str = "$") -> None:
    """
    Enforce depth, breadth, and JSON-serializable types for nested payloads.
    Raises ValueError with a stable message for 400 responses.
    """
    if depth > MAX_JSON_DEPTH:
        raise ValueError(f"{path}: nesting exceeds maximum depth ({MAX_JSON_DEPTH})")
    if isinstance(obj, dict):
        if len(obj) > MAX_DICT_KEYS_PER_LEVEL:
            raise ValueError(f"{path}: too many keys (max {MAX_DICT_KEYS_PER_LEVEL})")
        for k, v in obj.items():
            if not isinstance(k, str):
                raise ValueError(f"{path}: object keys must be strings")
            if len(k) > MAX_KEY_LENGTH:
                raise ValueError(f"{path}: key too long (max {MAX_KEY_LENGTH} chars)")
            validate_json_blob(v, depth=depth + 1, path=f"{path}.{k[:48]}")
    elif isinstance(obj, list):
        if len(obj) > MAX_LIST_LENGTH:
            raise ValueError(f"{path}: list too long (max {MAX_LIST_LENGTH})")
        for i, item in enumerate(obj):
            validate_json_blob(item, depth=depth + 1, path=f"{path}[{i}]")
    elif isinstance(obj, str):
        if len(obj) > MAX_STRING_LENGTH:
            raise ValueError(f"{path}: string too long (max {MAX_STRING_LENGTH} chars)")
    elif isinstance(obj, bool):
        pass
    elif isinstance(obj, (int, float)):
        pass
    elif obj is None:
        pass
    else:
        raise ValueError(f"{path}: unsupported JSON type {type(obj).__name__}")


def approximate_json_value_size(value: Any) -> int:
    """Rough serialized byte size for guarding bodies without Content-Length."""
    try:
        return len(json.dumps(value, default=str))
    except Exception:
        return MAX_COMPLETE_STEP_CONTENT_LENGTH + 1
