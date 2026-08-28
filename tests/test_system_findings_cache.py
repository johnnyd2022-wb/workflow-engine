"""Read-through cache for /api/core/system-findings.

The endpoint's contract (findings + system_status shape, org scoping, 401) is covered by
test_corechecks_routes.py. This file covers the caching layer added on top:

- first request computes and stores; subsequent requests are served from the row
- an inventory/execution/process mutation marks the row stale -> next request recomputes
- an unrelated event (user.login) does NOT invalidate
- an expired row (past TTL) recomputes
- the cache is per-org
"""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import text

from app.core.backend import system_findings_cache as sfc
from app.core.db.models.organisation import Organisation
from app.core.db.models.system_findings_cache import SystemFindingsCache
from app.core.db.repositories.user_repo import UserRepository
from app.core.security.auth_service import AuthService
from tests.factories import DEFAULT_TEST_PASSWORD, OrganisationFactory

PASSWORD = DEFAULT_TEST_PASSWORD
ENDPOINT = "/api/core/system-findings"


@pytest.fixture
def flask_app():
    from app.api.app_factory import create_app

    app = create_app()
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    with app.app_context():
        yield app


def _make_org_and_client(db, flask_app):
    org = OrganisationFactory()
    db.commit()
    email = f"user_{uuid4()}@test.com"
    UserRepository(db).create_user(
        org_id=org.id, email=email, password_hash=AuthService.hash_password(PASSWORD), is_active=True
    )
    db.commit()
    client = flask_app.test_client()
    client.environ_base["wsgi.url_scheme"] = "https"
    client.environ_base["HTTP_X_FORWARDED_PROTO"] = "https"
    assert client.post("/auth/login", json={"email": email, "password": PASSWORD}).status_code == 200
    return org, client


def _cache_row(db, org_id):
    return db.query(SystemFindingsCache).filter_by(org_id=org_id).first()


@pytest.fixture
def authed(db, flask_app):
    org, client = _make_org_and_client(db, flask_app)
    yield org, client
    db.rollback()
    db.query(SystemFindingsCache).filter_by(org_id=org.id).delete(synchronize_session=False)
    db.query(Organisation).filter_by(id=org.id).delete(synchronize_session=False)
    db.commit()


def test_first_call_computes_and_stores_then_serves_from_cache(db, authed, monkeypatch):
    org, client = authed
    calls = {"n": 0}
    real_compute = sfc._compute

    def counting_compute(org_id, session):
        calls["n"] += 1
        return real_compute(org_id, session)

    monkeypatch.setattr(sfc, "_compute", counting_compute)

    first = client.get(ENDPOINT)
    assert first.status_code == 200
    assert set(first.get_json()) == {"findings", "system_status"}
    assert calls["n"] == 1
    assert _cache_row(db, org.id) is not None

    # three more calls -> no further computes, byte-identical payload
    for _ in range(3):
        r = client.get(ENDPOINT)
        assert r.status_code == 200
        assert r.get_data() == first.get_data()
    assert calls["n"] == 1


def test_invalidating_event_marks_stale_and_forces_recompute(db, authed, monkeypatch):
    org, client = authed
    calls = {"n": 0}
    real = sfc._compute
    monkeypatch.setattr(sfc, "_compute", lambda o, s: (calls.__setitem__("n", calls["n"] + 1) or real(o, s)))

    client.get(ENDPOINT)
    assert calls["n"] == 1
    client.get(ENDPOINT)
    assert calls["n"] == 1  # cached

    # an inventory mutation goes through EventWriter -> mark_stale
    from app.core.backend.event_writer import EventWriter

    EventWriter(db, org.id).emit("inventory_item.updated", "inventory_item", uuid4(), {"x": 1})
    db.commit()
    assert _cache_row(db, org.id).stale is True

    client.get(ENDPOINT)
    assert calls["n"] == 2  # recomputed
    db.expire_all()
    assert _cache_row(db, org.id).stale is False  # recompute cleared it


def test_unrelated_event_does_not_invalidate(db, authed, monkeypatch):
    org, client = authed
    calls = {"n": 0}
    real = sfc._compute
    monkeypatch.setattr(sfc, "_compute", lambda o, s: (calls.__setitem__("n", calls["n"] + 1) or real(o, s)))

    client.get(ENDPOINT)
    from app.core.backend.event_writer import EventWriter

    EventWriter(db, org.id).emit("user.login", "user", uuid4(), {"ip": "127.0.0.1"})
    db.commit()
    db.expire_all()
    assert _cache_row(db, org.id).stale is False

    client.get(ENDPOINT)
    assert calls["n"] == 1  # still cached


def test_expired_row_recomputes(db, authed, monkeypatch):
    org, client = authed
    calls = {"n": 0}
    real = sfc._compute
    monkeypatch.setattr(sfc, "_compute", lambda o, s: (calls.__setitem__("n", calls["n"] + 1) or real(o, s)))

    client.get(ENDPOINT)
    assert calls["n"] == 1

    # backdate the row past the TTL
    old = datetime.now(UTC) - sfc.TTL - timedelta(minutes=1)
    db.execute(
        text("UPDATE system_findings_cache SET computed_at = :t WHERE org_id = :o"),
        {"t": old, "o": str(org.id)},
    )
    db.commit()

    client.get(ENDPOINT)
    assert calls["n"] == 2


def test_cache_is_per_org(db, flask_app):
    org_a, client_a = _make_org_and_client(db, flask_app)
    org_b, client_b = _make_org_and_client(db, flask_app)
    try:
        client_a.get(ENDPOINT)
        client_b.get(ENDPOINT)
        assert _cache_row(db, org_a.id) is not None
        assert _cache_row(db, org_b.id) is not None
        assert _cache_row(db, org_a.id).id != _cache_row(db, org_b.id).id

        # invalidating org A must not touch org B's row
        from app.core.backend.event_writer import EventWriter

        EventWriter(db, org_a.id).emit("execution.step_completed", "execution", uuid4(), {})
        db.commit()
        db.expire_all()
        assert _cache_row(db, org_a.id).stale is True
        assert _cache_row(db, org_b.id).stale is False
    finally:
        db.rollback()
        for oid in (org_a.id, org_b.id):
            db.query(SystemFindingsCache).filter_by(org_id=oid).delete(synchronize_session=False)
            db.query(Organisation).filter_by(id=oid).delete(synchronize_session=False)
        db.commit()
