"""The two ways a tool call can fail, as the spec's error table has them.

``ToolFailure``  becomes a tool result with ``isError`` set and a plain message the assistant can
                 read to the person (and a small structured ``error`` object).
``Unauthorized`` becomes an HTTP 401 so the assistant signs in again.
"""

from __future__ import annotations

PROBLEM = "Biz-E had a problem. Try again shortly."
NOT_AVAILABLE = "Not available for your organisation."
NOT_ALLOWED = (
    "Your organisation hasn't turned on AI assistant access, or your role can't use it. "
    "An admin can change this in Settings."
)
READ_ONLY = "This connection is read only, so it can't do that."
NO_PERMISSION = "You don't have permission to see that in Biz-E."


class ToolFailure(Exception):
    def __init__(self, message: str, kind: str = "error", retry_after_seconds: int | None = None):
        super().__init__(message)
        self.message = message
        self.kind = kind
        self.retry_after_seconds = retry_after_seconds

    def as_data(self) -> dict:
        data = {"kind": self.kind, "message": self.message}
        if self.kind == "rate_limited":
            data["retry_after_seconds"] = self.retry_after_seconds
        return {"error": data}


class Unauthorized(Exception):
    """The app says the token is no good (expired, revoked, or never ours)."""
