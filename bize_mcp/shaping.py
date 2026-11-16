"""Turning the app's answers into tool results: row caps, cursors, clipped text.

* at most ``MAX_ROWS`` (50) rows in any result; more means a ``next_cursor`` and a message saying so;
* a cursor is opaque, bound to the tool that issued it, and carries either the app's own keyset
  cursor (a string) or an offset into a list the app returns whole (an integer);
* text people typed (names, notes) is passed through as data, but clipped so one giant note can't
  flood an assistant's context;
* unknown stays unknown: nothing here turns ``null`` into ``0``.
"""

from __future__ import annotations

import base64
import binascii
import json
from typing import Any

MAX_ROWS = 50
MAX_TEXT = 2000
MAX_NESTED = 50
TRUNCATED = " …[truncated]"
_CURSOR_VERSION = 1
_MAX_CURSOR = 1024


def encode_cursor(tool: str, value: int | str) -> str:
    raw = json.dumps({"v": _CURSOR_VERSION, "t": tool, "c": value}, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def decode_cursor(tool: str, token: str) -> int | str:
    """The value inside a cursor this tool issued; ``ValueError`` for anything else."""
    if not isinstance(token, str) or not token or len(token) > _MAX_CURSOR:
        raise ValueError("bad cursor")
    try:
        body = json.loads(base64.urlsafe_b64decode(token + "=" * (-len(token) % 4)))
    except (binascii.Error, ValueError, UnicodeDecodeError):
        raise ValueError("bad cursor") from None
    if not isinstance(body, dict) or body.get("v") != _CURSOR_VERSION or body.get("t") != tool:
        raise ValueError("bad cursor")
    value = body.get("c")
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        raise ValueError("bad cursor")
    if isinstance(value, int) and value < 0:
        raise ValueError("bad cursor")
    return value


def clip_text(text: str, limit: int = MAX_TEXT) -> str:
    return text if len(text) <= limit else text[:limit] + TRUNCATED


def clip(value: Any, limit: int = MAX_TEXT) -> Any:
    """Clip every long string inside ``value`` (lists and dicts included)."""
    if isinstance(value, str):
        return clip_text(value, limit)
    if isinstance(value, list):
        return [clip(item, limit) for item in value]
    if isinstance(value, dict):
        return {key: clip(item, limit) for key, item in value.items()}
    return value


def cap_nested(items: list, *, label: str) -> tuple[list, str | None]:
    """First ``MAX_NESTED`` of a list inside one record, and a note when some were left out."""
    if len(items) <= MAX_NESTED:
        return items, None
    return items[:MAX_NESTED], f"{label}: showing {MAX_NESTED} of {len(items)}."


def pick(record: dict, fields: tuple[str, ...]) -> dict:
    """The named fields that exist in ``record``, in order (an absent field is left out, never zeroed)."""
    return {name: record[name] for name in fields if name in record}


def page_message(count: int, has_more: bool, noun: str = "rows") -> str:
    if has_more:
        return f"Showing {count} {noun}. More are available: call this tool again with next_cursor to continue."
    if count == 0:
        return f"No {noun} found."
    return f"{count} {noun}."


def list_result(
    tool: str,
    rows: list,
    *,
    next_value: int | str | None = None,
    extra: dict | None = None,
    noun: str = "rows",
) -> dict:
    """The standard shape of a list tool's result."""
    rows = clip(rows[:MAX_ROWS])
    has_more = next_value is not None
    body: dict[str, Any] = {
        "rows": rows,
        "row_count": len(rows),
        "has_more": has_more,
        "next_cursor": encode_cursor(tool, next_value) if has_more else None,
        "message": page_message(len(rows), has_more, noun),
    }
    if extra:
        body.update(clip(extra))
    return body


def slice_page(rows: list, offset: int) -> tuple[list, int | None]:
    """One page of a list the app returned whole: the rows, and the next offset when more remain."""
    page = rows[offset : offset + MAX_ROWS]
    end = offset + MAX_ROWS
    return page, (end if end < len(rows) else None)
