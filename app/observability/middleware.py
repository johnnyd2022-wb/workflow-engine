"""Observability middleware wiring helpers."""

from __future__ import annotations

import re
import time
from uuid import uuid4

from flask import g, request

from app.observability.context import feature_for_request
from app.observability.logging_config import get_logger
from app.observability.metrics import record_http_request

try:
    import structlog
except Exception:  # pragma: no cover - fallback for pre-dependency bootstrap
    structlog = None

_ACCESS_LOGGER = get_logger("app.observability.access")

# A caller-supplied X-Request-ID is kept only when it looks like an id: it is written into every
# log line and echoed in a response header, so anything else (spaces, newlines, very long) is
# replaced by this request's own id.
_SAFE_REQUEST_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{7,63}")


def incoming_request_id(value: str | None) -> str | None:
    if value and _SAFE_REQUEST_ID.fullmatch(value):
        return value
    return None


def setup_observability(app) -> None:
    """Attach request-scoped logging context and access logs."""

    @app.before_request
    def _bind_request_context():
        if structlog is not None:
            structlog.contextvars.clear_contextvars()
        g._request_start_perf = time.perf_counter()

        correlation_id = str(getattr(g, "correlation_id", uuid4()))
        request_id = incoming_request_id(request.headers.get("X-Request-ID")) or correlation_id
        # GL-C04: the reference people quote to support is this id (reference.py); it is in every
        # log line for the request and goes back on the response as X-Request-ID.
        g.request_id = request_id
        org_id = getattr(g, "org_id", None)
        user_id = getattr(g, "user_id", None)

        if structlog is not None:
            structlog.contextvars.bind_contextvars(
                feature=feature_for_request(),
                correlation_id=correlation_id,
                request_id=request_id,
                org_id=org_id,
                user_id=user_id,
                method=request.method,
                path=request.path,
                route=request.endpoint,
            )

    @app.after_request
    def _emit_access_log(response):
        request_id = getattr(g, "request_id", None)
        if request_id and "X-Request-ID" not in response.headers:
            response.headers["X-Request-ID"] = request_id
        start = getattr(g, "_request_start_perf", None)
        duration_ms = 0.0
        if start is not None:
            duration_ms = round((time.perf_counter() - start) * 1000.0, 2)

        body_bytes = response.calculate_content_length()
        feature = feature_for_request()
        record_http_request(
            feature=feature,
            route=request.endpoint,
            status_code=response.status_code,
            duration_ms=duration_ms,
        )
        _ACCESS_LOGGER.info(
            "http_request",
            status=response.status_code,
            duration_ms=duration_ms,
            bytes=body_bytes if body_bytes is not None else 0,
            feature=feature,
        )
        return response

    @app.teardown_request
    def _clear_request_context(_error):
        if structlog is not None:
            structlog.contextvars.clear_contextvars()
