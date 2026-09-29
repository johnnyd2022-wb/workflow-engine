"""Plan item 2.2: verifications from visit to next due date (Food Regulations 94)."""

from datetime import date, timedelta
from uuid import uuid4

import pytest

from app.core.db.models.organisation import Organisation
from app.features.compliant.models.verification import ComplianceVerification, ComplianceVerificationAction
from app.features.compliant.modules.nz_alcohol import verification as v
from app.features.compliant.modules.nz_alcohol.module import run_check, run_verification_check
from tests.dag_traversal_helpers import clear_org_synthetic_data
from tests.test_compliant_routes import _admin_client, flask_app  # noqa: F401 -- fixture re-export

TODAY = date.today()


# --- MPI's frequency rules --------------------------------------------------------------------


@pytest.mark.parametrize(
    ("programme", "outcome", "initial", "attitude", "previous", "step"),
    [
        # initial verification
        ("np1", "acceptable", True, None, None, 8),
        ("np2", "acceptable", True, None, None, 7),
        ("np3", "acceptable", True, None, None, 6),
        ("np1", "unacceptable", True, "willing", None, 6),
        ("np2", "unacceptable", True, "willing", None, 5),
        ("np3", "unacceptable", True, "willing", None, 4),
        ("np1", "unacceptable", True, "unwilling", None, 4),
        ("np2", "unacceptable", True, "unwilling", None, 3),
        ("np3", "unacceptable", True, "unwilling", None, 2),
        ("np3", "unacceptable", True, "immediate_risk", None, 1),
        # later verifications: acceptable goes up one step, capped per programme
        ("np3", "acceptable", False, None, 4, 5),
        ("np3", "acceptable", False, None, 6, 6),
        ("np2", "acceptable", False, None, 7, 7),
        ("np1", "acceptable", False, None, 7, 8),
        # unacceptable goes down one (willing) or two (unwilling), within the programme's range
        ("np3", "unacceptable", False, "willing", 6, 5),
        ("np3", "unacceptable", False, "willing", 5, 4),
        ("np3", "unacceptable", False, "unwilling", 6, 4),
        ("np3", "unacceptable", False, "unwilling", 2, 1),
        ("np2", "unacceptable", False, "immediate_risk", 7, 1),
    ],
)
def test_suggested_step_follows_food_regulations_94(programme, outcome, initial, attitude, previous, step):
    assert v.suggest_step(programme, outcome, initial, attitude, previous) == step


def test_steps_dates_and_initial_due():
    assert [v.step_label(s) for s in (1, 4, 5, 6, 7, 8)] == [
        "every 3 months",
        "every year",
        "every 18 months",
        "every 2 years",
        "every 3 years",
        "no further verification",
    ]
    assert v.add_months(date(2026, 8, 31), 6) == date(2027, 2, 28)
    assert v.initial_due("np3", date(2026, 1, 10), "new") == date(2026, 2, 21)  # 6 weeks
    assert v.initial_due("np3", date(2026, 1, 10), "existing") == date(2026, 7, 10)  # 6 months
    assert v.initial_due("np2", date(2026, 1, 10), "existing") == date(2027, 1, 10)  # 1 year
    assert list(v.allowed_steps("np3", "unacceptable", False)) == [1, 2, 3, 4, 5]
    assert list(v.allowed_steps("np3", "acceptable", True)) == [6]


# --- against a real tenant -----------------------------------------------------------------------


@pytest.fixture
def world(db, flask_app):  # noqa: F811
    org, client = _admin_client(db, flask_app)
    client.put(
        "/api/compliant/profile",
        json={
            "enabled": True,
            "settings": {
                "alcohol_product_types": ["spirits"],
                "food_control_programme": "np3",
                "np3_verification_date": (TODAY - timedelta(days=3)).isoformat(),
                "np3_verifier_name": "Sam Verifier",
            },
        },
    )
    yield {"org": org, "client": client, "db": db}
    db.rollback()
    for model in (ComplianceVerificationAction, ComplianceVerification):
        db.query(model).filter(model.org_id == org.id).delete(synchronize_session=False)
    db.commit()
    clear_org_synthetic_data(db, org.id)
    db.query(Organisation).filter(Organisation.id == org.id).delete(synchronize_session=False)
    db.commit()


