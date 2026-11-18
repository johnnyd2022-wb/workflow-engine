"""Per-grant request limits for the bearer path (spec "Bearer path" step 7, design review S4).

Flask-Limiter limits views; these limits apply to every request that arrives on a token, whatever
route it reaches, and are keyed on the grant id:

* 120 requests a minute for everything;
* on top of that, 30 a minute (``[mcp] calculation_requests_per_minute``) for operations the OpenAPI
  overlay marks ``x-bize.kind: calculation``: one of those can walk the whole cost graph.

They use the same ``limits`` machinery and the same store as the rest of the app (the app's
``RATELIMIT_STORAGE_URI``, see ``app/api/ratelimit_store.py``; in-process memory when unset). A store
error propagates as ``limits.errors.StorageError``: the caller refuses the request (fail closed).
"""

from __future__ import annotations

import threading
import time

from flask import current_app
from limits import parse
from limits.storage import storage_from_string
from limits.strategies import FixedWindowRateLimiter

from app.api.ratelimit_store import storage_options

BEARER_REQUESTS_PER_MINUTE = 120
CALCULATION_REQUESTS_PER_MINUTE = 30

_lock = threading.Lock()
_state: dict[str, object] = {}


def _strategy(app) -> FixedWindowRateLimiter:
    uri = app.config.get("RATELIMIT_STORAGE_URI") or "memory://"
    with _lock:
        if _state.get("uri") != uri:
            _state["uri"] = uri
            _state["strategy"] = FixedWindowRateLimiter(storage_from_string(uri, **storage_options(uri)))
        return _state["strategy"]  # type: ignore[return-value]


def calculation_requests_per_minute() -> int:
    from app.utils.config_loader import config

    try:
        value = int(config.get("mcp", "calculation_requests_per_minute", fallback=CALCULATION_REQUESTS_PER_MINUTE))
    except (TypeError, ValueError):
        value = CALCULATION_REQUESTS_PER_MINUTE
    return max(1, value)


def calculation_endpoints(app) -> frozenset[str]:
    """Endpoints with a GET operation the overlay marks ``calculation``. Built once per app from the
    same operation list the OpenAPI document is generated from, so the two can never disagree."""
    cached = app.extensions.get("mcp_calculation_endpoints")
    if cached is None:
        from app.api.openapi.generator import collect_operations
        from app.api.openapi.overlay import get_overlay

        overlay = get_overlay().operations
        cached = frozenset(
            op.endpoint
            for op in collect_operations(app)
            if op.method == "GET"
            and ((overlay.get(op.operation_id) or {}).get("x-bize") or {}).get("kind") == "calculation"
        )
        app.extensions["mcp_calculation_endpoints"] = cached
    return cached


def _retry_after(strategy: FixedWindowRateLimiter, item, key: str) -> int:
    reset_at, _remaining = strategy.get_window_stats(item, key)
    return max(1, int(reset_at - time.time()) + 1)


def hit_bearer(grant_id, *, calculation: bool = False) -> int | None:
    """Count one request for this grant. ``None`` when allowed, else seconds until it may retry.

    A calculation counts against both limits; the general one is counted first, so a refused
    calculation still uses one of the 120.
    """
    strategy = _strategy(current_app)
    item = parse(f"{int(BEARER_REQUESTS_PER_MINUTE)} per minute")
    key = f"mcp-grant:{grant_id}"
    if not strategy.hit(item, key):
        return _retry_after(strategy, item, key)
    if calculation:
        calc_item = parse(f"{calculation_requests_per_minute()} per minute")
        calc_key = f"mcp-grant-calculation:{grant_id}"
        if not strategy.hit(calc_item, calc_key):
            return _retry_after(strategy, calc_item, calc_key)
    return None
