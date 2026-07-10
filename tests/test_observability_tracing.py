"""Observability tracing propagation tests."""

from __future__ import annotations

import importlib.util

import pytest

OTEL_AVAILABLE = all(
    importlib.util.find_spec(module_name) is not None
    for module_name in (
        "opentelemetry",
        "opentelemetry.instrumentation.flask",
        "opentelemetry.sdk.trace",
    )
)

pytestmark = pytest.mark.skipif(not OTEL_AVAILABLE, reason="OpenTelemetry dependencies are not installed")


def test_incoming_traceparent_continues_same_trace():
    """Incoming W3C traceparent should be continued by the Flask server span."""
    from flask import Flask
    from opentelemetry.instrumentation.flask import FlaskInstrumentor
    from opentelemetry.propagate import inject
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
    from opentelemetry.trace import SpanKind

    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))

    app = Flask(__name__)

    @app.route("/trace-check")
    def trace_check():
        return {"ok": True}

    FlaskInstrumentor().instrument_app(app, tracer_provider=provider)

    tracer = provider.get_tracer("tests.observability")
    headers: dict[str, str] = {}
    with tracer.start_as_current_span("upstream-parent") as parent_span:
        inject(headers)
        parent_trace_id = parent_span.get_span_context().trace_id
        parent_span_id = parent_span.get_span_context().span_id

    with app.test_client() as client:
        response = client.get("/trace-check", headers=headers)
        assert response.status_code == 200

    spans = exporter.get_finished_spans()
    server_spans = [span for span in spans if span.kind == SpanKind.SERVER]
    assert server_spans, "Expected at least one server span from Flask instrumentation"

    server_span = server_spans[-1]
    assert server_span.context.trace_id == parent_trace_id
    assert server_span.parent is not None
    assert server_span.parent.span_id == parent_span_id