def _record(client, **body):
    return client.post("/api/compliant/verification", json=body)


def _staff_id(client):
    return client.get("/api/compliant/verification").get_json()["staff"][0]["id"]


def test_registration_sets_the_initial_verification_date(world):
    client = world["client"]
    status = client.get("/api/compliant/verification").get_json()
    assert status["state"] == "not_recorded" and status["next_due"] is None
    assert client.put("/api/compliant/verification/registration", json={"registered_on": "x"}).status_code == 400
    registered = TODAY - timedelta(days=10)
    resp = client.put(
        "/api/compliant/verification/registration",
        json={"registered_on": registered.isoformat(), "registered_as": "new"},
    )
    assert resp.status_code == 200
    status = resp.get_json()
    assert status["state"] == "initial_due" and status["next_due"] == (registered + timedelta(weeks=6)).isoformat()
    # The profile form doesn't wipe it (it doesn't send these keys).
    world["client"].put("/api/compliant/profile", json={"enabled": True, "settings": {"food_control_programme": "np3"}})
    assert client.get("/api/compliant/verification").get_json()["registered_as"] == "new"


def test_initial_acceptable_verification_sets_two_years_and_clears_the_booked_visit(world):
    client, db, org = world["client"], world["db"], world["org"]
    visited = TODAY - timedelta(days=2)
    resp = _record(
        client,
        verified_on=visited.isoformat(),
        verifier_name="Sam Verifier",
        verifier_agency="Council",
        outcome="acceptable",
        initial=True,
        actions=[
            {
                "description": "Relabel the sanitiser bottle",
                "owner_user_id": _staff_id(client),
                "due_on": TODAY.isoformat(),
            }
        ],
    )
    assert resp.status_code == 201, resp.get_json()
    status = resp.get_json()
    assert status["current_step"] == 6 and status["frequency"] == "every 2 years"
    assert status["next_due"] == v.add_months(visited, 24).isoformat() and status["state"] == "scheduled"
    assert status["last"]["initial"] is True
    (action,) = status["actions"]
    assert action["owner"] and action["status"] == "open" and status["open_actions"] == 1

    audit = client.get("/api/compliant/np3-audit").get_json()
    assert audit["verification"]["date"] is None  # the booked visit happened

    # The dashboard summary carries the next date; alerts include the action due today.
    result = run_check(org.id, db)
    milestone = result.data["workspace_summary"]["milestone"]
    assert milestone["label"] == "Next verification" and milestone["date"] == status["next_due"]
    assert "1 open corrective action" in milestone["detail"]
    alerts = run_verification_check(org.id, db).data["system_alerts"]
    assert [a["id"] for a in alerts] == [f"verification-action-{action['id']}"]

    done = client.post(f"/api/compliant/verification/actions/{action['id']}/complete", json={"note": "New label"})
    assert done.status_code == 200 and done.get_json()["actions"][0]["status"] == "done"
    again = client.post(f"/api/compliant/verification/actions/{action['id']}/complete", json={})
    assert again.status_code == 409
    assert run_verification_check(org.id, db).flagged is False


