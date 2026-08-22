"""AC: `PUT /api/compliant/profile` (auth + ADMIN, validates enabled/settings shape,
upserts) and `GET /api/compliant/capture-context` (auth only, reflects `profile.enabled`,
never 500s with no profile) -- .agents/specs/compliant-platform.md, "Profile / enrolment".
"""

from __future__ import annotations

import pytest

from tests.e2e.conftest import csrf_headers

pytestmark = pytest.mark.e2e


def test_capture_context_returns_false_and_200_before_any_profile_exists(admin_page):
    """The route must never 500 for a brand-new org with no ComplianceProfile row."""
    response = admin_page.request.get("/api/compliant/capture-context")
    assert response.status == 200, response.text()
    body = response.json()
    assert body["enabled"] is False
    assert body["label"]
    assert body["help"]


def test_capture_context_toggles_true_after_profile_enabled(admin_page, enable_profile):
    """AC: the shelf's on/off state is `profile.enabled`, live -- not cached at creation
    time and not merely "profile exists"."""
    enable_profile(admin_page, enabled=True, settings={})
    response = admin_page.request.get("/api/compliant/capture-context")
    assert response.status == 200, response.text()
    assert response.json()["enabled"] is True


def test_capture_context_toggles_back_to_false_after_profile_disabled(admin_page, enable_profile):
    enable_profile(admin_page, enabled=True, settings={})
    assert admin_page.request.get("/api/compliant/capture-context").json()["enabled"] is True

    enable_profile(admin_page, enabled=False)
    response = admin_page.request.get("/api/compliant/capture-context")
    assert response.status == 200, response.text()
    assert response.json()["enabled"] is False


def test_update_profile_requires_admin(member_page):
    response = member_page.request.put(
        "/api/compliant/profile", headers=csrf_headers(member_page), data={"enabled": True}
    )
    assert response.status == 403, f"expected a MEMBER to be rejected, got {response.status}"


def test_update_profile_rejects_non_object_body(admin_page):
    response = admin_page.request.put(
        "/api/compliant/profile",
        headers={**csrf_headers(admin_page), "Content-Type": "application/json"},
        data="[]",
    )
    assert response.status == 400
    assert "JSON object" in response.json()["error"]


def test_update_profile_rejects_non_boolean_enabled(admin_page):
    response = admin_page.request.put(
        "/api/compliant/profile", headers=csrf_headers(admin_page), data={"enabled": "yes"}
    )
    assert response.status == 400
    assert "enabled" in response.json()["error"]


def test_update_profile_rejects_non_object_settings(admin_page):
    response = admin_page.request.put(
        "/api/compliant/profile",
        headers=csrf_headers(admin_page),
        data={"enabled": True, "settings": "not-an-object"},
    )
    assert response.status == 400
    assert "settings" in response.json()["error"]


def test_update_profile_upserts_and_returns_refreshed_profile(admin_page, enable_profile):
    profile = enable_profile(
        admin_page,
        enabled=True,
        settings={"alcohol_product_types": ["spirits"]},
        council_name="Auckland Council",
    )
    assert profile["enabled"] is True
    assert profile["council_name"] == "Auckland Council"
    assert profile["settings"]["alcohol_product_types"] == ["spirits"]

    # A second PUT upserts the same row rather than erroring or creating a duplicate --
    # the overview must reflect the latest write, not the first.
    updated = enable_profile(admin_page, enabled=True, settings={"alcohol_product_types": ["beer", "spirits"]})
    assert updated["settings"]["alcohol_product_types"] == ["beer", "spirits"]

    overview = admin_page.request.get("/api/compliant/overview").json()
    assert overview["profile"]["settings"]["alcohol_product_types"] == ["beer", "spirits"]


def test_overview_requires_auth(page):
    """/api/* paths get the JSON 401, not the page-GET redirect (app_factory.py:322-336)."""
    response = page.request.get("/api/compliant/overview", max_redirects=0)
    assert response.status == 401
    assert response.json()["error"] == "Authentication required"


def test_overview_returns_null_profile_and_no_frameworks_for_a_fresh_org(admin_page):
    response = admin_page.request.get("/api/compliant/overview")
    assert response.status == 200, response.text()
    body = response.json()
    assert body["profile"] is None
    assert body["frameworks"] == []
    assert body["counts"] == {"compliant": 0, "attention": 0, "setup": 0}
