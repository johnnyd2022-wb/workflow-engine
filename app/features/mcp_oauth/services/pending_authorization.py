"""The authorization request that is waiting for its user to sign in (public MCP 8.2h, F7).

A signed-out visitor who arrives at ``/oauth/authorize`` is sent to the normal sign-in. The request
waits in the **server-side session**, not in a ``next=`` address, so there is no return URL for anyone
to tamper with. After any sign-in (password, 2FA, Google, first-time 2FA enrolment) the app asks for
``return_url()``, which is always ``/oauth/authorize?`` plus the stored OAuth parameters, URL-encoded.
The endpoint then validates the request from scratch, so nothing stored here is trusted.
"""

from __future__ import annotations

import time
from urllib.parse import urlencode

from flask import session

SESSION_KEY = "mcp_pending_authorization"
AUTHORIZE_PATH = "/oauth/authorize"
MAX_AGE_SECONDS = 15 * 60
# The session is a signed cookie (about 4 KB). A real request is a few hundred characters.
MAX_TOTAL_LENGTH = 2048
MAX_PAIRS = 12
PARAM_NAMES = frozenset(
    {
        "response_type",
        "client_id",
        "redirect_uri",
        "state",
        "code_challenge",
        "code_challenge_method",
        "scope",
        "resource",
    }
)


def build_url(pairs) -> str:
    """The authorize URL for these pairs. The path is fixed; values are only ever query data."""
    return f"{AUTHORIZE_PATH}?{urlencode(list(pairs))}"


def _clean(stored, now: float | None = None):
    """The stored pairs when the entry is well formed and fresh, else ``None``."""
    if not isinstance(stored, dict):
        return None
    at, pairs = stored.get("at"), stored.get("params")
    if isinstance(at, bool) or not isinstance(at, int | float):
        return None
    if (now or time.time()) - at > MAX_AGE_SECONDS or not isinstance(pairs, list) or not 0 < len(pairs) <= MAX_PAIRS:
        return None
    clean, total = [], 0
    for pair in pairs:
        if not isinstance(pair, list | tuple) or len(pair) != 2:
            return None
        name, value = pair
        if name not in PARAM_NAMES or not isinstance(value, str):
            return None
        total += len(name) + len(value)
        clean.append((name, value))
    return clean if total <= MAX_TOTAL_LENGTH else None


def remember(args) -> bool:
    """Keep this authorization request for after sign-in. ``args`` is the query MultiDict."""
    pairs = [(name, value) for name, value in args.items(multi=True) if name in PARAM_NAMES]
    if not pairs or len(pairs) > MAX_PAIRS or _clean({"at": time.time(), "params": pairs}) is None:
        session.pop(SESSION_KEY, None)
        return False
    session[SESSION_KEY] = {"at": time.time(), "params": [list(p) for p in pairs]}
    return True


def peek_url() -> str | None:
    """The address to return to, leaving the request in place (used until sign-in is complete)."""
    pairs = _clean(session.get(SESSION_KEY))
    if pairs is None:
        session.pop(SESSION_KEY, None)
        return None
    return build_url(pairs)


def take_url() -> str | None:
    """The address to return to, and forget the request."""
    url = peek_url()
    session.pop(SESSION_KEY, None)
    return url


def clear() -> None:
    session.pop(SESSION_KEY, None)


def carry_over() -> dict:
    """What survives a session rotation at sign-in: only a well-formed pending request."""
    stored = session.get(SESSION_KEY)
    return {SESSION_KEY: stored} if _clean(stored) is not None else {}
