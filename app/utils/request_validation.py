"""Field validation at the HTTP boundary.

Declare endpoint schemas with the same constraints as their domain and storage. JSON
uses strict Pydantic types. Dates, UUIDs, decimal strings and enum values use their
standard JSON representations. Schemas reject extra fields by default.
"""

from typing import Annotated
from unicodedata import category

from flask import jsonify, request
from pydantic import AfterValidator, BaseModel, ConfigDict, StringConstraints, ValidationError


def _check_name(value: str) -> str:
    if any(category(character) in {"Cc", "Cs"} for character in value):
        raise ValueError("Control characters are not allowed.")
    return value


CleanName = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1),
    AfterValidator(_check_name),
]


class JsonInput(BaseModel):
    """Base for route-specific JSON object schemas."""

    model_config = ConfigDict(strict=True, extra="forbid", allow_inf_nan=False, validate_default=True)


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
        super().__init__("Check the request fields.")
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
        errors: dict[str, str] = {}
        for error in exc.errors(include_url=False, include_context=False, include_input=False):
            kind = error["type"]
            location = error["loc"]
            field = location[0] if location and location[0] in schema.model_fields else "_body"
            errors.setdefault(field, _MESSAGES.get(kind, "Enter a valid value."))
        raise InvalidInputError(errors) from None
