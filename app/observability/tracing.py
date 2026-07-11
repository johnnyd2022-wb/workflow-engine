"""Tracing helpers and extension points."""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from functools import wraps
from typing import Any

from app.observability.resource import build_resource, otlp_http_signal_endpoint

LOGGER = logging.getLogger(__name__)
_TRACING_CONFIGURED = False


def configure_tracing(app: Any, config: Any) -> None:
    """Configure OpenTelemetry tracing provider and Flask instrumentation."""
    global _TRACING_CONFIGURED

    if not bool(getattr(config, "otel_enabled", False)):
        return
    if not bool(getattr(config, "grafana_data_enabled", False)):
        return

    try:
        from opentelemetry import trace
        from opentelemetry.baggage.propagation import W3CBaggagePropagator
        from opentelemetry.instrumentation.flask import FlaskInstrumentor
        from opentelemetry.propagate import set_global_textmap
        from opentelemetry.propagators.composite import CompositePropagator
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
        from opentelemetry.sdk.trace.sampling import ParentBased, TraceIdRatioBased
        from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator
    except Exception as exc:
        LOGGER.warning("otel_tracing_unavailable", error=str(exc))
        return

    if not _TRACING_CONFIGURED:
        sample_rate = _clamp_sample_rate(getattr(config, "otel_sample_rate", 0.1))
        resource = build_resource(config)
        provider = TracerProvider(
            resource=resource,
            sampler=ParentBased(root=TraceIdRatioBased(sample_rate)),
        )

        exporter = _build_span_exporter(config)
        if exporter is not None:
            provider.add_span_processor(BatchSpanProcessor(exporter))

        try:
            trace.set_tracer_provider(provider)
            set_global_textmap(
                CompositePropagator(
                    [
                        TraceContextTextMapPropagator(),
                        W3CBaggagePropagator(),
                    ]
                )
            )
            _TRACING_CONFIGURED = True
        except Exception as exc:
            LOGGER.warning("otel_tracing_setup_failed", error=str(exc))

    if app is not None and not getattr(app, "_otel_flask_instrumented", False):
        try:
            FlaskInstrumentor().instrument_app(app)
            app._otel_flask_instrumented = True
        except Exception as exc:
            LOGGER.warning("otel_flask_instrumentation_failed", error=str(exc))


def add_otel_context(_logger: Any, _method_name: str, event_dict: dict[str, Any]) -> dict[str, Any]:
    """Inject active span ids into the event dictionary for log/trace correlation."""
    try:
        from opentelemetry import trace
    except Exception:
        return event_dict

    span = trace.get_current_span()
    if span is None:
        return event_dict

    span_context = span.get_span_context()
    trace_id = getattr(span_context, "trace_id", 0)
    span_id = getattr(span_context, "span_id", 0)
    is_valid = getattr(span_context, "is_valid", False)
    if not is_valid or not trace_id or not span_id:
        return event_dict

    event_dict.setdefault("trace_id", f"{trace_id:032x}")
    event_dict.setdefault("span_id", f"{span_id:016x}")
    return event_dict


def traced(
    name: str,
    attributes_fn: Callable[..., dict[str, Any]] | None = None,
) -> Callable[..., Any]:
    """Wrap a function call in an OTel span."""

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            with start_span(name=name, attributes=(attributes_fn(*args, **kwargs) if attributes_fn else None)):
                return func(*args, **kwargs)

        return wrapper

    return decorator


@contextmanager
def start_span(name: str, attributes: dict[str, Any] | None = None) -> Iterator[Any]:
    """Create an OTel span if tracing is available; otherwise yield a no-op context."""
    try:
        from opentelemetry import trace
    except Exception:
        yield None
        return

    tracer = trace.get_tracer("workflow-engine")
    with tracer.start_as_current_span(name) as span:
        if span and attributes:
            for key, value in attributes.items():
                if value is None:
                    continue
                span.set_attribute(key, value)
        yield span


def _clamp_sample_rate(raw: Any) -> float:
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return 0.1
    return max(0.0, min(1.0, value))


def _build_span_exporter(config: Any):
    """Build OTLP span exporter based on configured protocol/environment."""
    environment = str(getattr(config, "environment", "")).strip().lower()
    if environment == "test":
        return None

    endpoint = str(getattr(config, "otel_exporter_endpoint", "")).strip()
    protocol = str(getattr(config, "otel_exporter_protocol", "grpc")).strip().lower()
    if not endpoint:
        return None

    try:
        if protocol == "http/protobuf":
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

            return OTLPSpanExporter(endpoint=otlp_http_signal_endpoint(endpoint, "traces"))
        else:
            from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter

            kwargs: dict[str, Any] = {"endpoint": endpoint}
            if endpoint.startswith("http://"):
                kwargs["insecure"] = True
            return OTLPSpanExporter(**kwargs)
    except Exception as exc:
        LOGGER.warning("otel_exporter_init_failed", error=str(exc), protocol=protocol, endpoint=endpoint)
        return None
