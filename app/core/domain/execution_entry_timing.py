"""Server-owned occurrence and entry timestamps for production steps."""

from datetime import UTC, datetime, timedelta


def entry_timing(completed_at: datetime | None, execution_data: dict | None) -> dict:
    """Return JSON-ready entry time and the >24h late-entry badge state."""
    raw = (execution_data or {}).get("entered_at")
    try:
        entered_at = datetime.fromisoformat(raw) if isinstance(raw, str) else None
    except ValueError:
        entered_at = None
    if entered_at is not None and entered_at.tzinfo is None:
        entered_at = entered_at.replace(tzinfo=UTC)
    occurred_at = completed_at
    if occurred_at is not None and occurred_at.tzinfo is None:
        occurred_at = occurred_at.replace(tzinfo=UTC)
    return {
        "entered_at": entered_at.isoformat() if entered_at is not None else None,
        "entered_later": bool(entered_at and occurred_at and entered_at - occurred_at > timedelta(days=1)),
    }
