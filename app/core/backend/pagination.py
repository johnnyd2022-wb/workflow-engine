"""Keyset cursor and limits shared by Core list endpoints."""

import base64
from datetime import datetime
from uuid import UUID

# Opt-in keyset pagination for the big list endpoints (executions, inventory). A caller
# that passes no ?limit gets the full list exactly as before -- every existing consumer
# (process pickers, sourcemap, reconciliation, the dispose flow) is unchanged. Only the
# /core hub tabs pass a limit. Cursor is an opaque base64url("<created_at_iso>|<id>") of
# the last row returned; the sort is (created_at DESC, id DESC).
LIST_PAGE_MAX = 50


def encode_list_cursor(created_at: datetime, row_id) -> str:
    raw = f"{created_at.isoformat()}|{row_id}".encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _decode_list_cursor(token: str) -> tuple[datetime, UUID]:
    """Parse a cursor token. Raises ValueError on anything malformed -- the caller turns
    that into a 400 rather than a 500."""
    pad = "=" * (-len(token) % 4)
    raw = base64.urlsafe_b64decode(token + pad).decode()
    ts_str, id_str = raw.split("|", 1)
    return datetime.fromisoformat(ts_str), UUID(id_str)


def parse_page_params(args) -> tuple[int | None, tuple[datetime, UUID] | None]:
    """(limit, cursor) from request args. limit is None when the caller wants the full
    list; otherwise it is clamped to [1, LIST_PAGE_MAX]. Raises ValueError for a bad
    limit or cursor."""
    limit_str = args.get("limit")
    if limit_str is None or limit_str == "":
        return None, None
    limit = int(limit_str)  # ValueError -> 400
    if limit < 1:
        raise ValueError("limit must be >= 1")
    limit = min(limit, LIST_PAGE_MAX)
    cursor_str = args.get("cursor")
    cursor = _decode_list_cursor(cursor_str) if cursor_str else None
    return limit, cursor
