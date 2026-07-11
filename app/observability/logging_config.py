"""Central logging configuration helpers."""

from __future__ import annotations

import logging
import sys
from typing import Any

try:
    import structlog
except Exception:  # pragma: no cover - fallback for pre-dependency bootstrap
    structlog = None

from app.observability.resource import build_resource, otlp_http_signal_endpoint
from app.observability.tracing import add_otel_context

_SENSITIVE_KEY_FRAGMENTS = (
    "password",
    "token",
    "secret",
    "authorization",
    "cookie",
    "email",
)
_REDACTED = "[REDACTED]"
_OTEL_LOG_HANDLER: logging.Handler | None = None


class _DropOpenTelemetryLogs(logging.Filter):
    """Prevent OTLP exporter diagnostics from recursively exporting themselves."""

    def filter(self, record: logging.LogRecord) -> bool:
        return not record.name.startswith("opentelemetry")


def _is_sensitive_key(key: Any) -> bool:
    if key is None:
        return False
    key_str = str(key).lower()
    return any(fragment in key_str for fragment in _SENSITIVE_KEY_FRAGMENTS)


def _redact_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: (_REDACTED if _is_sensitive_key(k) else _redact_value(v)) for k, v in value.items()}
    if isinstance(value, list):
        return [_redact_value(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_redact_value(item) for item in value)
    return value


def redact_sensitive_fields(_logger: Any, _method_name: str, event_dict: dict[str, Any]) -> dict[str, Any]:
    """Redact known sensitive keys before logs are rendered/exported."""
    for key in list(event_dict.keys()):
        if _is_sensitive_key(key):
            event_dict[key] = _REDACTED
            continue
        event_dict[key] = _redact_value(event_dict[key])
    return event_dict


def _resolve_level(level_name: str) -> int:
    return getattr(logging, level_name.upper(), logging.INFO)


def _resolve_renderer(log_format: str):
    if (log_format or "").strip().lower() == "console":
        return structlog.dev.ConsoleRenderer(colors=True)
    return structlog.processors.JSONRenderer()


def configure_logging(config: Any) -> None:
    """Configure structlog with stdlib integration for app + library logs."""
    level_name = str(getattr(config, "log_level", "INFO"))
    level = _resolve_level(level_name)

    if structlog is None:
        logging.basicConfig(
            level=level,
            format="%(asctime)s %(levelname)s %(name)s %(message)s",
            stream=sys.stdout,
        )
        return

    log_format = str(getattr(config, "log_format", "json"))
    renderer = _resolve_renderer(log_format)

    shared_processors = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        add_otel_context,
        redact_sensitive_fields,
    ]

    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=shared_processors,
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            structlog.processors.StackInfoRenderer(),
            structlog.processors.dict_tracebacks,
            renderer,
        ],
    )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    otel_handler = _configure_otel_log_handler(config, formatter, level)
    root_logger.handlers = [handler, otel_handler] if otel_handler is not None else [handler]
    root_logger.setLevel(level)

    # Reduce noise from default access/sql logs; access is emitted via our own hook.
    logging.getLogger("werkzeug").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)

    structlog.configure(
        processors=[
            *shared_processors,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str | None = None):
    """Return a structlog logger handle."""
    if structlog is None:
        return logging.getLogger(name)
    return structlog.stdlib.get_logger(name)


def _configure_otel_log_handler(config: Any, formatter: logging.Formatter, level: int) -> logging.Handler | None:
    """Create one OTLP log handler when collector export is enabled."""
    global _OTEL_LOG_HANDLER

    if _OTEL_LOG_HANDLER is not None:
        return _OTEL_LOG_HANDLER
    if not bool(getattr(config, "otel_enabled", False)):
        return None
    if not bool(getattr(config, "grafana_data_enabled", False)):
        return None
    if str(getattr(config, "environment", "")).strip().lower() == "test":
        return None

    endpoint = str(getattr(config, "otel_exporter_endpoint", "")).strip()
    if not endpoint:
        return None

    try:
        from opentelemetry._logs import set_logger_provider
        from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
        from opentelemetry.sdk._logs.export import BatchLogRecordProcessor

        protocol = str(getattr(config, "otel_exporter_protocol", "grpc")).strip().lower()
        if protocol == "http/protobuf":
            from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter

            exporter = OTLPLogExporter(endpoint=otlp_http_signal_endpoint(endpoint, "logs"))
        else:
            from opentelemetry.exporter.otlp.proto.grpc._log_exporter import OTLPLogExporter

            kwargs: dict[str, Any] = {"endpoint": endpoint}
            if endpoint.startswith("http://"):
                kwargs["insecure"] = True
            exporter = OTLPLogExporter(**kwargs)

        provider = LoggerProvider(resource=build_resource(config))
        provider.add_log_record_processor(BatchLogRecordProcessor(exporter))
        set_logger_provider(provider)

        handler = LoggingHandler(level=level, logger_provider=provider)
        handler.setFormatter(formatter)
        handler.addFilter(_DropOpenTelemetryLogs())
        _OTEL_LOG_HANDLER = handler
        return handler
    except Exception as exc:
        logging.getLogger(__name__).warning("otel_log_exporter_init_failed", extra={"error": str(exc)})
        return None
