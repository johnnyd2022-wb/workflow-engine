"""Process-wide in-memory counters (thread-safe). For low-cardinality operational signals (not high-volume per-row)."""

from __future__ import annotations

import threading
from typing import Any

_lock = threading.Lock()
_counts: dict[str, int] = {}


def inc_counter(name: str, n: int = 1) -> None:
    if n <= 0:
        return
    with _lock:
        _counts[name] = _counts.get(name, 0) + n


def get_counter_snapshot() -> dict[str, int]:
    with _lock:
        return dict(_counts)


def reset_counters_for_tests() -> None:
    with _lock:
        _counts.clear()
