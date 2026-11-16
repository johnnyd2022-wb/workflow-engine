"""Fixtures for the public-MCP 8.2f tests (spec .agents/specs/public-mcp.md, "OpenAPI for the app").

The ``world`` fixture (an organisation with one user per role, a second organisation, and MCP switched
on) is the one the 8.2b tests use, so a token here is minted exactly as it is there.
"""

from __future__ import annotations

import pytest

from app.api.openapi import build_document
from tests.mcp_oauth.conftest import flask_app, world  # noqa: F401  (fixtures re-used as they are)
from tests.openapi.seeds import showcase_world  # noqa: F401


@pytest.fixture(scope="module")
def full_doc(flask_app):  # noqa: F811
    """The whole document: every ``/api/`` operation, before any caller's permissions narrow it."""
    return build_document(flask_app)
