"""Shared UTC time helper.

`datetime.utcnow()` returns a naive datetime, which Postgres writes into
`TIMESTAMPTZ` columns using the session's local timezone rather than UTC.
`utc_now()` returns a timezone-aware UTC datetime so the stored instant is
always correct, and is used as the bare callable for Column `default=`/
`onupdate=` (a lambda would work but would be repeated across every model).
"""

from datetime import UTC, datetime


def utc_now() -> datetime:
    return datetime.now(UTC)
