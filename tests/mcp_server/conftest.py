"""Fixtures for the public-MCP 8.2c tests: the 8.2b two-organisation world plus a bize_mcp harness.

The directory needs the optional ``mcp`` dependency group (``uv sync --extra dev --extra mcp``).
Without it every file that imports ``tests.mcp_server.support`` skips with that reason (the
``importorskip`` there); the import-graph test (``test_isolation.py``) reads source text and needs
nothing installed.
"""

from __future__ import annotations

import pytest

from tests.mcp_oauth.conftest import World, flask_app, world  # noqa: F401  (fixtures re-exported)
from tests.mcp_oauth.support import mint_grant


def token_for(world: World, who: str = "admin", *, user=None) -> str:
    """A live read-only access token for one of the world's users."""
    _, access, _ = mint_grant(world.db, user or world.users[who], world.client_row)
    return access


@pytest.fixture
def app_transport(world):
    from tests.mcp_server.support import FlaskTransport

    return FlaskTransport(world.app)


@pytest.fixture
def mcp(world, app_transport):
    """bize_mcp in front of the real app for this world."""
    from tests.mcp_server.support import Mcp

    with Mcp(app_transport) as harness:
        yield harness


@pytest.fixture
def admin_token(world):
    return token_for(world, "admin")
