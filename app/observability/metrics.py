"""Metrics setup hooks."""

from __future__ import annotations

import logging
from typing import Any

from app.observability.resource import build_resource, otlp_http_signal_endpoint

LOGGER = logging.getLogger(__name__)
_METRICS_CONFIGURED = False

_HTTP_REQUEST_COUNTER = None
_HTTP_ERROR_COUNTER = None
_HTTP_DURATION_HISTOGRAM = None
_BUSINESS_COUNTERS: dict[str, Any] = {}


def configure_metrics(config: Any) -> None:
    """Configure OTel metrics provider/exporters."""
    global _METRICS_CONFIGURED

    if _METRICS_CONFIGURED:
        return
    if not bool(getattr(config, "otel_enabled", False)):
        return
    if not bool(getattr(config, "grafana_data_enabled", False)):
        return
    if not bool(getattr(config, "otel_capture_metrics", True)):
        return
    if str(getattr(config, "environment", "")).strip().lower() == "test":
        return

    try:
        from opentelemetry import metrics
        from opentelemetry.sdk.metrics import MeterProvider
        from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
    except Exception as exc:
        LOGGER.warning("otel_metrics_unavailable", error=str(exc))
        return

    exporter = _build_metric_exporter(config)
    if exporter is None:
        return

    try:
        reader = PeriodicExportingMetricReader(exporter)
        provider = MeterProvider(metric_readers=[reader], resource=build_resource(config))
        metrics.set_meter_provider(provider)
        meter = metrics.get_meter("workflow-engine")
    except Exception as exc:
        LOGGER.warning("otel_metrics_setup_failed", error=str(exc))
        return

    _configure_http_instruments(meter)
    _configure_business_instruments(meter)
    _METRICS_CONFIGURED = True


def record_http_request(feature: str, route: str | None, status_code: int, duration_ms: float) -> None:
    """Record RED metrics from the request access-log hook."""
    if _HTTP_REQUEST_COUNTER is None or _HTTP_DURATION_HISTOGRAM is None:
        return
    attributes = {
        "feature": feature,
        "route": route or "unknown",
        "status_class": _status_class(status_code),
    }
    _HTTP_REQUEST_COUNTER.add(1, attributes)
    _HTTP_DURATION_HISTOGRAM.record(float(duration_ms), attributes)
    if status_code >= 500 and _HTTP_ERROR_COUNTER is not None:
        _HTTP_ERROR_COUNTER.add(1, attributes)


def increment_business_counter(name: str, value: int = 1, attributes: dict[str, Any] | None = None) -> None:
    counter = _BUSINESS_COUNTERS.get(name)
    if counter is None:
        return
    counter.add(int(value), attributes or {})


def _build_metric_exporter(config: Any):
    protocol = str(getattr(config, "otel_exporter_protocol", "grpc")).strip().lower()
    endpoint = str(getattr(config, "otel_exporter_endpoint", "")).strip()
    if not endpoint:
        return None

    try:
        if protocol == "http/protobuf":
            from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter

            return OTLPMetricExporter(endpoint=otlp_http_signal_endpoint(endpoint, "metrics"))
        else:
            from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter

            kwargs: dict[str, Any] = {"endpoint": endpoint}
            if endpoint.startswith("http://"):
                kwargs["insecure"] = True
            return OTLPMetricExporter(**kwargs)
    except Exception as exc:
        LOGGER.warning("otel_metric_exporter_init_failed", error=str(exc), protocol=protocol, endpoint=endpoint)
        return None


def _configure_http_instruments(meter: Any) -> None:
    global _HTTP_REQUEST_COUNTER, _HTTP_ERROR_COUNTER, _HTTP_DURATION_HISTOGRAM

    _HTTP_REQUEST_COUNTER = meter.create_counter(
        "http.server.requests",
        unit="1",
        description="Total HTTP requests by feature/route/status class.",
    )
    _HTTP_ERROR_COUNTER = meter.create_counter(
        "http.server.errors",
        unit="1",
        description="Total HTTP 5xx responses by feature/route/status class.",
    )
    _HTTP_DURATION_HISTOGRAM = meter.create_histogram(
        "http.server.duration_ms",
        unit="ms",
        description="HTTP request duration in milliseconds.",
    )


def _configure_business_instruments(meter: Any) -> None:
    for metric_name in (
        "executions_started",
        "steps_completed",
        "inventory_writes",
        "invoices_created",
        "xero_sync_failures",
        "login_failures",
        "rate_limit_hits",
    ):
        _BUSINESS_COUNTERS[metric_name] = meter.create_counter(
            f"workflow.{metric_name}",
            unit="1",
            description=f"Business counter: {metric_name}.",
        )


def _status_class(status_code: int) -> str:
    try:
        status_bucket = int(status_code) // 100
    except (TypeError, ValueError):
        return "unknown"
    if status_bucket < 1 or status_bucket > 5:
        return "unknown"
    return f"{status_bucket}xx"
