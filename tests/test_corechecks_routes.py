"""Route-level tests for the compliance-checks API surface (corechecks.register_routes).

Before this review, corechecks.py's route handlers (lines ~169-260) had no HTTP-level
coverage at all — only the underlying check functions were unit tested. This file closes
that gap and, more importantly, proves org-scoping end-to-end through the real request
path (session -> g.org_id -> route -> CoreChecksRunner), which a unit test calling the
check function directly cannot do: it is the actual attack surface for a cross-tenant read.
"""

from uuid import uuid4

import pytest

from app.core.db.models.organisation import Organisation
from app.core.db.repositories.user_repo import UserRepository
from app.core.security.auth_service import AuthService
from tests.factories import DEFAULT_TEST_PASSWORD, InventoryItemFactory, OrganisationFactory

PASSWORD = DEFAULT_TEST_PASSWORD

ROUTES = [
    ("/api/core/inventory/expired-materials", "expired_raw_materials"),
    ("/api/core/inventory/untracked-items", "untracked_items"),
    ("/api/core/inventory/output-expiry", "output_expiry_items"),
    ("/api/core/inventory/output-ready-date", "output_ready_date_items"),
]


def _make_org_and_client(db, flask_app):
    org = OrganisationFactory()
    db.commit()
    email = f"user_{uuid4()}@test.com"
    UserRepository(db).create_user(
        org_id=org.id,
        email=email,
        password_hash=AuthService.hash_password(PASSWORD),
        is_active=True,
    )
    db.commit()

    client = flask_app.test_client()
    client.environ_base["wsgi.url_scheme"] = "https"
    client.environ_base["HTTP_X_FORWARDED_PROTO"] = "https"
    login_resp = client.post("/auth/login", json={"email": email, "password": PASSWORD})
    assert login_resp.status_code == 200, login_resp.data
    return org, client


@pytest.fixture
def flask_app():
    from app.api.app_factory import create_app

    app = create_app()
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    with app.app_context():
        yield app


@pytest.fixture
def authed_client(db, flask_app):
    org, client = _make_org_and_client(db, flask_app)
    yield client
    db.rollback()
    db.query(Organisation).filter(Organisation.id == org.id).delete(synchronize_session=False)
    db.commit()


@pytest.fixture
def two_org_clients(db, flask_app):
    """Two independent orgs, each with its own authenticated client — the cross-tenant probe."""
    org_a, client_a = _make_org_and_client(db, flask_app)
    org_b, client_b = _make_org_and_client(db, flask_app)
    yield {"org_a": org_a, "client_a": client_a, "org_b": org_b, "client_b": client_b}
    db.rollback()
    db.query(Organisation).filter(Organisation.id.in_([org_a.id, org_b.id])).delete(synchronize_session=False)
    db.commit()


@pytest.mark.parametrize("path,_key", ROUTES + [("/api/core/system-findings", "findings")])
def test_route_requires_auth(flask_app, path, _key):
    """Unauthenticated request gets 401, not the org-scoped data."""
    client = flask_app.test_client()
    client.environ_base["wsgi.url_scheme"] = "https"
    client.environ_base["HTTP_X_FORWARDED_PROTO"] = "https"
    resp = client.get(path)
    assert resp.status_code == 401, resp.data


@pytest.mark.parametrize("path,key", ROUTES)
def test_route_returns_expected_shape_when_authed(authed_client, path, key):
    resp = authed_client.get(path)
    assert resp.status_code == 200, resp.data
    body = resp.get_json()
    assert key in body
    assert isinstance(body[key], list)


def test_system_findings_route_returns_findings_and_system_status(authed_client):
    resp = authed_client.get("/api/core/system-findings")
    assert resp.status_code == 200, resp.data
    body = resp.get_json()
    assert "findings" in body
    assert isinstance(body["findings"], list)
    assert "system_status" in body
    assert "mode" in body["system_status"]


def test_untracked_items_route_excludes_other_org(db, two_org_clients):
    """The cross-tenant probe at the HTTP layer: org B must never see org A's untracked item."""
    item_a = InventoryItemFactory(org_id=two_org_clients["org_a"].id, extra_data={"untracked": True})
    item_b = InventoryItemFactory(org_id=two_org_clients["org_b"].id, extra_data={"untracked": True})
    db.commit()
    try:
        resp_a = two_org_clients["client_a"].get("/api/core/inventory/untracked-items")
        resp_b = two_org_clients["client_b"].get("/api/core/inventory/untracked-items")
        assert resp_a.status_code == 200 and resp_b.status_code == 200

        ids_a = {i["id"] for i in resp_a.get_json()["untracked_items"]}
        ids_b = {i["id"] for i in resp_b.get_json()["untracked_items"]}

        assert str(item_a.id) in ids_a
        assert str(item_b.id) not in ids_a
        assert str(item_b.id) in ids_b
        assert str(item_a.id) not in ids_b
    finally:
        from app.core.db.models.inventory_item import InventoryItem

        db.query(InventoryItem).filter(InventoryItem.id.in_([item_a.id, item_b.id])).delete(synchronize_session=False)
        db.commit()


def test_system_findings_route_excludes_other_org(db, two_org_clients):
    """The aggregate /api/core/system-findings endpoint must stay org-scoped too."""
    item_a = InventoryItemFactory(org_id=two_org_clients["org_a"].id, extra_data={"untracked": True})
    db.commit()
    try:
        resp_b = two_org_clients["client_b"].get("/api/core/system-findings")
        assert resp_b.status_code == 200
        body = resp_b.get_json()
        assert not any(str(item_a.id) in str(f.get("data")) for f in body["findings"])
    finally:
        from app.core.db.models.inventory_item import InventoryItem

        db.query(InventoryItem).filter(InventoryItem.id == item_a.id).delete(synchronize_session=False)
        db.commit()
