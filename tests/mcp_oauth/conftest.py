"""Fixtures for the public-MCP 8.2b tests: one app, one two-organisation world."""

from __future__ import annotations

from dataclasses import dataclass, field
from uuid import uuid4

import pytest
from sqlalchemy import or_

from app.core.db.models.organisation import Organisation
from app.core.db.models.user import User, UserRole
from app.features.mcp_oauth.models import McpAllowedRole, McpOrgSettings, OAuthClient
from tests.factories import DEFAULT_TEST_PASSWORD, InventoryItemFactory, OrganisationFactory, UserFactory
from tests.mcp_oauth.support import TEST_NAME_PREFIX, make_client, unique_addr
from tests.org_purge import purge_orgs

PASSWORD = DEFAULT_TEST_PASSWORD
ROLES = ("admin", "member", "production", "compliance", "sales", "auditor")


@pytest.fixture(scope="module")
def flask_app():
    from app.api.app_factory import create_app

    app = create_app()
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    return app


@dataclass
class World:
    app: object
    db: object
    org: Organisation
    other_org: Organisation
    users: dict = field(default_factory=dict)
    other_admin: User | None = None
    item: object = None
    other_item: object = None

    def _client(self):
        c = self.app.test_client()
        c.environ_base["wsgi.url_scheme"] = "https"
        c.environ_base["HTTP_X_FORWARDED_PROTO"] = "https"
        c.environ_base["REMOTE_ADDR"] = unique_addr()
        return c

    def anon(self):
        """A client with no cookies: what an MCP server or curl looks like."""
        return self._client()

    def session(self, who="admin", user=None):
        """A browser client signed in through the real login endpoint."""
        user = user or self.users[who]
        c = self._client()
        resp = c.post("/auth/login", json={"email": user.email, "password": PASSWORD})
        assert resp.status_code == 200, resp.get_json()
        assert not resp.get_json().get("requires_2fa"), "use sign_in_with_2fa for 2FA users"
        return c

    def add_user(self, role=UserRole.MEMBER, **kwargs) -> User:
        user = UserFactory(
            org_id=self.org.id, email=f"mcp-{role.value}-{uuid4().hex[:8]}@example.test", role=role, **kwargs
        )
        self.db.commit()
        return user

    def enable(self, enabled=True, roles=ROLES, extra_keys=(), allow_unverified=True):
        """Set the org's MCP switch, allowed roles and unverified-apps setting directly (what the
        settings API does). ``allow_unverified`` defaults to True so the tests written before S3
        keep exercising their unverified test client; the S3 tests pass False (the real default)."""
        self.db.query(McpAllowedRole).filter(McpAllowedRole.org_id == self.org.id).delete()
        row = self.db.get(McpOrgSettings, self.org.id)
        if row is None:
            row = McpOrgSettings(org_id=self.org.id)
            self.db.add(row)
        row.enabled = enabled
        row.allow_unverified_clients = allow_unverified
        for role in roles:
            self.db.add(McpAllowedRole(org_id=self.org.id, role_key=f"builtin:{role}"))
        for key in extra_keys:
            self.db.add(McpAllowedRole(org_id=self.org.id, role_key=key))
        self.db.commit()


@pytest.fixture
def world(db, flask_app):
    org = OrganisationFactory()
    other_org = OrganisationFactory()
    db.commit()
    w = World(app=flask_app, db=db, org=org, other_org=other_org)
    for role in ROLES:
        w.users[role] = UserFactory(
            org_id=org.id, email=f"mcp-{role}-{uuid4().hex[:8]}@example.test", role=UserRole(role)
        )
    w.other_admin = UserFactory(
        org_id=other_org.id, email=f"mcp-other-{uuid4().hex[:8]}@example.test", role=UserRole.ADMIN
    )
    w.item = InventoryItemFactory(org_id=org.id, name="Org A Juniper")
    w.other_item = InventoryItemFactory(org_id=other_org.id, name="Org B Secret Botanical")
    db.commit()
    w.enable()
    w.client_row = make_client(db)
    org_ids = [org.id, other_org.id]
    with flask_app.app_context():
        yield w
    db.rollback()
    purge_orgs(db, org_ids)
    # make_client ids start with test-client-; a client on the verified list is renamed (e.g. to
    # "Claude"), so the name prefix alone would miss it.
    db.query(OAuthClient).filter(
        or_(OAuthClient.client_name.like(f"{TEST_NAME_PREFIX}%"), OAuthClient.client_id.like("test-client-%"))
    ).delete(synchronize_session=False)
    db.commit()
