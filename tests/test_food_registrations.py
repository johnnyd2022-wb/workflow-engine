"""Explicit registration scope and independent visit/action histories."""

from concurrent.futures import ThreadPoolExecutor
from datetime import date
from html.parser import HTMLParser
from uuid import uuid4

import pytest
from sqlalchemy.exc import IntegrityError

from app.core.db.models.audit_log import AuditLog
from app.core.db.models.organisation import Organisation
from app.core.security.tenant_scope import unscoped
from app.features.compliant.models.food_registration import FoodRegistration, FoodRegistrationSite
from app.features.compliant.models.verification import ComplianceVerification, ComplianceVerificationAction
from app.features.compliant.modules.nz_alcohol import food_registrations as register
from app.features.compliant.modules.nz_alcohol import verification
from app.features.compliant.modules.nz_alcohol.module import run_verification_check
from tests.test_compliant_routes import _admin_client, flask_app  # noqa: F401
from tests.test_customs_premises import world  # noqa: F401

TODAY = date(2026, 9, 29)


def registration_data(**changes):
    return {
        "reference": "NP-123",
        "name": "Main registration",
        "programme": "np3",
        "registered_on": "2026-01-01",
        "registered_as": "new",
        "valid_until": None,
        "evidence_reference": "Registration PDF",
        **changes,
    }


def visit_data(**changes):
    return {
        "verified_on": "2026-09-01",
        "verifier_name": "Verifier",
        "outcome": "acceptable",
        "initial": True,
        **changes,
    }


def test_registration_scope_is_explicit_and_dated(db, world):  # noqa: F811
    orgs, sites, extra, _ = world
    row = register.add_registration(db, orgs[0].id, registration_data(valid_until="2026-12-31"), TODAY)
    register.add_scope(
        db,
        orgs[0].id,
        {
            "registration_id": str(row.id),
            "site_id": str(extra.id),
            "activity": "storage",
            "evidence_reference": "Registered premises schedule",
        },
    )
    assert register.covers_activity(db, orgs[0].id, extra.id, "storage", TODAY)
    assert not register.covers_activity(db, orgs[0].id, extra.id, "manufacturing", TODAY)
    assert not register.covers_activity(db, orgs[0].id, sites[0].id, "storage", TODAY)
    assert not register.covers_activity(db, orgs[1].id, extra.id, "storage", TODAY)
    assert not register.covers_activity(db, orgs[0].id, extra.id, "storage", date(2027, 1, 1))


@pytest.mark.parametrize(
    "changes",
    [
        {"programme": []},
        {"programme": "anything"},
        {"registered_as": True},
        {"registered_on": "2027-01-01"},
        {"valid_until": False},
        {"valid_until": "2025-01-01"},
        {"reference": ""},
        {"evidence_reference": ""},
        {"org_id": str(uuid4())},
    ],
)
def test_registration_validation_is_controlled(db, world, changes):  # noqa: F811
    orgs, _, _, _ = world
    with pytest.raises(ValueError):
        register.add_registration(db, orgs[0].id, registration_data(**changes), TODAY)
    assert db.query(FoodRegistration).count() == 0


def test_foreign_scope_rejected_by_service_and_composite_fk(db, world):  # noqa: F811
    orgs, sites, _, _ = world
    row = register.add_registration(db, orgs[0].id, registration_data(), TODAY)
    with pytest.raises(ValueError):
        register.add_scope(
            db,
            orgs[0].id,
            {
                "registration_id": str(row.id),
                "site_id": str(sites[1].id),
                "activity": "storage",
                "evidence_reference": "Wrong tenant",
            },
        )
    with pytest.raises(IntegrityError):
        with db.begin_nested():
            db.add(
                FoodRegistrationSite(
                    org_id=orgs[1].id,
                    registration_id=row.id,
                    site_id=sites[1].id,
                    activity="storage",
                    evidence_reference="Raw bypass",
                )
            )
            db.flush()


def test_two_registrations_have_independent_verification_steps_and_actions(db, world):  # noqa: F811
    orgs, _, _, _ = world
    first = register.add_registration(db, orgs[0].id, registration_data(), TODAY)
    second = register.add_registration(db, orgs[0].id, registration_data(reference="NP-456", programme="np2"), TODAY)
    one = verification.record(
        db,
        orgs[0].id,
        register.registration_profile(first),
        visit_data(
            actions=[{"description": "Registration A only", "due_on": "2026-09-10", "owner_name": "Action owner"}]
        ),
        None,
        TODAY,
        first.id,
    )
    two = verification.record(
        db, orgs[0].id, register.registration_profile(second), visit_data(), None, TODAY, second.id
    )
    assert one.initial and two.initial
    assert one.step == 6 and two.step == 7
    current_a = verification.status(db, orgs[0].id, register.registration_profile(first), TODAY, first.id)
    current_b = verification.status(db, orgs[0].id, register.registration_profile(second), TODAY, second.id)
    assert len(current_a["verifications"]) == len(current_b["verifications"]) == 1
    assert current_a["open_actions"] == 1 and current_b["open_actions"] == 0
    action_id = uuid4() if not current_a["actions"] else current_a["actions"][0]["id"]
    assert verification.complete_action(db, orgs[0].id, action_id, "Wrong history", None, TODAY, second.id) is None
    legacy = verification.status(db, orgs[0].id, register.registration_profile(first), TODAY)
    assert not legacy["verifications"] and not legacy["actions"]


