"""Tests for shared OpenTelemetry resource and OTLP/HTTP endpoint configuration."""

from app.observability.resource import build_resource, otlp_http_signal_endpoint


class _DummyConfig:
    environment = "production"
    otel_service_name = "workflow-engine"


def test_resource_has_consistent_service_identity():
    resource = build_resource(_DummyConfig())

    assert resource.attributes["service.name"] == "workflow-engine"
    assert resource.attributes["service.namespace"] == "workflow-engine"
    assert resource.attributes["deployment.environment"] == "production"


def test_otlp_http_endpoint_uses_signal_path():
    assert otlp_http_signal_endpoint("http://collector:4318", "logs") == "http://collector:4318/v1/logs"
    assert otlp_http_signal_endpoint("https://collector/v1/traces", "traces") == "https://collector/v1/traces"
