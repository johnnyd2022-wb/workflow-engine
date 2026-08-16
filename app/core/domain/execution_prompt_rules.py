"""Invariant checks for structured data captured during a workflow step."""

from __future__ import annotations

from typing import Any


def _present(value: Any) -> bool:
    """Treat whitespace-only strings and nulls as absent; preserve valid zero values."""
    return value is not None and (not isinstance(value, str) or bool(value.strip()))


def _choices(prompt: dict[str, Any]) -> list[str]:
    values = prompt.get("options")
    if not isinstance(values, list):
        return []
    return list(dict.fromkeys(str(value).strip() for value in values if str(value).strip()))


def validate_execution_prompts(prompts: list[Any] | None, execution_data: dict[str, Any] | None) -> list[str]:
    """Return user-safe violations for required and constrained workflow prompts.

    Evidence prompts are persisted through the evidence service rather than
    ``execution_data`` and therefore remain intentionally outside this check.
    Select prompts created before choices existed remain compatible: they are
    required when configured as such, but only a prompt with actual choices has
    an enum constraint to enforce.
    """
    data = execution_data or {}
    errors: list[str] = []
    for prompt in prompts or []:
        if not isinstance(prompt, dict):
            continue
        label = str(prompt.get("label") or "").strip()
        if not label or prompt.get("type") == "evidence":
            continue
        value = data.get(label)
        if prompt.get("required") is not False and not _present(value):
            errors.append(f'Please fill in required field: "{label}"')
            continue
        choices = _choices(prompt)
        if prompt.get("type") == "select" and choices and _present(value) and str(value).strip() not in choices:
            errors.append(f'Field "{label}" must be one of: {", ".join(choices)}')
    return errors