@pytest.fixture
def clients(db, flask_app):  # noqa: F811
    org, client = _admin_client(db, flask_app)
    other, neighbour = _admin_client(db, flask_app)
    ids = [org.id, other.id]
    try:
        yield org, client, other, neighbour
    finally:
        db.rollback()
        with unscoped():
            for model in (
                ComplianceVerificationAction,
                ComplianceVerification,
                FoodRegistrationSite,
                FoodRegistration,
                AuditLog,
            ):
                db.query(model).filter(model.org_id.in_(ids)).delete(synchronize_session=False)
            db.query(Organisation).filter(Organisation.id.in_(ids)).delete(synchronize_session=False)
            db.commit()


def test_api_registry_and_history_are_tenant_scoped(db, clients):
    org, client, _, neighbour = clients
    response = client.post("/api/compliant/food-registrations", json=registration_data())
    assert response.status_code == 201
    rid = response.get_json()["id"]
    assert neighbour.get("/api/compliant/food-registrations").get_json()["registrations"] == []
    assert neighbour.get("/api/compliant/verification", query_string={"registration_id": rid}).status_code == 404
    assert neighbour.post("/api/compliant/verification", json=visit_data(registration_id=rid)).status_code == 400
    response = client.post("/api/compliant/verification", json=visit_data(registration_id=rid))
    assert response.status_code == 201
    assert response.get_json()["registration_id"] == rid
    assert client.get("/api/compliant/verification").get_json()["verifications"] == []
    assert (
        client.put(
            "/api/compliant/verification/registration",
            json={"registration_id": rid, "registered_on": "2026-01-02", "registered_as": "existing"},
        ).status_code
        == 409
    )
    assert db.query(ComplianceVerification).filter(ComplianceVerification.org_id == org.id).count() == 1


def test_registration_alerts_use_distinct_stable_keys_and_internal_links(db, clients):
    org, client, _, _ = clients
    client.put("/api/compliant/profile", json={"enabled": True})
    first = client.post("/api/compliant/food-registrations", json=registration_data()).get_json()["id"]
    second = client.post("/api/compliant/food-registrations", json=registration_data(reference="NP-456")).get_json()[
        "id"
    ]
    result = run_verification_check(org.id, db)
    assert result.flagged
    alerts = result.data["system_alerts"]
    assert len(alerts) == 2
    assert len({alert["id"] for alert in alerts}) == 2
    assert {alert["href"] for alert in alerts} == {
        f"/compliant/nz-alcohol/food-safety?registration_id={rid}#verification" for rid in (first, second)
    }
    assert result.data["system_finding"]["details"] == alerts


def test_fcp_does_not_use_national_programme_frequency_rules(db, clients):
    _, client, _, _ = clients
    rid = client.post("/api/compliant/food-registrations", json=registration_data(programme="fcp")).get_json()["id"]
    current = client.get("/api/compliant/verification", query_string={"registration_id": rid}).get_json()
    assert current["state"] == "not_applicable" and current["registration_programme"] == "fcp"
    assert client.post("/api/compliant/verification", json=visit_data(registration_id=rid)).status_code == 400


def test_registration_writes_require_actual_csrf_token(clients, flask_app):  # noqa: F811
    class TokenParser(HTMLParser):
        token = None

        def handle_starttag(self, tag, attrs):
            values = dict(attrs)
            if tag == "meta" and values.get("name") == "csrf-token":
                self.token = values.get("content")

    _, client, _, _ = clients
    previous = flask_app.config["WTF_CSRF_ENABLED"]
    flask_app.config["WTF_CSRF_ENABLED"] = True
    try:
        endpoint = "/api/compliant/food-registrations"
        assert client.post(endpoint, json=registration_data()).status_code == 400
        parser = TokenParser()
        parser.feed(client.get("/compliant/nz-alcohol/food-registrations").get_data(as_text=True))
        assert parser.token
        response = client.post(
            endpoint,
            json=registration_data(),
            headers={
                "X-CSRFToken": parser.token,
                "Referer": "https://localhost/compliant/nz-alcohol/food-registrations",
            },
        )
        assert response.status_code == 201
    finally:
        flask_app.config["WTF_CSRF_ENABLED"] = previous


def test_concurrent_registration_visits_share_one_initial_transition(db, clients, flask_app):  # noqa: F811
    org, client, _, _ = clients
    rid = client.post("/api/compliant/food-registrations", json=registration_data()).get_json()["id"]
    cookie = client.get_cookie(flask_app.config.get("SESSION_COOKIE_NAME", "session"))
    assert cookie

    def enter_visit(_):
        worker = flask_app.test_client()
        worker.set_cookie(cookie.key, cookie.value, domain=cookie.domain)
        return worker.post(
            "/api/compliant/verification", json=visit_data(registration_id=rid), base_url="https://localhost"
        ).status_code

    with ThreadPoolExecutor(max_workers=2) as executor:
        assert list(executor.map(enter_visit, range(2))) == [201, 201]
    db.expire_all()
    rows = db.query(ComplianceVerification).filter(ComplianceVerification.org_id == org.id).all()
    assert len(rows) == 2 and sum(row.initial for row in rows) == 1


def test_database_rejects_verification_link_to_foreign_registration(db, world):  # noqa: F811
    orgs, _, _, _ = world
    row = register.add_registration(db, orgs[0].id, registration_data(), TODAY)
    with pytest.raises(IntegrityError):
        with db.begin_nested():
            db.add(
                ComplianceVerification(
                    org_id=orgs[1].id,
                    food_registration_id=row.id,
                    programme="np3",
                    verified_on=TODAY,
                    verifier_name="Raw bypass",
                    outcome="acceptable",
                    step=6,
                )
            )
            db.flush()
