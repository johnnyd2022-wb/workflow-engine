"""Tests for the demo-data slice: POST /api/core/reset-demo-db and the
reset_demo_db/clear_demo_db service functions three other suites import directly as
fixture infrastructure (test_corechecks, test_executions, test_dag_traversal).

No dedicated test file existed for this slice before this review — see
.agents/reports/demo-data/review.md. Route-level behavior (env gate, auth, the
caller-identity check added by this review's security patch, and the generic error
message on exception) is exercised through a Flask test client rather than only through
tests/e2e/demo-data/, matching the app_client pattern in tests/test_wastage.py; the
service-function edge cases (USER_NOT_FOUND / no-op-when-missing) are exercised directly
since reproducing "the demo user does not exist" against the real seeded row would break
every other suite that depends on it (see the feature index's note on this).
"""

import logging
from uuid import uuid4

import pytest

from app.core.db.models.organisation import Organisation
from app.core.db.repositories.organisation_repo import OrganisationRepository
from app.core.db.repositories.user_repo import UserRepository
from app.core.security.auth_service import AuthService
from app.features.demo_data.services.resetdb import DEMO_USER_EMAIL, clear_demo_db, reset_demo_db

TEST_PASSWORD = "TestPass123!"


@pytest.fixture
def demo_org_and_user(db):
    """The real demo org/user, created only if missing (mirrors
    tests/test_corechecks.py::ensure_demo_user) — never deleted at teardown, since other
    suites' fixtures assume this row persists across the whole test session. Its real
    password is unknown (it may be a genuinely pre-existing seeded account), so tests
    that need to log in as *a* demo-org member use `demo_org_member` below instead of
    logging in as this user directly."""
    user_repo = UserRepository(db)
    user = user_repo.get_user_by_email(DEMO_USER_EMAIL)
    if user:
        return user
    org = OrganisationRepository(db).create_org("Whistlebird Demo")
    password_hash = AuthService.hash_password(TEST_PASSWORD)
    user_repo.create_user(org_id=org.id, email=DEMO_USER_EMAIL, password_hash=password_hash)
    db.commit()
    return user_repo.get_user_by_email(DEMO_USER_EMAIL)


@pytest.fixture
def demo_org_member(db, demo_org_and_user):
    """A throwaway user in the SAME org as demo@whistlebird.co.nz, with a password this
    test controls — lets tests log in as a legitimate demo-org member without touching
    the real demo account's (unknown) credentials."""
    user = UserRepository(db).create_user(
        org_id=demo_org_and_user.org_id,
        email=f"demo-org-member-{uuid4()}@example.test",
        password_hash=AuthService.hash_password(TEST_PASSWORD),
    )
    db.commit()
    user_id = user.id
    yield user
    db.rollback()
    from app.core.db.models.audit_log import AuditLog
    from app.core.db.models.user import User

    db.query(AuditLog).filter(AuditLog.user_id == user_id).delete(synchronize_session=False)
    db.query(User).filter(User.id == user_id).delete(synchronize_session=False)
    db.commit()


@pytest.fixture
def outsider_org(db):
    """Deleting the organisation directly (not its users first) cascades both `users`
    (`users_org_id_fkey`) and `audit_logs` (`audit_logs_org_id_fkey`) — both `ON DELETE
    CASCADE` — in the right order in one statement, avoiding the FK ordering trouble a
    manual users-then-audit_logs delete runs into (audit_logs.user_id has no cascade)."""
    organisation = OrganisationRepository(db).create_org(f"Outsider Org {uuid4().hex[:8]}")
    db.commit()
    org_id = organisation.id
    yield organisation
    db.rollback()
    db.query(Organisation).filter(Organisation.id == org_id).delete(synchronize_session=False)
    db.commit()


@pytest.fixture
def outsider_user(db, outsider_org):
    user = UserRepository(db).create_user(
        org_id=outsider_org.id,
        email=f"outsider_{uuid4()}@example.test",
        password_hash=AuthService.hash_password(TEST_PASSWORD),
    )
    db.commit()
    return user


@pytest.fixture
def flask_app():
    """A real app instance, built during fixture setup (not inside a test body).

    create_app() -> configure_logging() unconditionally replaces the root logger's
    handler list, which silently discards pytest's caplog handler if it's called
    *during* a test body (after caplog's own per-test handler has already attached).
    Building the app here, as a fixture, means create_app() runs during pytest's setup
    phase — before caplog's handler attachment — so caplog keeps working for any test
    that requests both. Same pattern as tests/test_executions.py's `flask_app` fixture.
    """
    from app.api.app_factory import create_app

    app = create_app()
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    return app


