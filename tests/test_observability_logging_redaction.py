"""Unit tests for observability log redaction backstop."""

from app.observability.logging_config import redact_sensitive_fields


def test_redacts_sensitive_keys_top_level_and_nested():
    event = {
        "event": "login_failure",
        "email": "person@example.com",
        "auth_token": "abc123",
        "payload": {
            "password": "super-secret",
            "profile": {"phone": "123", "api_secret": "shh"},
            "list_data": [{"cookie_value": "x"}, {"ok": "value"}],
        },
    }

    result = redact_sensitive_fields(None, "info", event)

    assert result["email"] == "[REDACTED]"
    assert result["auth_token"] == "[REDACTED]"
    assert result["payload"]["password"] == "[REDACTED]"
    assert result["payload"]["profile"]["api_secret"] == "[REDACTED]"
    assert result["payload"]["list_data"][0]["cookie_value"] == "[REDACTED]"
    assert result["payload"]["list_data"][1]["ok"] == "value"


def test_non_sensitive_fields_are_preserved():
    event = {
        "event": "inventory_write",
        "org_id": "org-1",
        "details": {"status": "ok", "count": 3},
    }

    result = redact_sensitive_fields(None, "info", event)

    assert result["event"] == "inventory_write"
    assert result["org_id"] == "org-1"
    assert result["details"]["status"] == "ok"
    assert result["details"]["count"] == 3
