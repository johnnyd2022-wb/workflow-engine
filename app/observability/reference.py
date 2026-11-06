"""The reference a person quotes when they ask for help (GL-C04).

It is the first eight characters of the request's id, the ``request_id`` field on every log line
for that request (and the ``correlation_id`` on the events it wrote). Support finds the request
with a prefix match, e.g. in Loki ``{app="workflow-engine"} | json | request_id=~"3f9a2c1b.*"``.
Eight hex characters are short enough to read out over the phone and, with the time and page
that come with them, unambiguous.
"""

from __future__ import annotations

from flask import g, has_request_context

REFERENCE_LENGTH = 8


def reference_for(request_id: str | None) -> str:
    return (request_id or "").replace("-", "")[:REFERENCE_LENGTH].lower()


def request_reference() -> str:
    """This request's reference, or "" outside a request."""
    if not has_request_context():
        return ""
    return reference_for(getattr(g, "request_id", None) or str(getattr(g, "correlation_id", "") or ""))
