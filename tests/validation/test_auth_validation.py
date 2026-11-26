from uuid import uuid4

import pytest

from app.api.app_factory import create_app
from tests.test_auth_password_session import account  # noqa: F401
from tests.test_go_live import _admin_client, _cleanup, flask_app  # noqa: F401


@pytest.fixture
def anonymous():
    app = create_app()
    app.config.update(TESTING=True, WTF_CSRF_ENABLED=False)
    client = app.test_client()
    client.environ_base["REMOTE_ADDR"] = f"validation-{uuid4()}"
    client.environ_base["wsgi.url_scheme"] = "https"
    client.environ_base["HTTP_X_FORWARDED_PROTO"] = "https"
    return client


@pytest.mark.parametrize(
    ("path", "payload", "field"),
    [
        ("/auth/signup", ["unexpected"], "_body"),
        ("/auth/login", "unexpected", "_body"),
        ("/auth/signup", {"email": "person@example.test"}, "org_name"),
        ("/auth/login", {"email": True, "password": "Example123!"}, "email"),
        ("/auth/login", {"email": "person@example.test", "password": True}, "password"),
        (
            "/auth/login",
            {"email": "person@example.test", "password": "Example123!", "device_fingerprint": []},
            "device_fingerprint",
        ),
        ("/auth/verify-2fa", {"token": 123456}, "token"),
        ("/auth/verify-2fa", {"token": "123456", "remember_device": "false"}, "remember_device"),
        ("/auth/verify-2fa", {"token": "1234"}, "token"),
        ("/auth/accept-invite", {"token": []}, "token"),
        ("/auth/password-policy-check", {"password": 123456}, "password"),
        ("/auth/password-policy-check", {"password": "Example123!", "ignored": True}, "_body"),
    ],
)
def test_auth_json_fields(anonymous, path, payload, field):
    response = anonymous.post(path, json=payload)
    assert response.status_code == 400
    assert field in response.json["errors"]


@pytest.mark.parametrize(
    ("method", "path", "payload", "field"),
    [
        ("PUT", "/auth/session-timeout", ["unexpected"], "_body"),
        ("PUT", "/auth/session-timeout", {"session_timeout_minutes": "60"}, "session_timeout_minutes"),
        ("PUT", "/auth/settings", {"email": 7}, "email"),
        ("PUT", "/auth/settings", {"first_name": "a" * 256}, "first_name"),
        ("POST", "/auth/2fa/enable", {"token1": 123456, "token2": "234567"}, "token1"),
        (
            "POST",
            "/auth/change-password",
            {"current_password": [], "new_password": "NewValidPass123!"},
            "current_password",
        ),
    ],
)
def test_account_json_fields(account, method, path, payload, field):  # noqa: F811
    response = account["client"].open(path, method=method, json=payload)
    assert response.status_code == 400
    assert field in response.json["errors"]


def test_google_callback_requires_ascii_state(anonymous):
    from time import time

    with anonymous.session_transaction() as session:
        session["google_flow"] = {"state": "a" * 43, "created_at": time()}
    response = anonymous.get("/auth/google/callback", query_string={"state": "é"})
    assert response.status_code == 400


@pytest.fixture
def go_live_client(db, flask_app):  # noqa: F811
    org, client = _admin_client(db, flask_app)
    org_id = org.id
    try:
        yield client
    finally:
        _cleanup(db, org_id)


@pytest.mark.parametrize(
    ("values", "field"),
    [
        ({"name": 10}, "name"),
        ({"quantity": "0.00001"}, "quantity"),
        ({"quantity": "1e15"}, "quantity"),
        ({"abv_percent": "NaN"}, "abv_percent"),
        ({"abv_percent": "100.1"}, "abv_percent"),
        ({"batch_id": "X" * 256}, "batch_id"),
        ({"inventory_type": []}, "inventory_type"),
        ({"unit": ["L"]}, "unit"),
        ({"bottled_on": "not a date"}, "bottled_on"),
    ],
)
def test_opening_stock_rejects_invalid_rows_before_writing(go_live_client, values, field):
    client = go_live_client
    assert client.put("/api/core/go-live", json={"go_live_date": "2026-10-01"}).status_code == 200
    row = {"name": "Opening stock", "unit": "L", "quantity": "1", "inventory_type": "work_in_progress"}
    response = client.post("/api/core/opening-stock", json={"items": [row, {**row, **values}]})
    assert response.status_code == 400
    assert "items.1." + field in response.json["errors"]
    assert client.get("/api/core/go-live").json["opening_items"] == []


def test_go_live_date_requires_a_json_object(go_live_client):
    response = go_live_client.put("/api/core/go-live", json=["2026-10-01"])
    assert response.status_code == 400
    assert "_body" in response.json["errors"]
