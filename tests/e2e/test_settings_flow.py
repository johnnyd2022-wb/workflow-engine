"""Stage 1/2: settings — change a value and prove it persists.

Render-only coverage proves the settings page loads; this proves a change round-trips.
The /auth/* settings routes are CSRF-exempt (app_factory), so these mutate without a token
— matching how the real client calls them.
"""

import uuid

import pytest

pytestmark = pytest.mark.e2e


def test_update_profile_settings_persists(logged_in_page):
    page = logged_in_page
    new_first = f"E2E{uuid.uuid4().hex[:6]}"

    resp = page.request.put(
        "/auth/settings",
        data={"first_name": new_first, "last_name": "Tester"},
    )
    assert resp.status == 200, f"settings update failed: {resp.status} {resp.text()}"

    after = page.request.get("/auth/settings")
    assert after.status == 200
    assert new_first in after.text(), "profile change did not persist"


def test_update_session_timeout_persists(logged_in_page):
    page = logged_in_page
    current = page.request.get("/auth/session-timeout").json()
    lo = current.get("min_session_timeout_minutes", 5)
    hi = current.get("max_session_timeout_minutes", 43200)
    target = min(max(lo, 120), hi)  # a valid in-bounds value

    resp = page.request.put("/auth/session-timeout", data={"session_timeout_minutes": target})
    assert resp.status == 200, f"timeout update failed: {resp.status} {resp.text()}"

    after = page.request.get("/auth/session-timeout")
    assert after.json().get("session_timeout_minutes") == target, "timeout did not persist"


def test_session_timeout_rejects_out_of_bounds(logged_in_page):
    """Unhappy path: a value above max is rejected, nothing changes."""
    page = logged_in_page
    resp = page.request.put("/auth/session-timeout", data={"session_timeout_minutes": 10**9})
    assert resp.status == 400, f"expected 400 for out-of-bounds timeout, got {resp.status}"
