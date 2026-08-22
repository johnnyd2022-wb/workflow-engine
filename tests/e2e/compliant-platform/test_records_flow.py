"""AC: `GET/POST /api/compliant/records` (.agents/specs/compliant-platform.md, "Manual
compliance records"). POST requires an existing enabled profile (409 otherwise), validates
framework_slug/control_id against the static catalogue, and requires no ADMIN role (any
org member may attest). GET supports an optional `?framework=` filter; an unknown slug is
400, not an empty/all list.
"""

from __future__ import annotations

import uuid

import pytest

from tests.e2e.conftest import csrf_headers

pytestmark = pytest.mark.e2e

# customs-alcohol/product-mapping carries no CONTROL_REQUIREMENTS entry (see
# app/features/compliant/modules/nz_alcohol/catalogue.py) -- the simplest control for a
# happy-path record with no extra capture requirements to also satisfy.
FRAMEWORK_SLUG = "customs-alcohol"
CONTROL_ID = "product-mapping"


def test_create_record_requires_an_enabled_profile(admin_page):
    """AC: POST /records 409s when the org has no ComplianceProfile yet -- distinct from
    the 400s below, which are payload-shape errors."""
    response = admin_page.request.post(
        "/api/compliant/records",
        headers=csrf_headers(admin_page),
        data={
            "framework_slug": FRAMEWORK_SLUG,
            "control_id": CONTROL_ID,
            "record_type": "attestation",
            "title": "No profile yet",
        },
    )
    assert response.status == 409, f"expected 409 with no profile configured, got {response.status}"


def test_create_record_requires_profile_to_be_enabled_not_merely_present(admin_page, enable_profile):
    """A profile that exists but was disabled (PUT /profile {enabled: false}) must 409 the
    same as no profile at all -- a profile row existing is not the AC's "enabled" clause."""
    enable_profile(admin_page, enabled=False, settings={})
    response = admin_page.request.post(
        "/api/compliant/records",
        headers=csrf_headers(admin_page),
        data={
            "framework_slug": FRAMEWORK_SLUG,
            "control_id": CONTROL_ID,
            "record_type": "attestation",
            "title": "Profile exists but disabled",
        },
    )
    assert response.status == 409, f"expected 409 with a disabled profile, got {response.status} {response.text()}"


def test_create_record_happy_path_returns_full_record_shape(admin_page, enable_profile):
    """AC: POST /records returns the full serialised record on success.
    test_create_record_member_can_attest_without_admin_role below is what actually proves
    the "no ADMIN gate" claim -- admin_page here would stay green even if an ADMIN gate
    were mistakenly added, so this test only claims the response shape."""
    enable_profile(admin_page, enabled=True, settings={})
    title = f"Mapped House Gin {uuid.uuid4().hex[:8]}"
    response = admin_page.request.post(
        "/api/compliant/records",
        headers=csrf_headers(admin_page),
        data={
            "framework_slug": FRAMEWORK_SLUG,
            "control_id": CONTROL_ID,
            "record_type": "attestation",
            "title": title,
        },
    )
    assert response.status == 201, response.text()
    record = response.json()["record"]
    assert record["title"] == title
    assert record["framework_slug"] == FRAMEWORK_SLUG
    assert record["control_id"] == CONTROL_ID
    assert record["status"] == "complete"


def test_create_record_member_can_attest_without_admin_role(admin_and_member_pages, enable_profile):
    """Enrolment (`PUT /profile`) is ADMIN-gated, but attesting a record is not -- an
    ADMIN must enable Compliant first, then a plain MEMBER in that *same* org attests.
    A MEMBER trying to self-enable would 403 before this claim was even exercised, which
    is exactly why this needs the same-org two-role fixture rather than `member_page`
    alone.
    """
    admin_page = admin_and_member_pages["admin"]
    member_page = admin_and_member_pages["member"]
    enable_profile(admin_page, enabled=True, settings={})

    response = member_page.request.post(
        "/api/compliant/records",
        headers=csrf_headers(member_page),
        data={
            "framework_slug": FRAMEWORK_SLUG,
            "control_id": CONTROL_ID,
            "record_type": "attestation",
            "title": "Member-attested record",
        },
    )
    assert response.status == 201, f"a plain MEMBER should be able to attest: {response.status} {response.text()}"


def test_create_record_rejects_unknown_framework(admin_page, enable_profile):
    enable_profile(admin_page, enabled=True, settings={})
    response = admin_page.request.post(
        "/api/compliant/records",
        headers=csrf_headers(admin_page),
        data={
            "framework_slug": "not-a-real-framework",
            "control_id": CONTROL_ID,
            "record_type": "attestation",
            "title": "Unknown framework",
        },
    )
    assert response.status == 400
    assert "Unknown framework" in response.json()["error"]


def test_create_record_rejects_unknown_control_for_a_known_framework(admin_page, enable_profile):
    enable_profile(admin_page, enabled=True, settings={})
    response = admin_page.request.post(
        "/api/compliant/records",
        headers=csrf_headers(admin_page),
        data={
            "framework_slug": FRAMEWORK_SLUG,
            "control_id": "not-a-real-control",
            "record_type": "attestation",
            "title": "Unknown control",
        },
    )
    assert response.status == 400
    assert "Unknown control" in response.json()["error"]


def test_list_records_unknown_framework_filter_returns_400(admin_page):
    response = admin_page.request.get("/api/compliant/records?framework=not-a-real-framework")
    assert response.status == 400
    assert "Unknown framework" in response.json()["error"]


def test_list_records_filters_by_framework_and_orders_newest_first(admin_page, enable_profile):
    enable_profile(admin_page, enabled=True, settings={})
    first_title = f"First record {uuid.uuid4().hex[:8]}"
    second_title = f"Second record {uuid.uuid4().hex[:8]}"
    for title in (first_title, second_title):
        response = admin_page.request.post(
            "/api/compliant/records",
            headers=csrf_headers(admin_page),
            data={
                "framework_slug": FRAMEWORK_SLUG,
                "control_id": CONTROL_ID,
                "record_type": "attestation",
                "title": title,
            },
        )
        assert response.status == 201, response.text()

    response = admin_page.request.get(f"/api/compliant/records?framework={FRAMEWORK_SLUG}")
    assert response.status == 200, response.text()
    titles = [r["title"] for r in response.json()["records"]]
    assert titles.index(second_title) < titles.index(first_title), "expected newest-first ordering"

    # An unrelated framework filter must not include these records.
    other = admin_page.request.get("/api/compliant/records?framework=wine-standards")
    assert other.status == 200
    assert all(r["title"] not in (first_title, second_title) for r in other.json()["records"])


def test_list_records_requires_auth(page):
    """GET is CSRF-exempt (Flask-WTF only guards mutating methods), so this is a clean
    read of the auth boundary alone -- POST /records' auth boundary is already proven by
    tests/test_compliant_routes.py (a CSRF-disabled unit client); re-asserting it here
    with a real browser session would test CSRF-vs-auth precedence, not the AC."""
    response = page.request.get("/api/compliant/records", max_redirects=0)
    assert response.status == 401
