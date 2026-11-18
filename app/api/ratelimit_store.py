"""Where rate-limit counts live (design review S4).

gunicorn runs ``WEB_CONCURRENCY`` workers (two in the test and production images). Counts kept in
process memory are per worker, so with two workers every limit is twice as loose. The test and
production configs therefore name a Valkey (``[ratelimit] host/port/db``, the container
``scripts/run_valkey.sh`` starts) and the password comes from ``VALKEY_PASSWORD``
(``Config.valkey_password``). The URI built here carries that password: it goes into the app config
and the limiter, and is never logged.

A store outage fails closed (ASSUMPTION, design review S4): no in-memory fallback and no swallowed
errors, so a limited route answers 503 "try again" instead of quietly going back to per-worker
buckets. Only limited routes touch the store (sign-in, the portal, telemetry, the MCP bearer path).
"""

from __future__ import annotations

import os
from urllib.parse import quote

from flask import jsonify
from limits.errors import StorageError

from app.observability import get_logger

logger = get_logger(__name__)

DEFAULT_PORT = 6379
# Short timeouts: a dead store must turn into a quick 503, never a hung worker thread.
_REDIS_OPTIONS = {"socket_connect_timeout": 1.0, "socket_timeout": 1.0}
RETRY_AFTER_SECONDS = 5


def web_workers() -> int:
    """How many processes serve this app. ``WEB_CONCURRENCY`` is what gunicorn.conf.py reads; the
    images set it (so ``docker exec ... workflow`` sees it too). Unset means one process: the
    Werkzeug dev server or a test run."""
    try:
        return max(1, int(os.getenv("WEB_CONCURRENCY", "1")))
    except ValueError:
        return 1


def storage_uri(cfg) -> str | None:
    """The shared store for this config, or ``None`` for in-process memory.

    An explicit ``[ratelimit] storage_uri`` wins (as before). Otherwise ``[ratelimit] host`` (with
    ``port``, default 6379, and ``db``, default 0) plus the Valkey password. A host with no password
    is no store: Valkey here always requires one, and connecting without it would fail every request.
    """
    explicit = (cfg.get("ratelimit", "storage_uri", fallback=None) or "").strip()
    if explicit:
        return explicit
    host = (cfg.get("ratelimit", "host", fallback=None) or "").strip()
    if not host:
        return None
    password = cfg.valkey_password
    if not password:
        return None
    port = int(cfg.get("ratelimit", "port", fallback=str(DEFAULT_PORT)) or DEFAULT_PORT)
    db = int(cfg.get("ratelimit", "db", fallback="0") or 0)
    return f"redis://:{quote(password, safe='')}@{host}:{port}/{db}"


def storage_options(uri: str | None) -> dict:
    """What the ``limits`` storage is built with: wrapped errors always, socket timeouts for Valkey."""
    options: dict = {"wrap_exceptions": True}
    if uri and uri.startswith(("redis://", "rediss://", "valkey://")):
        options.update(_REDIS_OPTIONS)
    return options


def shared_store_problem(cfg) -> str | None:
    """Why the limits are not real here, or ``None``. Used at start-up and before MCP is turned on."""
    workers = web_workers()
    if workers <= 1 or storage_uri(cfg):
        return None
    configured = bool((cfg.get("ratelimit", "host", fallback=None) or "").strip())
    cause = "VALKEY_PASSWORD is not set" if configured else "no [ratelimit] store is configured"
    return (
        f"This app runs {workers} workers but has no shared rate-limit store ({cause}), so every rate limit "
        "is per worker. Start Valkey (scripts/run_valkey.sh) and give the app VALKEY_PASSWORD first."
    )


def configure_ratelimit(app, limiter, cfg) -> None:
    """Point ``limiter`` at this config's store, fail closed on store errors, and init it on ``app``."""
    uri = storage_uri(cfg)
    if uri:
        app.config["RATELIMIT_STORAGE_URI"] = uri
    app.config["RATELIMIT_STORAGE_OPTIONS"] = storage_options(uri)
    app.config["RATELIMIT_SWALLOW_ERRORS"] = False
    app.config["RATELIMIT_IN_MEMORY_FALLBACK_ENABLED"] = False
    problem = shared_store_problem(cfg)
    if problem:
        logger.error("ratelimit.no_shared_store", workers=web_workers(), detail=problem)
    else:
        logger.info("ratelimit.store", shared=bool(uri), workers=web_workers())

    @app.errorhandler(StorageError)
    def _store_unavailable(error):
        # The wrapped error names the host and port, never the password; log its type only to be sure.
        logger.error("ratelimit.store_unavailable", error=type(getattr(error, "storage_error", error)).__name__)
        response = jsonify({"error": "This is briefly unavailable. Try again in a few seconds."})
        response.status_code = 503
        response.headers["Retry-After"] = str(RETRY_AFTER_SECONDS)
        return response

    limiter.init_app(app)
