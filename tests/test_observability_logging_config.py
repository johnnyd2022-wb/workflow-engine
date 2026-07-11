"""Tests for structured logging configuration and redaction."""

from __future__ import annotations

import json
import logging

import pytest

from app.observability.logging_config import configure_logging, get_logger


class _DummyConfig:
    log_level = "INFO"
    log_format = "json"


def test_configure_logging_outputs_json_and_redacts_sensitive_keys(capsys):
    pytest.importorskip("structlog")

    configure_logging(_DummyConfig())
    logger = get_logger("tests.observability")

    logger.info(
        "observability_test_event",
        feature="core",
        correlation_id="corr-1",
        org_id="org-1",
        user_id="user-1",
        request_id="req-1",
        trace_id="0" * 32,
        span_id="0" * 16,
        password="top-secret",
    )

    captured = capsys.readouterr().out.strip().splitlines()
    assert captured, "Expected JSON log output"
    payload = json.loads(captured[-1])

    required_keys = {
        "timestamp",
        "level",
        "logger",
        "event",
        "feature",
        "correlation_id",
        "org_id",
        "user_id",
        "trace_id",
        "span_id",
        "request_id",
    }
    assert required_keys.issubset(payload.keys())
    assert payload["password"] == "[REDACTED]"


def test_stdlib_logger_flows_through_structured_formatter(capsys):
    pytest.importorskip("structlog")

    configure_logging(_DummyConfig())
    std_logger = logging.getLogger("tests.stdlib")
    std_logger.info("stdlib_event")

    captured = capsys.readouterr().out.strip().splitlines()
    assert captured, "Expected structured output for stdlib logger"
    payload = json.loads(captured[-1])
    assert payload["event"] == "stdlib_event"
    assert payload["logger"] == "tests.stdlib"
