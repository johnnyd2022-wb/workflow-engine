"""
HTTP contract for POST .../executions/<id>/steps/<id>/complete.

Pydantic boundary (forbid extra top-level keys) + JSON shape limits to cap memory/CPU.
Trace/audit keys in execution_data are still stripped in backend after validation (server-owned fields).
"""

from __future__ import annotations

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
# Hard cap on total dict/list/scalar nodes visited (pathological wide+deep trees)
MAX_JSON_NODES = 10_000


class _JsonNodeBudget:
    """Mutable visit counter (clearer than list[int] sentinel)."""

    __slots__ = ("n",)

    def __init__(self) -> None:
        self.n = 0

    def visit(self, path: str) -> None:
        self.n += 1
        if self.n > MAX_JSON_NODES:
            raise ValueError(f"{path}: JSON structure too large (max {MAX_JSON_NODES} nodes)")


class CompleteStepRequestBody(BaseModel):
    """Strict top-level shape. Dynamic step prompts live inside execution_data as string values."""

    model_config = ConfigDict(extra="forbid")

    actual_inputs: list[Any] = Field(default_factory=list)
    actual_outputs: list[Any] = Field(default_factory=list)
    execution_data: dict[str, Any] = Field(default_factory=dict)
    allow_consumption_override: bool = False


def validate_json_blob(
    obj: Any,
    *,
    depth: int = 0,
    path: str = "$",
    budget: _JsonNodeBudget | None = None,
) -> None:
    """
    Enforce depth, breadth, and JSON-serializable types for nested payloads.
    Raises ValueError with a stable message for 400 responses.
    """
    if budget is None:
        budget = _JsonNodeBudget()
    budget.visit(path)
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
            validate_json_blob(v, depth=depth + 1, path=f"{path}.{k[:48]}", budget=budget)
    elif isinstance(obj, list):
        if len(obj) > MAX_LIST_LENGTH:
            raise ValueError(f"{path}: list too long (max {MAX_LIST_LENGTH})")
        for i, item in enumerate(obj):
            validate_json_blob(item, depth=depth + 1, path=f"{path}[{i}]", budget=budget)
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
