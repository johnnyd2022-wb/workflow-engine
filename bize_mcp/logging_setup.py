"""Logging that can't leak a token.

``install_redaction`` wraps the log-record factory, so every record in the process (this package,
the SDK, uvicorn, httpx) is scrubbed as it is created, including the text of a traceback. A token
shaped like ours (``bza_``/``bzr_``/``bzc_`` plus its body) or any ``Bearer`` value is replaced by
``[redacted]``. Tool arguments are never logged at all; this is the second line of defence.
"""

from __future__ import annotations

import logging
import re
import traceback

REDACTED = "[redacted]"
_OUR_TOKEN = re.compile(r"\bbz[acr]_[A-Za-z0-9_\-]+")
_BEARER = re.compile(r"(?i)\bbearer\s+(?!\[redacted\])[^\s\"',;}\]]+")


def redact(text: str) -> str:
    scrubbed = _OUR_TOKEN.sub(REDACTED, text)
    return _BEARER.sub(lambda m: f"{m.group(0).split()[0]} {REDACTED}", scrubbed)


def redact_value(value):
    """``value`` with every string (and key) in it redacted. Works on the object, never on its JSON text."""
    if isinstance(value, str):
        return redact(value)
    if isinstance(value, list):
        return [redact_value(item) for item in value]
    if isinstance(value, dict):
        return {redact(k) if isinstance(k, str) else k: redact_value(v) for k, v in value.items()}
    return value


def quiet_http_libraries() -> None:
    """The HTTP client logs every request URL at INFO, query values included; parameters are logged by name only."""
    for name in ("httpx2", "httpcore2", "httpcore2.http11", "httpcore2.connection"):
        logging.getLogger(name).setLevel(logging.WARNING)


def _redacted_arg(value):
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return redact(str(value))


def _redact_message(record: logging.LogRecord) -> None:
    """Redact the message, keeping ``record.args`` when that gives exactly the same text.

    Some formatters read the arguments themselves (uvicorn's access formatter unpacks them), so
    flattening every record to a finished string broke them. The arguments are kept only when the
    redacted template filled with redacted arguments equals the redacted finished message; anything
    else (a token split between template and argument, an object whose ``repr`` differs) falls back
    to the flattened, redacted string.
    """
    full = redact(record.getMessage())
    args = record.args
    if args:
        try:
            if isinstance(args, dict):
                kept = {key: _redacted_arg(value) for key, value in args.items()}
            else:
                kept = tuple(_redacted_arg(value) for value in args)
            template = redact(record.msg)
            if template % kept == full:
                record.msg, record.args = template, kept
                return
        except Exception:  # any mismatch means: flatten instead
            pass
    record.msg = full
    record.args = None


def install_redaction() -> None:
    quiet_http_libraries()
    previous = logging.getLogRecordFactory()
    if getattr(previous, "_bize_redacting", False):
        return

    def factory(*args, **kwargs):
        record = previous(*args, **kwargs)
        try:
            if isinstance(record.msg, str):  # a structured (dict) message belongs to its own formatter
                _redact_message(record)
            if record.exc_info and record.exc_info[0] is not None:
                record.exc_text = redact("".join(traceback.format_exception(*record.exc_info)).rstrip())
        except Exception:  # a logging problem must never break a request
            pass
        return record

    factory._bize_redacting = True  # type: ignore[attr-defined]
    logging.setLogRecordFactory(factory)


def configure_logging(level: int = logging.INFO) -> None:
    """Process-level setup for the real server (tests rely on caplog instead)."""
    install_redaction()
    logging.basicConfig(level=level, format="%(asctime)s %(levelname)s %(name)s %(message)s")
