"""Checking tool arguments before anything is sent to the app.

Arguments end up in two places: as query values (always encoded by the HTTP client) and as one
path segment (an id). A path segment is only ever a canonical UUID or an encoded product key, so no
argument can steer a call to a different route. Error messages name the field and never echo the
value (a value could be a token someone pasted by mistake).
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any
from urllib.parse import quote
from uuid import UUID

import jsonschema

from bize_mcp.errors import ToolFailureError

UUID_PATTERN = r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
MONTH_PATTERN = r"^\d{4}-(0[1-9]|1[0-2])$"
DATE_PATTERN = r"^\d{4}-\d{2}-\d{2}$"
KEY_PATTERN = r"^[^\x00-\x1f\x7f/\\?#]{1,200}$"
_BAD_KEY = {".", ".."}


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
        return f"{field} must be {error.validator_value}"
    if rule == "enum":
        return f"{field} must be one of: " + ", ".join(str(v) for v in error.validator_value)
    if rule in {"minimum", "maximum"}:
        low, high = error.schema.get("minimum"), error.schema.get("maximum")
        return f"{field} must be between {low} and {high}"
    if rule in {"maxLength", "minLength"}:
        return f"{field} has the wrong length"
    return f"{field} is not valid"


def check_arguments(tool_name: str, tool_schema: dict[str, Any], arguments: Any) -> dict[str, Any]:
    """The arguments if they fit the schema, else a ``ToolFailureError`` saying which field is wrong."""
    if arguments is None:
        arguments = {}
    validator = jsonschema.Draft202012Validator(tool_schema)
    errors = sorted(validator.iter_errors(arguments), key=lambda e: [str(p) for p in e.absolute_path])
    if errors:
        raise ToolFailureError(f"Invalid input for {tool_name}: {_message(errors[0])}.", kind="invalid_input")
    return dict(arguments)


def uuid_segment(value: str, name: str) -> str:
    """A canonical UUID string, safe to place in a URL path."""
    try:
        return str(UUID(value))
    except (ValueError, AttributeError, TypeError):
        raise ToolFailureError(
            f"Invalid input: {name} must be an id like 3f2b8c1e-....", kind="invalid_input"
        ) from None


def key_segment(value: str, name: str) -> str:
    """A product key as one encoded path segment (colons kept, so ``name:gin`` stays readable)."""
    if not re.fullmatch(KEY_PATTERN, value) or value in _BAD_KEY:
        raise ToolFailureError(f"Invalid input: {name} is not a valid product key.", kind="invalid_input")
    return quote(value, safe=":")


def iso_date(value: str, name: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise ToolFailureError(f"Invalid input: {name} must be a date like 2026-10-31.", kind="invalid_input") from None
