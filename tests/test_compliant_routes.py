"""HTTP contracts for the tenant-scoped Compliant product area."""

from uuid import uuid4

import pytest

from app.core.db.models.organisation import Organisation
from app.core.db.models.user import UserRole
from app.core.db.repositories.user_repo import UserRepository
from app.core.security.auth_service import AuthService
from tests.factories import DEFAULT_TEST_PASSWORD, OrganisationFactory


def _admin_client(db, flask_app):
    org = OrganisationFactory()
    email = f"compliant-{uuid4()}@test.com"
    UserRepository(db).create_user(
        org_id=org.id,
        email=email,
        password_hash=AuthService.hash_password(DEFAULT_TEST_PASSWORD),
        role=UserRole.ADMIN,
        is_active=True,
    )
    db.commit()
    client = flask_app.test_client()
    client.environ_base["wsgi.url_scheme"] = "https"
    client.environ_base["HTTP_X_FORWARDED_PROTO"] = "https"
    response = client.post("/auth/login", json={"email": email, "password": DEFAULT_TEST_PASSWORD})
    assert response.status_code == 200
    return org, client


@pytest.fixture
def flask_app():
    from app.api.app_factory import create_app

    app = create_app()
    app.config.update(TESTING=True, WTF_CSRF_ENABLED=False)
    with app.app_context():
        yield app


def test_compliant_profile_records_and_audit_pack_are_org_scoped(db, flask_app):
    org_a, client_a = _admin_client(db, flask_app)
    org_b, client_b = _admin_client(db, flask_app)
    try:
        assert client_a.get("/api/compliant/overview").get_json()["frameworks"] == []
        profile = client_a.put(
            "/api/compliant/profile",
            json={
                "enabled": True,
                "settings": {"alcohol_product_types": ["spirits"], "trade_waste_council": "auckland-watercare"},
            },
        )
        assert profile.status_code == 200
        assert (
            client_a.post(
                "/api/compliant/alcohol-products",
                json={"inventory_name": "House Gin", "product_type": "spirits", "abv_percent": "40"},
            ).status_code
            == 201
        )
        record = client_a.post(
            "/api/compliant/records",
            json={
                "framework_slug": "customs-alcohol",
                "control_id": "period-lodgement",
                "record_type": "lodgement",
                "title": "July excise entry",
                "period_start": "2026-07-01",
                "period_end": "2026-07-31",
                "evidence_reference": "NZCS filing 123",
            },
        )
        assert record.status_code == 201
        report = client_a.post("/api/compliant/reports/customs-alcohol", json={})
        assert report.status_code == 201
        report_id = report.get_json()["report"]["report_id"]
        assert client_a.get(f"/api/compliant/reports/{report_id}?format=csv").status_code == 200
        audit_html = client_a.get(f"/api/compliant/reports/{report_id}?format=html")
        assert audit_html.status_code == 200
        assert b"Source and scope" in audit_html.data
        assert client_b.get(f"/api/compliant/reports/{report_id}").status_code == 404
    finally:
        db.query(Organisation).filter(Organisation.id.in_([org_a.id, org_b.id])).delete(synchronize_session=False)
        db.commit()


def test_compliant_routes_require_auth(flask_app):
    client = flask_app.test_client()
    client.environ_base["wsgi.url_scheme"] = "https"
    client.environ_base["HTTP_X_FORWARDED_PROTO"] = "https"
    assert client.get("/api/compliant/overview").status_code == 401
    assert client.post("/api/compliant/records", json={}).status_code == 401


def test_control_capture_requirements_are_enforced(db, flask_app):
    org, client = _admin_client(db, flask_app)
    try:
        assert client.put("/api/compliant/profile", json={"enabled": True, "settings": {}}).status_code == 200
        invalid = client.post(
            "/api/compliant/records",
            json={
                "framework_slug": "customs-alcohol",
                "control_id": "period-lodgement",
                "record_type": "lodgement",
                "title": "Missing the period and evidence",
            },
        )
        assert invalid.status_code == 400
        assert "period start" in invalid.get_json()["error"]
        invalid_link = client.post(
            "/api/compliant/records",
            json={
                "framework_slug": "customs-alcohol",
                "control_id": "movement-evidence",
                "record_type": "attestation",
                "title": "Unverified core link",
                "evidence_reference": "dispatch-note-7",
                "source_refs": [str(uuid4())],
            },
        )
        assert invalid_link.status_code == 400
        assert "this organisation" in invalid_link.get_json()["error"]
    finally:
        db.query(Organisation).filter(Organisation.id == org.id).delete(synchronize_session=False)
        db.commit()