def test_later_unacceptable_verification_steps_down_and_can_follow_the_verifier(world):
    client = world["client"]
    first = TODAY - timedelta(days=400)
    _record(client, verified_on=first.isoformat(), verifier_name="A", outcome="acceptable", initial=True)
    visited = TODAY - timedelta(days=1)

    missing = _record(client, verified_on=visited.isoformat(), verifier_name="B", outcome="unacceptable")
    assert missing.status_code == 400 and "willing" in missing.get_json()["error"]
    out_of_range = _record(
        client, verified_on=visited.isoformat(), verifier_name="B", outcome="unacceptable", attitude="willing", step=6
    )
    assert out_of_range.status_code == 400 and "1 to 5" in out_of_range.get_json()["error"]

    suggested = client.get(
        f"/api/compliant/verification/suggest?outcome=unacceptable&attitude=willing&previous_step=6&verified_on={visited}"
    ).get_json()
    assert suggested["step"] == 5 and suggested["next_due"] == v.add_months(visited, 18).isoformat()

    # The verifier set 6 months and a specific date in their report.
    report_date = v.add_months(visited, 6) + timedelta(days=3)
    resp = _record(
        client,
        verified_on=visited.isoformat(),
        verifier_name="B",
        outcome="unacceptable",
        attitude="willing",
        step=2,
        next_due=report_date.isoformat(),
    )
    assert resp.status_code == 201, resp.get_json()
    status = resp.get_json()
    assert status["current_step"] == 2 and status["next_due"] == report_date.isoformat()
    assert [x["outcome"] for x in status["verifications"]] == ["unacceptable", "acceptable"]

    earlier = _record(client, verified_on=first.isoformat(), verifier_name="C", outcome="acceptable")
    assert earlier.status_code == 400
    future = _record(
        client, verified_on=(TODAY + timedelta(days=1)).isoformat(), verifier_name="C", outcome="acceptable"
    )
    assert future.status_code == 400


def test_existing_history_without_an_initial_record_uses_the_current_step(world):
    client = world["client"]
    resp = _record(
        client,
        verified_on=(TODAY - timedelta(days=5)).isoformat(),
        verifier_name="A",
        outcome="acceptable",
        previous_step=5,
    )
    assert resp.status_code == 201 and resp.get_json()["current_step"] == 6


def test_overdue_and_due_soon_alerts(world):
    client, db, org = world["client"], world["db"], world["org"]
    visited = TODAY - timedelta(days=700)
    _record(client, verified_on=visited.isoformat(), verifier_name="A", outcome="acceptable", initial=True)
    status = client.get("/api/compliant/verification").get_json()
    assert status["days_until"] < 60 and not status["overdue"]
    (alert,) = run_verification_check(org.id, db).data["system_alerts"]
    assert alert["title"].startswith("NP3 verification due")
    later = v.alerts(status, date.fromisoformat(status["next_due"]) + timedelta(days=1))
    assert later[0]["description"].startswith("Overdue")
    assert v.milestone({**status, "overdue": True})["overdue"] is True


def test_np1_acceptable_initial_means_no_further_verification(world):
    client = world["client"]
    client.put("/api/compliant/profile", json={"enabled": True, "settings": {"food_control_programme": "np1"}})
    resp = _record(client, verified_on=TODAY.isoformat(), verifier_name="A", outcome="acceptable", initial=True)
    status = resp.get_json()
    assert status["state"] == "no_further" and status["next_due"] is None and status["current_step"] == 8


def test_owners_and_actions_are_tenant_scoped(world, db, flask_app):  # noqa: F811
    client = world["client"]
    other_org, other = _admin_client(db, flask_app)
    try:
        other.put("/api/compliant/profile", json={"enabled": True, "settings": {"food_control_programme": "np3"}})
        stranger = other.get("/api/compliant/verification").get_json()["staff"][0]["id"]
        bad = _record(
            client,
            verified_on=TODAY.isoformat(),
            verifier_name="A",
            outcome="acceptable",
            initial=True,
            actions=[{"description": "x", "owner_user_id": stranger, "due_on": TODAY.isoformat()}],
        )
        assert bad.status_code == 400 and "owner" in bad.get_json()["error"]
        ok = _record(
            client,
            verified_on=TODAY.isoformat(),
            verifier_name="A",
            outcome="acceptable",
            initial=True,
            actions=[{"description": "x", "owner_name": "Contractor", "due_on": TODAY.isoformat()}],
        )
        action_id = ok.get_json()["actions"][0]["id"]
        assert ok.get_json()["actions"][0]["owner"] == "Contractor"
        assert other.post(f"/api/compliant/verification/actions/{action_id}/complete", json={}).status_code == 404
        assert other.post(f"/api/compliant/verification/actions/{uuid4()}/complete", json={}).status_code == 404
    finally:
        clear_org_synthetic_data(db, other_org.id)
        db.query(Organisation).filter(Organisation.id == other_org.id).delete(synchronize_session=False)
        db.commit()
