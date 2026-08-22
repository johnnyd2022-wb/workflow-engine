"""AC: `POST /api/compliant/reports/<framework_slug>` and `GET
/api/compliant/reports/<report_id>` (.agents/specs/compliant-platform.md, "Audit packs").

POST builds an immutable, checksummed snapshot and 400s on an unknown/inapplicable
framework or a missing profile. GET 400s on a malformed UUID, defaults to a JSON body with
id/checksum/payload, and supports `?format=html` (printable page) and `?format=csv`
(streamed export with a Content-Disposition: attachment header).
"""

from __future__ import annotations

import pytest

from tests.e2e.conftest import csrf_headers

pytestmark = pytest.mark.e2e

FRAMEWORK_SLUG = "customs-alcohol"


def test_create_report_requires_an_enabled_profile(admin_page):
    response = admin_page.request.post(
        f"/api/compliant/reports/{FRAMEWORK_SLUG}", headers=csrf_headers(admin_page), data={}
    )
    assert response.status == 400
    assert "error" in response.json()


def test_create_report_requires_profile_to_be_enabled_not_merely_present(admin_page, enable_profile):
    """A profile that exists but was disabled must 400 the same as no profile at all --
    otherwise this AC would be indistinguishable from "profile row happens to be missing"."""
    enable_profile(admin_page, enabled=False, settings={})
    response = admin_page.request.post(
        f"/api/compliant/reports/{FRAMEWORK_SLUG}", headers=csrf_headers(admin_page), data={}
    )
    assert response.status == 400, f"expected 400 with a disabled profile, got {response.status} {response.text()}"


def test_create_report_rejects_unknown_framework(admin_page, enable_profile):
    enable_profile(admin_page, enabled=True, settings={})
    response = admin_page.request.post(
        "/api/compliant/reports/not-a-real-framework", headers=csrf_headers(admin_page), data={}
    )
    assert response.status == 400
    assert "Unknown framework" in response.json()["error"]


def test_create_report_happy_path_returns_checksum_and_view_url(admin_page, enable_profile, create_report):
    enable_profile(admin_page, enabled=True, settings={"alcohol_product_types": ["spirits"]})
    body = create_report(admin_page, FRAMEWORK_SLUG)

    report = body["report"]
    assert report["report_id"]
    assert len(report["checksum_sha256"]) == 64, "expected a hex SHA-256 digest"
    assert report["payload"]["framework"]["slug"] == FRAMEWORK_SLUG
    assert body["view_url"] == f"/api/compliant/reports/{report['report_id']}?format=html"


def test_get_report_malformed_uuid_returns_400(admin_page):
    response = admin_page.request.get("/api/compliant/reports/not-a-uuid")
    assert response.status == 400
    assert "Invalid report id" in response.json()["error"]


def test_get_report_default_json_shape(admin_page, enable_profile, create_report):
    enable_profile(admin_page, enabled=True, settings={})
    report_id = create_report(admin_page, FRAMEWORK_SLUG)["report"]["report_id"]

    response = admin_page.request.get(f"/api/compliant/reports/{report_id}")
    assert response.status == 200, response.text()
    body = response.json()
    assert body["id"] == report_id
    assert len(body["checksum_sha256"]) == 64
    assert body["payload"]["framework"]["slug"] == FRAMEWORK_SLUG


def test_get_report_html_format_renders_audit_pack_page(admin_page, enable_profile, create_report):
    enable_profile(admin_page, enabled=True, settings={})
    report_id = create_report(admin_page, FRAMEWORK_SLUG)["report"]["report_id"]

    response = admin_page.request.get(f"/api/compliant/reports/{report_id}?format=html")
    assert response.status == 200, response.text()
    assert "text/html" in response.headers.get("content-type", "")
    assert "Source and scope" in response.text()


def test_get_report_csv_format_streams_attachment(admin_page, enable_profile, create_record, create_report):
    enable_profile(admin_page, enabled=True, settings={})
    create_record(admin_page, framework_slug=FRAMEWORK_SLUG, control_id="product-mapping", title="CSV export row")
    report_id = create_report(admin_page, FRAMEWORK_SLUG)["report"]["report_id"]

    response = admin_page.request.get(f"/api/compliant/reports/{report_id}?format=csv")
    assert response.status == 200, response.text()
    assert "text/csv" in response.headers.get("content-type", "")
    content_disposition = response.headers.get("content-disposition", "")
    assert "attachment" in content_disposition
    assert f"{FRAMEWORK_SLUG}-audit-pack.csv" in content_disposition

    csv_text = response.text()
    assert "framework" in csv_text.splitlines()[0]  # header row
    assert "CSV export row" in csv_text


def test_get_report_requires_auth(page, admin_page, enable_profile, create_report):
    enable_profile(admin_page, enabled=True, settings={})
    report_id = create_report(admin_page, FRAMEWORK_SLUG)["report"]["report_id"]

    response = page.request.get(f"/api/compliant/reports/{report_id}", max_redirects=0)
    assert response.status == 401
