"""A small per-caller sliding window (in memory is enough: the server is one stateless process)."""

from __future__ import annotations

from collections import deque


class Window:
    """At most ``limit`` hits per ``seconds`` for each key."""

    def __init__(self, limit: int, seconds: float):
        self.limit, self.seconds = limit, seconds
        self._hits: dict[str, deque[float]] = {}

    def hit(self, key: str, now: float) -> int | None:
        """None when allowed, else the seconds to wait."""
        hits = self._hits.setdefault(key, deque())
        while hits and hits[0] <= now - self.seconds:
            hits.popleft()
        if len(hits) >= self.limit:
            return max(1, int(hits[0] + self.seconds - now) + 1)
        hits.append(now)
        if len(self._hits) > 4096:
            self._hits = {k: v for k, v in self._hits.items() if v and v[-1] > now - self.seconds}
        return None
