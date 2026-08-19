"""AC12: session inactivity timeout renders session_expired.html for page requests and
returns JSON 401 for API requests (app/api/middleware/session_security.py).

The real trigger -- a user idling past their configured timeout -- is minutes-to-days of
wall-clock time, which no test should sit through. `check_session_timeout` decides purely
from two session values it trusts verbatim: `last_activity_at` and
`session_timeout_minutes`. So this signs a session cookie by hand, the same way Flask's
`SecureCookieSessionInterface` signs a real one (same secret key, same salt, same
serializer), with an already-stale `last_activity_at` baked in, and hands it to the
browser directly -- no real login, no waiting. That exercises the actual middleware branch
(session.clear() + the 401 response) rather than a mock standing in for it.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from urllib.parse import urlsplit

import pytest

pytestmark = pytest.mark.e2e

# Below MIN_SESSION_TIMEOUT_MINUTES (session_security.py) so the forged timeout survives
# the middleware's own clamp; comfortably older than that so the check is unambiguous.
_FORGED_TIMEOUT_MINUTES = 5
_STALE_MINUTES = 30


def _sign_session(payload: dict) -> str:
    from flask.sessions import SecureCookieSessionInterface

    from app.app import app as flask_app

    serializer = SecureCookieSessionInterface().get_signing_serializer(flask_app)
    return serializer.dumps(payload)


def _install_expired_session(context, app_url: str, user_id: str) -> None:
    stale_activity = (datetime.now(UTC) - timedelta(minutes=_STALE_MINUTES)).isoformat()
    payload = {
        "user_id": user_id,
        "last_activity_at": stale_activity,
        "session_timeout_minutes": _FORGED_TIMEOUT_MINUTES,
    }
    context.add_cookies(
        [
            {
                "name": "session",
                "value": _sign_session(payload),
                "domain": urlsplit(app_url).hostname,
                "path": "/",
                "secure": True,
                "httpOnly": True,
            }
        ]
    )


def test_ac12_inactivity_timeout_renders_session_expired_page_for_html_request(page, app_url, fresh_user):
    user = fresh_user()
    _install_expired_session(page.context, app_url, user["user_id"])

    response = page.request.get("/core/dashboard", headers={"Accept": "text/html"})

    assert response.status == 401, f"expected 401 for an expired session, got {response.status}"
    body = response.text()
    # Markers specific to session_expired.html's actual markup, not just the words
    # "session"/"expired" -- a generic 401 body (e.g. the JSON error message's text)
    # would satisfy a bare substring check without the real template having rendered
    # (test-evaluator.md finding #4).
    assert "<title>Session Expired</title>" in body, "session_expired.html was not rendered"
    assert 'id="countdown"' in body, "session_expired.html was not rendered"


def test_ac12_inactivity_timeout_returns_json_401_for_api_request(page, app_url, fresh_user):
    user = fresh_user()
    _install_expired_session(page.context, app_url, user["user_id"])

    response = page.request.get("/api/core/metrics", headers={"Accept": "application/json"})

    assert response.status == 401, f"expected 401 for an expired session, got {response.status}"
    assert response.json().get("error") == "Session expired due to inactivity"


def test_ac12_fresh_session_is_not_treated_as_expired(logged_in_page):
    """Control: a session with a recent last_activity_at must not trip the same check --
    proves the two tests above are actually exercising the timeout, not a route that
    always 401s."""
    response = logged_in_page.request.get("/core/dashboard")
    assert response.status == 200
