"""Regression test for a verbose-error-to-client fix in reconciliation_routes.py.

Found by the bize-verbose-error-to-client learned semgrep rule (originally written
during a review-feature audit of a different blueprint, org_routes.py) firing on this
file too: reconcile_via_execution_route() returned the raw ValueError text from a failed
UUID(...) parse directly in its JSON error body. Low severity here (the message is just
Python's stdlib "badly formed hexadecimal UUID string", not DB/SQL detail), but the same
vulnerability class, so fixed the same way -- log server-side, return a fixed message.
"""

from uuid import uuid4

import pytest

from app.core.db.models.organisation import Organisation
from app.core.db.repositories.user_repo import UserRepository
from app.core.security.auth_service import AuthService
from tests.factories import DEFAULT_TEST_PASSWORD, OrganisationFactory

PASSWORD = DEFAULT_TEST_PASSWORD


@pytest.fixture
def authed_client(db):
    org = OrganisationFactory()
    db.commit()
    org_id = org.id

    email = f"user_{uuid4()}@test.com"
    UserRepository(db).create_user(
        org_id=org_id,
        email=email,
        password_hash=AuthService.hash_password(PASSWORD),
        is_active=True,
    )
    db.commit()

    from app.api.app_factory import create_app

    flask_app = create_app()
    flask_app.config["TESTING"] = True
    flask_app.config["WTF_CSRF_ENABLED"] = False

    with flask_app.app_context():
        client = flask_app.test_client()
        client.environ_base["wsgi.url_scheme"] = "https"
        client.environ_base["HTTP_X_FORWARDED_PROTO"] = "https"
        login_resp = client.post("/auth/login", json={"email": email, "password": PASSWORD})
        assert login_resp.status_code == 200, login_resp.data
        yield client

    db.rollback()
    db.query(Organisation).filter(Organisation.id == org_id).delete(synchronize_session=False)
    db.commit()


def test_reconcile_via_execution_invalid_uuid_does_not_leak_exception_text(authed_client):
    resp = authed_client.post(
        "/api/core/inventory/reconcile/via-execution",
        json={
            "untracked_item_id": "not-a-uuid",
            "process_id": str(uuid4()),
            "step_id": str(uuid4()),
            "output_name": "Test Output",
            "output_quantity": 1,
            "output_unit": "kg",
        },
    )
    assert resp.status_code == 400, resp.data
    body = resp.get_data(as_text=True)
    assert "not-a-uuid" not in body
    assert "badly formed" not in body.lower()
    assert resp.get_json()["error"] == "Invalid untracked_item_id, process_id, or step_id"


# --------------------------------------------------------------------------------------
# AC29/AC30 request-validation 400 paths (test-evaluator round 2, priority 3)
# --------------------------------------------------------------------------------------


def test_matching_untracked_rejects_malformed_process_id(authed_client):
    resp = authed_client.get(
        "/api/core/inventory/reconcile/matching-untracked",
        query_string={"name": "Widget", "unit": "kg", "process_id": "not-a-uuid"},
    )
    assert resp.status_code == 400, resp.data
    assert resp.get_json()["error"] == "Invalid process_id"


@pytest.mark.parametrize(
    ("query", "missing"),
    [({"unit": "kg"}, "name"), ({"name": "Widget"}, "unit"), ({}, "both")],
)
def test_matching_untracked_returns_empty_list_when_name_or_unit_missing(authed_client, query, missing):
    """AC29: BOTH name and unit are required — an empty result, not a 400, is the
    documented behaviour when either is absent.

    Parameterized because the single missing-name case left a route that had stopped
    handling a missing *unit* fully green (test-evaluator round 3).
    """
    resp = authed_client.get("/api/core/inventory/reconcile/matching-untracked", query_string=query)
    assert resp.status_code == 200, resp.data
    assert resp.get_json() == {"matching_untracked": []}, f"missing {missing} must yield an empty match set"


def test_reconcile_via_addition_rejects_missing_name(authed_client):
    resp = authed_client.post(
        "/api/core/inventory/reconcile/via-addition",
        json={"quantity": 5, "unit": "kg"},
    )
    assert resp.status_code == 400, resp.data
    assert resp.get_json()["error"] == "name is required"


def test_reconcile_via_addition_rejects_missing_quantity(authed_client):
    resp = authed_client.post(
        "/api/core/inventory/reconcile/via-addition",
        json={"name": "Widget", "unit": "kg"},
    )
    assert resp.status_code == 400, resp.data
    assert resp.get_json()["error"] == "quantity is required"


def test_reconcile_via_addition_rejects_missing_unit(authed_client):
    resp = authed_client.post(
        "/api/core/inventory/reconcile/via-addition",
        json={"name": "Widget", "quantity": 5},
    )
    assert resp.status_code == 400, resp.data
    assert resp.get_json()["error"] == "unit is required"


def test_reconcile_via_addition_rejects_malformed_untracked_item_id(authed_client):
    resp = authed_client.post(
        "/api/core/inventory/reconcile/via-addition",
        json={"name": "Widget", "quantity": 5, "unit": "kg", "untracked_item_id": "not-a-uuid"},
    )
    assert resp.status_code == 400, resp.data
    assert resp.get_json()["error"] == "Invalid untracked_item_id"


def test_reconcile_via_execution_rejects_missing_untracked_item_id(authed_client):
    resp = authed_client.post(
        "/api/core/inventory/reconcile/via-execution",
        json={
            "process_id": str(uuid4()),
            "step_id": str(uuid4()),
            "output_name": "Distillate",
            "output_quantity": 1,
            "output_unit": "kg",
        },
    )
    assert resp.status_code == 400, resp.data
    assert resp.get_json()["error"] == "untracked_item_id is required"


def test_reconcile_via_execution_rejects_missing_process_id(authed_client):
    resp = authed_client.post(
        "/api/core/inventory/reconcile/via-execution",
        json={
            "untracked_item_id": str(uuid4()),
            "step_id": str(uuid4()),
            "output_name": "Distillate",
            "output_quantity": 1,
            "output_unit": "kg",
        },
    )
    assert resp.status_code == 400, resp.data
    assert resp.get_json()["error"] == "process_id is required"


def test_reconcile_via_execution_rejects_missing_step_id(authed_client):
    resp = authed_client.post(
        "/api/core/inventory/reconcile/via-execution",
        json={
            "untracked_item_id": str(uuid4()),
            "process_id": str(uuid4()),
            "output_name": "Distillate",
            "output_quantity": 1,
            "output_unit": "kg",
        },
    )
    assert resp.status_code == 400, resp.data
    assert resp.get_json()["error"] == "step_id is required"
