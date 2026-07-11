"""Shared OpenTelemetry resource and endpoint helpers."""

from __future__ import annotations

from typing import Any
from urllib.parse import urlsplit, urlunsplit


def build_resource(config: Any):
    """Return the common resource identity for every emitted OTel signal."""
    from opentelemetry.sdk.resources import Resource

    return Resource.create(
        {
            "service.name": str(getattr(config, "otel_service_name", "workflow-engine")),
            "service.namespace": "workflow-engine",
            "deployment.environment": str(getattr(config, "environment", "local")),
        }
    )


def otlp_http_signal_endpoint(endpoint: str, signal: str) -> str:
    """Turn a configured OTLP/HTTP base URL into its signal-specific endpoint."""
    parsed = urlsplit(endpoint.strip())
    path = parsed.path.rstrip("/")
    expected_suffix = f"/v1/{signal}"
    if path == expected_suffix:
        return endpoint
    return urlunsplit((parsed.scheme, parsed.netloc, f"{path}{expected_suffix}", parsed.query, parsed.fragment))
