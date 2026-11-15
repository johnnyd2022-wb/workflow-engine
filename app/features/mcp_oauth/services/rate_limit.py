"""Per-grant request limit for the bearer path (120 per minute, spec "Bearer path" step 7).

Flask-Limiter limits views; this limit applies to every request that arrives on a token, whatever
route it reaches, and is keyed on the grant id. It uses the same ``limits`` machinery and the same
storage URI as the rest of the app (``[ratelimit] storage_uri``; in-process memory when unset).
"""

from __future__ import annotations

import threading

from flask import current_app
from limits import parse
from limits.storage import storage_from_string
from limits.strategies import FixedWindowRateLimiter

BEARER_REQUESTS_PER_MINUTE = 120

_lock = threading.Lock()
_state: dict[str, object] = {}


def _strategy(app) -> FixedWindowRateLimiter:
    uri = app.config.get("RATELIMIT_STORAGE_URI") or "memory://"
    with _lock:
        if _state.get("uri") != uri:
            _state["uri"] = uri
            _state["strategy"] = FixedWindowRateLimiter(storage_from_string(uri))
        return _state["strategy"]  # type: ignore[return-value]


def hit_bearer(grant_id) -> int | None:
    """Count one request for this grant. ``None`` when allowed, else seconds until it may retry."""
    item = parse(f"{int(BEARER_REQUESTS_PER_MINUTE)} per minute")
    strategy = _strategy(current_app)
    key = f"mcp-grant:{grant_id}"
    if strategy.hit(item, key):
        return None
    reset_at, _remaining = strategy.get_window_stats(item, key)
    import time

    return max(1, int(reset_at - time.time()) + 1)
