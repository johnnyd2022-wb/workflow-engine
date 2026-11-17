"""Per-caller sliding windows: in this process, or in the shared Valkey (design review S4).

One process is enough to count in memory. Any second process (a restart overlap, a second replica)
would start a fresh budget, so with ``BIZE_RATELIMIT_URI`` set the windows are counted in Valkey
instead, with the server's own clock (``TIME``), so every process sees one window.

A store that cannot be reached refuses the call (``kind: unavailable``) rather than counting nothing.
The client is synchronous with one-second timeouts; the server calls ``ahit``, which runs a shared hit
on a worker thread so a slow or dead store never blocks the event loop for every other caller.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections import deque

from bize_mcp.errors import ToolFailureError

logger = logging.getLogger("bize_mcp.ratelimit")

UNAVAILABLE_RETRY_SECONDS = 5

# KEYS[1] the window's key; ARGV: limit, seconds, a unique member. 0 = allowed, else seconds to wait.
_SLIDING_WINDOW = """
local t = redis.call('TIME')
local now = tonumber(t[1]) + tonumber(t[2]) / 1000000
local limit = tonumber(ARGV[1])
local seconds = tonumber(ARGV[2])
redis.call('ZREMRANGEBYSCORE', KEYS[1], '-inf', now - seconds)
if redis.call('ZCARD', KEYS[1]) >= limit then
  local oldest = redis.call('ZRANGE', KEYS[1], 0, 0, 'WITHSCORES')
  local wait = math.floor(tonumber(oldest[2]) + seconds - now) + 1
  if wait < 1 then wait = 1 end
  return wait
end
redis.call('ZADD', KEYS[1], now, ARGV[3])
redis.call('PEXPIRE', KEYS[1], math.ceil(seconds * 1000))
return 0
"""


class SharedStore:
    """The Valkey the windows are counted in."""

    def __init__(self, uri: str, password: str):
        import redis

        self._redis = redis
        self._client = redis.Redis.from_url(uri, password=password, socket_connect_timeout=1, socket_timeout=1)
        self._script = self._client.register_script(_SLIDING_WINDOW)

    @classmethod
    def from_config(cls, config) -> SharedStore | None:
        if not config.ratelimit_uri:
            return None
        return cls(config.ratelimit_uri, config.ratelimit_password)

    def hit(self, key: str, limit: int, seconds: float) -> int | None:
        try:
            wait = int(self._script(keys=[key], args=[limit, seconds, uuid.uuid4().hex]))
        except self._redis.RedisError as error:
            logger.warning("ratelimit_store_unavailable error=%s", type(error).__name__)
            raise ToolFailureError(
                "Biz-E is briefly unavailable. Try again in a few seconds.",
                kind="unavailable",
                retry_after_seconds=UNAVAILABLE_RETRY_SECONDS,
            ) from None
        return wait or None


class Window:
    """At most ``limit`` hits per ``seconds`` for each key."""

    def __init__(self, limit: int, seconds: float, *, store: SharedStore | None = None, name: str = "window"):
        self.limit, self.seconds = limit, seconds
        self.store, self.name = store, name
        self._hits: dict[str, deque[float]] = {}

    def hit(self, key: str, now: float) -> int | None:
        """None when allowed, else the seconds to wait. ``now`` is this process's clock (ignored when
        the window is shared: Valkey's clock is the one every process agrees on)."""
        if self.store is not None:
            return self.store.hit(f"bize_mcp:{self.name}:{key}", self.limit, self.seconds)
        hits = self._hits.setdefault(key, deque())
        while hits and hits[0] <= now - self.seconds:
            hits.popleft()
        if len(hits) >= self.limit:
            return max(1, int(hits[0] + self.seconds - now) + 1)
        hits.append(now)
        if len(self._hits) > 4096:
            self._hits = {k: v for k, v in self._hits.items() if v and v[-1] > now - self.seconds}
        return None

    async def ahit(self, key: str, now: float) -> int | None:
        """``hit`` for async callers: a shared window's round trip runs off the event loop."""
        if self.store is None:
            return self.hit(key, now)
        return await asyncio.to_thread(self.hit, key, now)