def _logged_in_client(flask_app, user, password: str = TEST_PASSWORD):
    client = flask_app.test_client()
    client.environ_base["wsgi.url_scheme"] = "https"
    client.environ_base["HTTP_X_FORWARDED_PROTO"] = "https"
    with flask_app.app_context():
        resp = client.post(
            "/auth/login", json={"email": user.email, "password": password}, content_type="application/json"
        )
        assert resp.status_code in (200, 201), f"login failed: {resp.data}"
    return client


# --------------------------------------------------------------------------------------
# Route: POST /api/core/reset-demo-db
# --------------------------------------------------------------------------------------


def test_env_gate_blocks_outside_test_and_local(monkeypatch, flask_app, demo_org_member):
    # Log in first, under the real local/test environment — create_app() itself refuses
    # to boot with the dev-fallback secret key outside local/test, so "production" can
    # only be simulated for the one check this route makes, not for the whole app.
    client = _logged_in_client(flask_app, demo_org_member)

    from app.utils.config_loader import config

    monkeypatch.setattr(config, "environment", "production")
    resp = client.post("/api/core/reset-demo-db")

    assert resp.status_code == 403
    body = resp.get_json()
    assert body["success"] is False
    assert "test or local" in body["error"]


def test_unauthenticated_reset_is_rejected(flask_app):
    client = flask_app.test_client()
    client.environ_base["wsgi.url_scheme"] = "https"
    client.environ_base["HTTP_X_FORWARDED_PROTO"] = "https"

    resp = client.post("/api/core/reset-demo-db")

    assert resp.status_code == 401


def test_demo_org_member_can_reset(flask_app, demo_org_member, db, caplog):
    """Reset twice — a real "reset demo data" button gets clicked more than once, and
    the second call is what exercises reset_demo_db's delete-existing-data branches
    (there is data left over from the first call to delete). Also asserts the
    demo_data_reset_completed INFO log the observability stage added (state-changing
    operations get a stable event name per the observability skill's convention)."""
    client = _logged_in_client(flask_app, demo_org_member)

    with caplog.at_level(logging.INFO):
        first = client.post("/api/core/reset-demo-db")
    assert first.status_code == 200, first.data
    assert first.get_json()["success"] is True

    completions = [r for r in caplog.records if "demo_data_reset_completed" in r.getMessage()]
    assert completions, f"successful reset was not logged: {[r.getMessage() for r in caplog.records]}"

    second = client.post("/api/core/reset-demo-db")
    assert second.status_code == 200, second.data
    assert second.get_json()["success"] is True

    clear_demo_db(db)


def test_outsider_org_member_gets_403_forbidden(flask_app, demo_org_member, outsider_user, caplog):
    """The security fix from this review: a caller who is not a member of the demo org
    must be explicitly rejected, not merely relying on the global tenant filter's
    incidental side effect (see security-audit.md's "Empirical correction"), and that
    rejection must be observable (access_denied — same convention as the auth
    decorators and tests/test_executions.py::TestFlowProcessAccessObservability)."""
    client = _logged_in_client(flask_app, outsider_user)

    with caplog.at_level(logging.WARNING):
        resp = client.post("/api/core/reset-demo-db")

    assert resp.status_code == 403
    body = resp.get_json()
    assert body["success"] is False
    assert body["error"] == "FORBIDDEN"

    denials = [r for r in caplog.records if "access_denied" in r.getMessage()]
    assert denials, f"cross-org reset attempt was not logged: {[r.getMessage() for r in caplog.records]}"


def test_exception_during_reset_returns_generic_message_not_raw_exception(monkeypatch, flask_app, demo_org_member):
    """F2 (security-audit.md): the raw exception string must never reach the client."""
    import app.features.demo_data.services.resetdb as resetdb_module

    def _boom(db):
        raise RuntimeError("super secret constraint detail: uq_inventory_items_org_name_batch")

    monkeypatch.setattr(resetdb_module, "reset_demo_db", _boom)
    client = _logged_in_client(flask_app, demo_org_member)

    resp = client.post("/api/core/reset-demo-db")

    assert resp.status_code == 500
    body = resp.get_json()
    assert body["error"] == "RESET_FAILED"
    assert "super secret constraint detail" not in body["message"]


# --------------------------------------------------------------------------------------
# Service functions: reset_demo_db / clear_demo_db edge cases
# --------------------------------------------------------------------------------------


def test_reset_demo_db_returns_user_not_found_when_demo_user_missing(monkeypatch, db):
    monkeypatch.setattr(UserRepository, "get_user_by_email", lambda self, email: None)

    result = reset_demo_db(db)

    assert result == {
        "success": False,
        "message": f"User {DEMO_USER_EMAIL} not found. Create the demo user first.",
        "error": "USER_NOT_FOUND",
    }


def test_clear_demo_db_is_noop_when_demo_user_missing(monkeypatch, db):
    monkeypatch.setattr(UserRepository, "get_user_by_email", lambda self, email: None)

    assert clear_demo_db(db) is None
