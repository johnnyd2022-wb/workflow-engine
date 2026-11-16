"""Seeded data for the response-validation test (AC37), and the call each assistant operation is made with.

One organisation, built once per module and removed with the test session's organisations, holds a little
of everything the first-wave operations read: stock in several states, a finished batch, a hold, a
costed purchase, a sale, an excise period, a stocktake and a planner demand. Each ``SEEDS`` entry says which
path and query to call an operation with, and which parts of the response must come back non-empty so a
seed that quietly produced nothing cannot pass for proof.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

import pytest

from app.core.db import db_session
from app.core.db.models.user import UserRole
from tests.factories import DEFAULT_TEST_PASSWORD, OrganisationFactory, UserFactory
from tests.mcp_oauth.support import RESOURCE, bearer, make_client, mint_grant, unique_addr  # noqa: F401


@dataclass
class Call:
    params: dict = field(default_factory=dict)  # path parameters
    query: dict = field(default_factory=dict)
    nonempty: tuple[str, ...] = ()  # dotted body paths the seed must have produced


@dataclass
class Showcase:
    app: object
    db: object
    org: object
    admin: object
    ids: dict = field(default_factory=dict)
    token_headers: dict = field(default_factory=dict)

    def _client(self):
        client = self.app.test_client()
        client.environ_base["wsgi.url_scheme"] = "https"
        client.environ_base["HTTP_X_FORWARDED_PROTO"] = "https"
        client.environ_base["REMOTE_ADDR"] = unique_addr()
        return client

    @property
    def token_client(self):
        return self._client()

    @property
    def session_client(self):
        client = self._client()
        resp = client.post("/auth/login", json={"email": self.admin.email, "password": DEFAULT_TEST_PASSWORD})
        assert resp.status_code == 200, resp.get_json()
        return client


SEEDS: dict[str, Callable[[Showcase], Call]] = {}


@pytest.fixture(scope="module")
def showcase_world(flask_app):
    """The seeded organisation, with an admin and a live assistant token for that admin."""
    from app.features.mcp_oauth.models import McpAllowedRole, McpOrgSettings

    db = db_session()
    org = OrganisationFactory()
    admin = UserFactory(org_id=org.id, email=f"showcase-{org.id.hex[:8]}@example.test", role=UserRole.ADMIN)
    db.commit()
    db.add(McpOrgSettings(org_id=org.id, enabled=True))
    db.add(McpAllowedRole(org_id=org.id, role_key="builtin:admin"))
    db.commit()
    client_row = make_client(db)
    _grant, access, _refresh = mint_grant(db, admin, client_row)
    world = Showcase(app=flask_app, db=db, org=org, admin=admin, token_headers=bearer(access))
    with flask_app.app_context():
        yield world
    db.rollback()
    db.close()
    db_session.remove()
