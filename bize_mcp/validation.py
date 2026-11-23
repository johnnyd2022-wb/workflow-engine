"""Checking tool arguments before anything is sent to the app.

Arguments are checked against a JSON Schema (formats such as ``uuid`` and ``date`` included) before
anything is sent. Path values are additionally encoded and restricted in ``tools/execute.py``. Error
messages name the field and never echo the value (it could be a token someone pasted by mistake).
"""

from __future__ import annotations

from typing import Any

import jsonschema

from bize_mcp.errors import ToolFailureError


def schema(properties: dict[str, Any], required: tuple[str, ...] = ()) -> dict[str, Any]:
    body: dict[str, Any] = {"type": "object", "properties": properties, "additionalProperties": False}
    if required:
        body["required"] = list(required)
    return body


CURSOR = {"type": "string", "maxLength": 1024, "description": "The next_cursor from the previous result."}


def _field(error: jsonschema.ValidationError) -> str:
    return ".".join(str(part) for part in error.absolute_path) or "arguments"


def _message(error: jsonschema.ValidationError) -> str:
    field = _field(error)
    rule = error.validator
    if rule == "required":
        missing = [name for name in error.validator_value if name not in (error.instance or {})]
        return f"{', '.join(missing)} is required"
    if rule == "additionalProperties":
        extras = sorted(set(error.instance) - set(error.schema.get("properties", {})))
        return "unknown argument: " + ", ".join(name[:40] for name in extras[:5])
    if rule == "type":
        if error.validator_value == "integer" and {"minimum", "maximum"} <= error.schema.keys():
            return f"{field} must be an integer from {error.schema['minimum']} to {error.schema['maximum']}"
        return f"{field} must be of type {error.validator_value}"
    if rule == "enum":
        return f"{field} must be one of: " + ", ".join(str(v) for v in error.validator_value)
    if rule in {"minimum", "maximum"}:
        low, high = error.schema.get("minimum"), error.schema.get("maximum")
        if low is not None and high is not None:
            return f"{field} must be between {low} and {high}"
        bound = "at least" if rule == "minimum" else "at most"
        return f"{field} must be {bound} {error.validator_value}"
    if rule in {"maxLength", "minLength"}:
        bound = "at most" if rule == "maxLength" else "at least"
        return f"{field} must be {bound} {error.validator_value} characters long"
    return f"{field} is not valid"


def check_arguments(tool_name: str, tool_schema: dict[str, Any], arguments: Any) -> dict[str, Any]:
    """The arguments if they fit the schema, else a ``ToolFailureError`` saying which field is wrong."""
    if arguments is None:
        arguments = {}
    validator = jsonschema.Draft202012Validator(tool_schema, format_checker=jsonschema.FormatChecker())
    try:
        errors = sorted(validator.iter_errors(arguments), key=lambda e: [str(p) for p in e.absolute_path])
    except Exception:  # an unusable schema (a dangling $ref, say) must fail this call, not the whole batch
        raise ToolFailureError(
            f"{tool_name} can't be run: its parameter schema is unusable.", kind="upstream_error"
        ) from None
    if errors:
        raise ToolFailureError(f"Invalid input for {tool_name}: {_message(errors[0])}.", kind="invalid_input")
    return dict(arguments)
