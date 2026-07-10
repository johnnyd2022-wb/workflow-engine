"""Observability package entrypoints.

This module provides stable import paths while implementation is rolled out
incrementally by phase.
"""

from app.observability.logging_config import configure_logging, get_logger
from app.observability.metrics import configure_metrics
from app.observability.middleware import setup_observability
from app.observability.resource import build_resource
from app.observability.tracing import add_otel_context, configure_tracing, start_span, traced

__all__ = [
    "add_otel_context",
    "build_resource",
    "configure_logging",
    "configure_metrics",
    "configure_tracing",
    "get_logger",
    "setup_observability",
    "start_span",
    "traced",
]
