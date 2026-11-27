"""Field validation at the HTTP boundary.

Declare endpoint schemas with the same constraints as their domain and storage. JSON
uses strict Pydantic types. Dates, UUIDs, decimal strings and enum values use their
standard JSON representations. Schemas reject extra fields by default.
"""

from math import isfinite
from types import NoneType, UnionType
from typing import Annotated, get_args, get_origin
from unicodedata import category

from flask import jsonify, request
from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, JsonValue, StringConstraints, ValidationError


def _check_name(value):
    if isinstance(value, str) and any(category(character) in {"Cc", "Cs"} for character in value):
        raise ValueError("Control characters are not allowed.")
    return value


CleanText = Annotated[str, StringConstraints(strip_whitespace=True), BeforeValidator(_check_name)]
CleanName = Annotated[CleanText, StringConstraints(min_length=1)]


def validate_json_storage(value):
    """Reject values PostgreSQL JSONB cannot represent, including in nested metadata."""
    if isinstance(value, dict):
        for key, item in value.items():
            validate_json_storage(key)
            validate_json_storage(item)
    elif isinstance(value, list):
        for item in value:
            validate_json_storage(item)
    elif isinstance(value, str) and ("\x00" in value or any(category(char) == "Cs" for char in value)):
        raise ValueError("Use valid text without null characters.")
    elif isinstance(value, float) and not isfinite(value):
        raise ValueError("Enter a finite number.")
    return value


StoredJson = Annotated[JsonValue, BeforeValidator(validate_json_storage)]


class JsonInput(BaseModel):
    """Base for route-specific JSON object schemas."""

    model_config = ConfigDict(
        strict=True, extra="forbid", allow_inf_nan=False, validate_default=True, loc_by_alias=False
    )


class _ServiceInput(JsonInput):
    """Validate JSON storage types when the called service already owns the schema."""

    model_config = ConfigDict(extra="allow")
    __pydantic_extra__: dict[str, StoredJson] = Field(init=False)


_MESSAGES = {
    "missing": "This field is required.",
    "string_too_short": "This text is too short.",
    "string_too_long": "This text is too long.",
    "string_pattern_mismatch": "Use the required format.",
    "string_type": "Enter text.",
    "int_type": "Enter a whole number.",
    "bool_type": "Use true or false.",
    "list_type": "Use a list.",
    "too_short": "Include more items.",
    "too_long": "Include fewer items.",
    "finite_number": "Enter a finite number.",
    "decimal_max_places": "Use fewer decimal places.",
    "decimal_max_digits": "Use fewer digits.",
    "greater_than": "This value is below the allowed range.",
    "greater_than_equal": "This value is below the allowed range.",
    "less_than": "This value is above the allowed range.",
    "less_than_equal": "This value is above the allowed range.",
    "enum": "Choose an allowed value.",
    "extra_forbidden": "Unknown field.",
    "json_invalid": "Send a valid JSON object.",
    "model_type": "Send a JSON object.",
}


class InvalidInputError(ValueError):
    """Field errors safe to display in JSON responses or HTML forms."""

    def __init__(self, errors: dict[str, str]):
        message = next(iter(errors.values())) if len(errors) == 1 else "Check the request fields."
        super().__init__(message)
        self.errors = errors

    def response(self):
        return jsonify(error=str(self), errors=self.errors), 400


def read_json[Payload: JsonInput](schema: type[Payload]) -> Payload:
    """Read and validate a JSON object without reflecting caller-controlled values."""
    if not request.is_json:
        raise InvalidInputError({"_body": "Send an application/json request."})
    try:
        return schema.model_validate_json(request.get_data())
    except ValidationError as exc:
        raise _format_errors(schema, exc) from None


def read_service_json() -> dict:
    return read_json(_ServiceInput).model_extra or {}


def read_form[Payload: JsonInput](schema: type[Payload]) -> Payload:
    """Validate a flat HTML form, leaving CSRF handling to Flask-WTF."""
    values = {}
    for name, entries in request.form.lists():
        if name == "csrf_token":
            continue
        if len(entries) != 1:
            field = name if name in schema.model_fields else "_body"
            raise InvalidInputError({field: "Use one value for this field."})
        values[name] = entries[0]
    try:
        return schema.model_validate(values)
    except ValidationError as exc:
        raise _format_errors(schema, exc) from None


def _format_errors(schema: type[JsonInput], exc: ValidationError) -> InvalidInputError:
    errors: dict[str, str] = {}
    for error in exc.errors(include_url=False, include_context=False, include_input=False):
        kind = error["type"]
        field = _field_path(schema, error["loc"])
        errors.setdefault(field, _MESSAGES.get(kind, "Enter a valid value."))
    return InvalidInputError(errors)


def _field_path(schema: type[JsonInput], location: tuple) -> str:
    """Use declared names and list indices. Caller-controlled object keys are omitted."""
    annotation = schema
    path = []
    for part in location:
        if get_origin(annotation) is UnionType:
            variants = tuple(choice for choice in get_args(annotation) if choice is not NoneType)
            if len(variants) == 1:
                annotation = variants[0]
        if get_origin(annotation) is Annotated:
            annotation = get_args(annotation)[0]
        if isinstance(part, int) and get_origin(annotation) is list:
            annotation = get_args(annotation)[0]
        elif isinstance(annotation, type) and issubclass(annotation, JsonInput) and part in annotation.model_fields:
            annotation = annotation.model_fields[part].annotation
        else:
            break
        path.append(str(part))
    return ".".join(path) or "_body"


def query_text(name: str, *, default: str = "", max_length: int = 255) -> str:
    """Read one bounded query string value."""
    values = request.args.getlist(name)
    if not values:
        return default
    if len(values) != 1:
        raise InvalidInputError({name: "Use one value for this parameter."})
    value = values[0]
    if len(value) > max_length or any(category(character) in {"Cc", "Cs"} for character in value):
        raise InvalidInputError({name: f"Enter text of up to {max_length} characters."})
    return value.strip()


def query_int(name: str, *, default: int, minimum: int, maximum: int) -> int:
    """Read a bounded non-negative integer from a URL query string."""
    raw = query_text(name, default=str(default), max_length=24)
    if not raw.isascii() or not raw.isdecimal():
        raise InvalidInputError({name: f"{name} must be an integer."})
    value = int(raw)
    if not minimum <= value <= maximum:
        raise InvalidInputError({name: f"{name} must be between {minimum} and {maximum}."})
    return value
