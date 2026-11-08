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


# --- GL-S04: personal data inside free text and error reports -----------------------------------


def test_free_text_loses_emails_constraint_values_parameters_and_tokens():
    from app.observability.logging_config import scrub_personal_text

    event = {
        "event": "save_failed",
        "error": (
            'duplicate key value violates unique constraint "uq_users_email"\n'
            "DETAIL:  Key (org_id, email)=(7f1c, jo@whistlebird.co.nz) already exists.\n"
            "[SQL: INSERT INTO users ...] [parameters: {'notes': 'RECIPE: 40g juniper'}]"
        ),
        "path": "/invite/Ab3Ab3Ab3Ab3Ab3Ab3Ab3Ab3?token=abc",
        "nested": [{"message": "reply sent to buyer@liquorland.co.nz"}],
        "count": 3,
    }
    out = scrub_personal_text(None, "error", event)
    text = repr(out)
    for leaked in ("jo@whistlebird.co.nz", "RECIPE", "juniper", "Ab3Ab3", "token=abc", "buyer@liquorland"):
        assert leaked not in text, leaked
    # What a developer needs to act on stays: the constraint, the columns, the route.
    assert "uq_users_email" in out["error"] and "Key (org_id, email)=([REDACTED]) already exists" in out["error"]
    assert out["path"] == "/invite/[REDACTED]?token=[REDACTED]"
    assert out["nested"][0]["message"] == "reply sent to [EMAIL]"
    assert out["count"] == 3


def test_a_failed_statement_does_not_carry_its_values():
    """hide_parameters: the bound values never become part of the error's text."""
    import pytest
    from sqlalchemy import text

    from app.core.db import engine

    with pytest.raises(Exception) as caught, engine.connect() as conn:
        conn.execute(text("select 1/0 where :note = :note"), {"note": "RECIPE: 40g juniper"})
    assert "juniper" not in str(caught.value)
    assert "hidden due to hide_parameters" in str(caught.value)


def test_a_logged_traceback_is_scrubbed_before_it_is_written(capsys):
    """The whole pipeline: an exception's message, rendered as a traceback, is scrubbed too."""
    import logging
    from types import SimpleNamespace

    from app.observability.logging_config import configure_logging, get_logger

    root = logging.getLogger()
    before = (list(root.handlers), root.level)
    try:
        configure_logging(SimpleNamespace(log_level="INFO", log_format="json", otel_enabled=False))
        try:
            recipe = "RECIPE: 40g juniper per litre"  # noqa: F841 -- a local the traceback must not carry
            raise ValueError("Key (email)=(jo@whistlebird.co.nz) already exists")
        except ValueError:
            get_logger("gl-s04").exception("save_failed", note="sent to buyer@liquorland.co.nz")
        written = capsys.readouterr().out
    finally:
        root.handlers = before[0]
        root.setLevel(before[1])
    assert "save_failed" in written
    assert "jo@whistlebird.co.nz" not in written and "buyer@liquorland.co.nz" not in written
    assert "[REDACTED]" in written and "[EMAIL]" in written
    assert "juniper" not in written and '"locals"' not in written  # frames, but not their variables
    assert "test_a_logged_traceback_is_scrubbed_before_it_is_written" in written
