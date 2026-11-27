import pytest

from app.core.db.models.organisation import Organisation
from tests.dag_traversal_helpers import clear_org_synthetic_data
from tests.test_compliant_routes import _admin_client, flask_app  # noqa: F401


@pytest.fixture
def compliant_client(db, flask_app):  # noqa: F811
    org, client = _admin_client(db, flask_app)
    try:
        yield client
    finally:
        db.rollback()
        clear_org_synthetic_data(db, org.id)
        db.query(Organisation).filter(Organisation.id == org.id).delete(synchronize_session=False)
        db.commit()


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


@pytest.mark.parametrize(
    ("path", "payload", "field"),
    [
        ("/licensing/licences", {"kind": []}, "kind"),
        ("/licensing/licences", {"kind": "on", "endorsements": [[]]}, "endorsements.0"),
        ("/licensing/managers", {"holder_name": 123}, "holder_name"),
        ("/licensing/log", {"kind": "incident", "description": "Note\0invalid"}, "description"),
        (
            "/nz-alcohol/cca-destinations",
            {"name": "Depot", "cca_code": "DL-1", "address": "Main St", "kind": []},
            "kind",
        ),
        (
            "/nz-alcohol/cca-licences",
            {
                "name": "Depot",
                "number": "DL-1",
                "kind": "oss",
                "legal_entity_reference": "Legal\0name",
                "valid_from": "2026-01-01",
                "evidence_reference": "Filed licence",
            },
            "legal_entity_reference",
        ),
        (
            "/food-registrations",
            {
                "programme": "np3",
                "reference": "REG-1",
                "name": "Producer",
                "registered_on": "2026-01-01",
                "registered_as": "new",
                "evidence_reference": "Registration\0notice",
            },
            "evidence_reference",
        ),
    ],
)
def test_registers_reject_invalid_input(compliant_client, path, payload, field):
    response = compliant_client.post(f"/api/compliant{path}", json=payload)
    assert response.status_code == 400
    assert field in response.json["errors"]


def test_cca_movement_rejects_duplicate_start_date(compliant_client):
    response = compliant_client.get(
        "/api/compliant/nz-alcohol/excise/cca-movements?start=2026-01-01&start=2026-01-02&end=2026-01-31"
    )
    assert response.status_code == 400
    assert "start" in response.json["errors"]


def test_wine_problem_requires_an_option(compliant_client):
    response = compliant_client.post("/api/compliant/wine/problems", json={"kind": [], "description": "Issue"})
    assert response.status_code == 400
    assert "kind" in response.json["errors"]


def test_excise_product_can_omit_an_optional_measurement(compliant_client):
    response = compliant_client.put(
        "/api/compliant/nz-alcohol/excise/products",
        json={"name": "Warehouse gin", "pack_volume_ml": "700", "abv_fallback": ""},
    )
    assert response.status_code == 200
