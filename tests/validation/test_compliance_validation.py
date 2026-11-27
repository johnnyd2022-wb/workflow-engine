import pytest

from tests.test_compliant_routes import _admin_client, flask_app  # noqa: F401


@pytest.fixture
def compliant_client(db, flask_app):  # noqa: F811
    return _admin_client(db, flask_app)[1]


@pytest.mark.parametrize(
    ("method", "path", "payload", "field"),
    [
        ("PUT", "/profile", {"settings": {"food_control_programme": []}}, "settings.food_control_programme"),
        ("PUT", "/profile", {"settings": {"np3_review_interval_months": True}}, "settings.np3_review_interval_months"),
        ("PUT", "/profile", {"settings": {"module_data": {"name": "Invalid\0text"}}}, "settings"),
        (
            "POST",
            "/np3-audit/attestations",
            {"control_id": "staff-competency", "confirmed": True, "how_we_meet": ["Training"]},
            "how_we_meet",
        ),
        (
            "POST",
            "/records",
            {
                "framework_slug": "customs-alcohol",
                "control_id": "period-lodgement",
                "title": "Excise entry",
                "record_type": [],
            },
            "record_type",
        ),
        ("POST", "/reports/customs-alcohol", [1], "_body"),
        ("PUT", "/nz-alcohol/excise/settings", {"frequency": []}, "frequency"),
        ("POST", "/nz-alcohol/excise/lodge", {"period_start": "2026-01-01", "entry_reference": 2}, "entry_reference"),
        (
            "POST",
            "/nz-alcohol/excise/rates",
            {"tariff_item": "99", "effective_from": "2026-01-01", "rate_per_lal": "100000000"},
            "rate_per_lal",
        ),
        ("PUT", "/nz-alcohol/excise/products", {"name": "Test gin", "abv_fallback": "NaN"}, "abv_fallback"),
        ("PUT", "/nz-alcohol/excise/products", {"name": "x" * 256}, "name"),
        (
            "POST",
            "/verification",
            {
                "verified_on": "2025-01-01",
                "verifier_name": "Verifier",
                "outcome": "acceptable",
                "actions": ["Follow up"],
            },
            "actions.0",
        ),
    ],
)
def test_compliance_invalid_request_is_rejected(compliant_client, method, path, payload, field):
    response = compliant_client.open(f"/api/compliant{path}", method=method, json=payload)
    assert response.status_code == 400
    assert field in response.json["errors"]


def test_core_source_offset_rejects_duplicate_values(compliant_client):
    response = compliant_client.get("/api/compliant/core-sources?kind=file&offset=0&offset=10")
    assert response.status_code == 400
    assert "offset" in response.json["errors"]
