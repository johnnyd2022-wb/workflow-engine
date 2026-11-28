"""Input checks shared by the OAuth protocol endpoints and MCP settings."""

from typing import Annotated
from unicodedata import category

from pydantic import Field

from app.features.mcp_oauth.services.settings_service import MAX_ROLE_KEYS
from app.utils.request_validation import JsonInput

RoleKey = Annotated[str, Field(max_length=43, pattern=r"^[A-Za-z0-9:_-]+$")]


class MCPSettingsInput(JsonInput):
    enabled: bool
    allowed_roles: list[RoleKey] = Field(max_length=MAX_ROLE_KEYS)


AUTHORIZE_SINGLE_FIELDS = (
    "client_id",
    "redirect_uri",
    "response_type",
    "code_challenge",
    "code_challenge_method",
    "scope",
    "state",
)
CONSENT_SINGLE_FIELDS = (*AUTHORIZE_SINGLE_FIELDS, "decision", "access_level")
TOKEN_SINGLE_FIELDS = (
    "grant_type",
    "client_id",
    "code",
    "code_verifier",
    "redirect_uri",
    "refresh_token",
    "scope",
    "resource",
)
REVOKE_SINGLE_FIELDS = ("token", "client_id", "token_type_hint")


def check_single_fields(parameters, fields):
    for name in fields:
        values = parameters.getlist(name)
        if len(values) > 1:
            raise ValueError(f"Send only one {name} parameter.")
        if values and (len(values[0]) > 2048 or any(category(char) in {"Cc", "Cs"} for char in values[0])):
            raise ValueError(f"{name} is invalid.")
