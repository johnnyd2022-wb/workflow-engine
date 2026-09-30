"""NP3 evidence replay for Whistlebird Ltd (scripts/whistlebird_np3.py).

Pure tests cover manifest validation and content identity. The integration tests drive the
REAL Compliant/org routes through Flask's test client against the real test database, on a
throwaway org -- never on `Whistlebird Ltd` -- so a manifest the replay would send is
proven acceptable to the routes, and a delete-and-replay is proven to reproduce the
evidence, dates, staff link and profile.
"""

import copy
import sys
from datetime import date, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))
import whistlebird_np3 as np3  # noqa: E402

from app.core.db.models.organisation import Organisation  # noqa: E402
from app.core.db.models.user import UserRole  # noqa: E402
from app.core.db.repositories.feature_subscription_repo import FeatureSubscriptionRepository  # noqa: E402
from app.core.db.repositories.user_repo import UserRepository  # noqa: E402
from app.core.security.auth_service import AuthService  # noqa: E402
from app.features.compliant.routes.api_routes import _add_months as route_add_months  # noqa: E402
from tests.factories import DEFAULT_TEST_PASSWORD, OrganisationFactory  # noqa: E402

SIGNED_ON = "2026-03-10"
STAFF_EMAIL = "packer@whistlebird.test"

MANIFEST = {
    "profile": {
        "council_name": None,
        "trade_waste_consent_reference": None,
        "settings": {
            "food_control_programme": "np3",
            "np3_review_interval_months": 3,
            "alcohol_product_types": ["spirits"],
        },
    },
    "staff": [{"email": STAFF_EMAIL, "role": "member"}],
    "attestations": [
        {
            "control_id": "registration-scope",
            "signed_on": SIGNED_ON,
            "due_date": "2026-09-10",
            "review_interval_months": 6,
            "how_we_meet": "The founder reviews the registration after any change to the site.",
            "evidence_reference": "Drive / Food safety / Registration certificate",
            "evidence_fields": {"registration_reference": "NP3-REG-123"},
        }
    ],
    "logs": [
        {
            "control_id": "health-and-sickness",
            "fields": {
                "event_date": "2026-02-02",
                "employee_email": STAFF_EMAIL,
                "food_safety_decision": "cleared",
            },
        },
        {
            "control_id": "cleaning-and-hygiene",
            "fields": {
                "event_date": "2026-02-20",
                "area_or_equipment": "Still room floor",
                "method": "Detergent and sanitiser",
                "result": "action-required",
                "corrective_action": "Re-cleaned and re-checked.",
            },
        },
    ],
}


def _manifest(**overrides):
    return {**copy.deepcopy(MANIFEST), **overrides}


# --------------------------------------------------------------------------------------
# Pure: manifest validation and content identity
# --------------------------------------------------------------------------------------


def test_committed_manifest_is_valid():
    manifest = np3.load_np3_manifest()

    assert len(manifest.attestations) == 39
    assert len(manifest.logs) == 64  # 62 plus the policy update and the prepared simulated recall pack
    policy = next(record for record in manifest.attestations if record.control_id == "recall-policy")
    assert policy.evidence_fields["policy_reference"] == "docs/whistlebird-recall-policy.md"
    assert policy.signed_on == date(2026, 9, 23)
    assert policy.due_date == date(2027, 9, 23)
    assert policy.evidence_fields["last_policy_review"] == "2026-09-30"
    # Both decision makers have equal authority; nobody is the owner with a deputy.
    assert "both recall decision makers with equal authority" in policy.how_we_meet
    assert "deputy" not in policy.how_we_meet
    policy_text = (Path(__file__).parents[1] / "docs/whistlebird-recall-policy.md").read_text(encoding="utf-8")
    assert "deputy" not in policy_text.lower()
    assert "equal authority" in policy_text
    updates = [record for record in manifest.logs if record.control_id == "recall-policy"]
    assert [record.event_date.isoformat() for record in updates] == ["2026-09-30"]
    exercise = [record for record in manifest.logs if record.control_id == "trace-and-recall"]
    assert len(exercise) == 1
    assert exercise[0].fields["batch_or_product"].startswith("SIMULATED RECALL")
    assert "docs/whistlebird-mock-recall-juniper-berries.md" in exercise[0].fields["trace_result"]
    assert (Path(__file__).parents[1] / "docs/whistlebird-mock-recall-juniper-berries.md").is_file()
    assert (Path(__file__).parents[1] / policy.evidence_fields["policy_reference"]).is_file()
    training = [record for record in manifest.logs if record.control_id == "staff-competency"]
    # 2 staff x 9 supplied register items x 3 annual dates, plus the two recall
    # procedure training records dated 2026-09-23.
    assert len(training) == 56
    assert {record.event_date.isoformat() for record in training} == {
        "2024-02-02",
        "2025-02-02",
        "2026-02-02",
        "2026-09-23",
    }
    recall = [record for record in training if record.fields["training_topic"] == "recall-policy-procedures"]
    assert {record.fields["employee_name"] for record in recall} == {"Johnny Dempsey", "Nikolai Scott"}
    assert {member.name for member in manifest.staff} == {"Johnny Dempsey", "Nikolai Scott"}
    assert {record.fields["employee_name"] for record in training} == {"Johnny Dempsey", "Nikolai Scott"}
    assert manifest.record_count == len(manifest.attestations) + len(manifest.logs)


def test_annual_training_expands_to_category_person_and_date_and_needs_human_names():
    data = _manifest(
        staff=[{"email": STAFF_EMAIL, "name": "Pat Packer"}],
        annual_training={"dates": ["2026-02-01"], "categories": ["hand-washing-clean-clothing"]},
        logs=[],
    )

    training = np3.parse_np3_manifest(data).logs

    assert [record.fields for record in training] == [
        {"event_date": "2026-02-01", "employee_name": "Pat Packer", "training_topic": "hand-washing-clean-clothing"}
    ]
    data["staff"] = [{"email": STAFF_EMAIL}]
    with pytest.raises(np3.Np3ManifestError, match="name is required"):
        np3.parse_np3_manifest(data)
    data["staff"] = [{"email": STAFF_EMAIL, "name": "Pat Packer"}]
    data["annual_training"]["categories"] = ["not-a-category"]
    with pytest.raises(np3.Np3ManifestError, match="training categories"):
        np3.parse_np3_manifest(data)


def test_valid_manifest_parses_and_defaults_the_due_date_to_the_review_interval():
    data = _manifest()
    del data["attestations"][0]["due_date"]

    manifest = np3.parse_np3_manifest(data)

    assert manifest.attestations[0].due_date == date(2026, 9, 10)
    assert manifest.record_count == 3


def test_month_arithmetic_matches_the_attestation_route():
    for start in (date(2026, 8, 31), date(2026, 1, 31), date(2024, 2, 29), date(2026, 12, 15)):
        for months in np3.REVIEW_INTERVALS:
            assert np3._add_months(start, months) == route_add_months(start, months)


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda d: d.update(extra=1), "unknown key"),
        (lambda d: d["attestations"][0].update(source_refs=[str(uuid4())]), "source_refs cannot be replayed"),
        (lambda d: d["attestations"][0].update(control_id="not-a-control"), "unknown NP3 control"),
        (lambda d: d["attestations"][0].update(signed_on="10/03/2026"), "not a YYYY-MM-DD date"),
        (lambda d: d["attestations"][0].update(review_interval_months=5), "review_interval_months"),
        (lambda d: d["attestations"][0].update(how_we_meet="  "), "how_we_meet is required"),
        (lambda d: d["attestations"][0].update(evidence_fields={"nope": "x"}), "evidence_fields do not match"),
        (lambda d: d["attestations"].append(copy.deepcopy(d["attestations"][0])), "identical content"),
        (lambda d: d["logs"][0]["fields"].update(employee_email="stranger@x.test"), "not listed under staff"),
        (lambda d: d["logs"][0]["fields"].pop("food_safety_decision"), "is required"),
        (lambda d: d["logs"][0]["fields"].update(food_safety_decision="great"), "invalid option"),
        (lambda d: d["logs"][0]["fields"].update(employee_user_id=str(uuid4())), "do not match"),
        (lambda d: d["logs"][1]["fields"].pop("corrective_action"), "needs its corrective action"),
        (lambda d: d["logs"][1].update(control_id="registration-scope"), "no built-in NP3 log"),
        (lambda d: d["staff"].append({"email": STAFF_EMAIL.upper()}), "duplicate email"),
        (lambda d: d["staff"][0].update(role="owner"), "role must be"),
    ],
)
def test_manifest_rejects_what_the_routes_would_reject(mutate, message):
    data = _manifest()
    mutate(data)

    with pytest.raises(np3.Np3ManifestError, match=message):
        np3.parse_np3_manifest(data)


def test_fingerprint_ignores_whitespace_and_blank_fields_but_not_content():
    base = np3.attestation_fingerprint("registration-scope", "We check it.", 6, "ref", {"registration_reference": "A"})

    assert base == np3.attestation_fingerprint(
        "registration-scope", "  We check it.  ", 6, " ref ", {"registration_reference": " A ", "last_scope_review": ""}
    )
    assert base != np3.attestation_fingerprint(
        "registration-scope", "We check it!", 6, "ref", {"registration_reference": "A"}
    )
    assert base != np3.attestation_fingerprint(
        "registration-scope", "We check it.", 12, "ref", {"registration_reference": "A"}
    )
    assert np3.log_fingerprint("calibration", {"a": "1", "b": ""}) == np3.log_fingerprint("calibration", {"a": "1"})


# --------------------------------------------------------------------------------------
# Replay ordering and idempotency, with a stub client/store
# --------------------------------------------------------------------------------------


class _Client:
    def __init__(self):
        self.calls = []

    def post(self, path, body):
        self.calls.append(("POST", path, body))
        return {}

    def put(self, path, body):
        self.calls.append(("PUT", path, body))
        return {}


class _Store:
    def __init__(self, users=(), fingerprints=()):
        self.users = {email: f"user-{index}" for index, email in enumerate(users)}
        self._fingerprints = set(fingerprints)

    def user_id_for_email(self, email):
        return self.users.get(email)

    def fingerprints(self):
        return self._fingerprints


def test_replay_orders_staff_then_profile_then_attestations_then_logs_and_links_employee():
    manifest = np3.parse_np3_manifest(_manifest())
    store = _Store()

    class _CreatingClient(_Client):
        def post(self, path, body):
            super().post(path, body)
            if path == "/org/users":
                store.users[body["email"]] = "created-user-id"
            return {}

    client = _CreatingClient()
    counts = np3.replay_np3(client, store, manifest)

    assert [(method, path) for method, path, _ in client.calls] == [
        ("POST", "/org/users"),
        ("PUT", "/api/compliant/profile"),
        ("POST", "/api/compliant/np3-audit/attestations"),
        ("POST", "/api/compliant/np3-audit/checks/health-and-sickness/logs"),
        ("POST", "/api/compliant/np3-audit/checks/cleaning-and-hygiene/logs"),
    ]
    assert counts == {"staff": 1, "profile": 1, "attestations": 1, "logs": 2, "skipped": 0}
    user_body = client.calls[0][2]
    assert user_body["email"] == STAFF_EMAIL and user_body["role"] == "member" and len(user_body["password"]) >= 32
    log_fields = client.calls[3][2]["fields"]
    assert log_fields["employee_user_id"] == "created-user-id"
    assert "employee_email" not in log_fields
    assert client.calls[2][2]["confirmed"] is True


def test_replay_skips_what_already_exists():
    manifest = np3.parse_np3_manifest(_manifest())
    store = _Store(users=[STAFF_EMAIL], fingerprints=[r.fingerprint for r in (*manifest.attestations, *manifest.logs)])
    client = _Client()

    counts = np3.replay_np3(client, store, manifest)

    assert counts == {"staff": 0, "profile": 1, "attestations": 0, "logs": 0, "skipped": 4}
    assert [call[1] for call in client.calls] == ["/api/compliant/profile"]


def test_replay_without_a_profile_leaves_the_setup_baseline_alone():
    client = _Client()

    np3.replay_np3(client, _Store(), np3.parse_np3_manifest(_manifest(profile=None, staff=[], logs=[])))

    assert all(path != "/api/compliant/profile" for _, path, _ in client.calls)


# --------------------------------------------------------------------------------------
# Integration: real routes, real DB, throwaway org
# --------------------------------------------------------------------------------------


@pytest.fixture
def flask_app():
    from app.api.app_factory import create_app

    app = create_app()
    app.config.update(TESTING=True, WTF_CSRF_ENABLED=False)
    with app.app_context():
        yield app


class _FlaskClient:
    """The ReplayClient interface over Flask's test client: same routes, decorators and
    validation, without a live server."""

    def __init__(self, client):
        self._client = client

    def _send(self, method, path, body):
        response = getattr(self._client, method)(path, json=body)
        assert response.status_code in (
            200,
            201,
        ), f"{method.upper()} {path} -> {response.status_code}: {response.data!r}"
        return response.get_json()

    def post(self, path, body):
        return self._send("post", path, body)

    def put(self, path, body):
        return self._send("put", path, body)


def _setup_baseline(client):
    """What `--setup-compliant-nz-alcohol` gives Whistlebird Ltd before any replay."""
    client.put(
        "/api/compliant/profile",
        {"enabled": True, "industry_module": "nz_alcohol", "settings": np3.wm.WHISTLEBIRD_NZ_ALCOHOL_SETTINGS},
    )


@pytest.fixture
def np3_org(db, flask_app):
    org = OrganisationFactory()
    admin_email = f"np3-admin-{uuid4().hex[:8]}@test.com"
    UserRepository(db).create_user(
        org_id=org.id,
        email=admin_email,
        password_hash=AuthService.hash_password(DEFAULT_TEST_PASSWORD),
        role=UserRole.ADMIN,
        is_active=True,
    )
    FeatureSubscriptionRepository(db).grant(org.id, "compliant")
    db.commit()
    client = flask_app.test_client()
    client.environ_base["wsgi.url_scheme"] = "https"
    client.environ_base["HTTP_X_FORWARDED_PROTO"] = "https"
    assert client.post("/auth/login", json={"email": admin_email, "password": DEFAULT_TEST_PASSWORD}).status_code == 200
    client_wrapper = _FlaskClient(client)
    _setup_baseline(client_wrapper)
    url = db.get_bind().url.render_as_string(hide_password=False)
    try:
        yield {"org": org, "name": org.name, "admin_email": admin_email, "client": client_wrapper, "url": url}
    finally:
        db.rollback()
        db.query(Organisation).filter(Organisation.id == org.id).delete(synchronize_session=False)
        db.commit()


def _replay(ctx, manifest):
    store = np3.Np3Store(ctx["url"], ctx["org"].id)
    try:
        return np3.replay_np3(ctx["client"], store, manifest)
    finally:
        store.dispose()


def _reset(db, ctx):
    """What the scoped reset does to NP3 evidence, plus the staff user an org removal loses."""
    db.execute(text("DELETE FROM compliance_records WHERE org_id = :o"), {"o": ctx["org"].id})
    db.execute(text("DELETE FROM users WHERE org_id = :o AND email = :e"), {"o": ctx["org"].id, "e": STAFF_EMAIL})
    db.execute(text("DELETE FROM compliance_profiles WHERE org_id = :o"), {"o": ctx["org"].id})
    db.commit()
    _setup_baseline(ctx["client"])  # the bootstrap re-creates the profile before replaying


def test_manifest_is_accepted_by_the_real_routes_and_dated_explicitly(db, np3_org):
    manifest = np3.parse_np3_manifest(_manifest())

    counts = _replay(np3_org, manifest)
    updated = np3.correct_np3_timestamps(np3_org["url"], np3_org["name"], manifest)
    report = np3.verify_np3(np3_org["url"], np3_org["name"], manifest)

    assert counts == {"staff": 1, "profile": 1, "attestations": 1, "logs": 2, "skipped": 0}
    assert updated == 3
    assert report == {
        "np3_record_count": {"expected": 3, "actual": 3},
        "np3_record_content": {"expected": 3, "actual": 3},
        "np3_staff": {"expected": 1, "actual": 1},
        "np3_profile": {"expected": 1, "actual": 1},
        "np3_date_mismatches": 0,
    }
    rows = {
        (row.control_id, row.record_type): row
        for row in db.execute(
            text(
                "SELECT control_id, record_type, status, due_date, period_start, "
                "(created_at AT TIME ZONE 'Pacific/Auckland')::date AS created_on, owner_user_id "
                "FROM compliance_records WHERE org_id = :o AND framework_slug = 'np3-food-control'"
            ),
            {"o": np3_org["org"].id},
        )
    }
    attestation = rows[("registration-scope", "attestation")]
    assert (attestation.created_on, attestation.due_date) == (date(2026, 3, 10), date(2026, 9, 10))
    attestation_audit_date = db.execute(
        text(
            "SELECT (a.timestamp AT TIME ZONE 'Pacific/Auckland')::date "
            "FROM audit_logs a JOIN compliance_records r ON r.id = a.entity_id "
            "WHERE a.org_id = :o AND a.entity = 'compliance_record' AND a.action = 'create' "
            "AND r.control_id = 'registration-scope'"
        ),
        {"o": np3_org["org"].id},
    ).scalar_one()
    assert attestation_audit_date == attestation.created_on
    training = rows[("health-and-sickness", "incident")]
    assert training.created_on == date(2026, 2, 2) and training.owner_user_id is not None
    follow_up = rows[("cleaning-and-hygiene", "reading")]
    assert follow_up.status == "open" and follow_up.created_on == date(2026, 2, 20)
    staff_date = db.execute(
        text(
            "SELECT (created_at AT TIME ZONE 'Pacific/Auckland')::date FROM users WHERE org_id = :o AND email = :email"
        ),
        {"o": np3_org["org"].id, "email": STAFF_EMAIL},
    ).scalar_one()
    audit_date = db.execute(
        text(
            "SELECT DISTINCT (timestamp AT TIME ZONE 'Pacific/Auckland')::date FROM audit_logs "
            "WHERE org_id = :o AND entity = 'user' AND action = 'create' "
            "AND entity_id = (SELECT id FROM users WHERE email = :email)"
        ),
        {"o": np3_org["org"].id, "email": STAFF_EMAIL},
    ).scalar_one()
    assert staff_date == audit_date == date(2026, 2, 1)
    profile_audit_date = db.execute(
        text(
            "SELECT DISTINCT (timestamp AT TIME ZONE 'Pacific/Auckland')::date FROM audit_logs "
            "WHERE org_id = :o AND entity = 'compliance_profile' AND action = 'update'"
        ),
        {"o": np3_org["org"].id},
    ).scalar_one()
    assert profile_audit_date == date(2026, 2, 1)


def test_committed_manifest_replays_all_review_placeholders(db, np3_org):
    # User emails are globally unique, and the test DB may already contain the
    # Whistlebird tenant. Keep its evidence unchanged while giving this org its own users.
    data = copy.deepcopy(np3.load_np3_manifest().raw)
    email_map = {}
    for member in data["staff"]:
        original = member["email"]
        member["email"] = f"np3-{uuid4().hex[:12]}@test.com"
        email_map[original] = member["email"]
    for entry in data["logs"]:
        fields = entry["fields"]
        if "employee_email" in fields:
            fields["employee_email"] = email_map[fields["employee_email"]]
    manifest = np3.parse_np3_manifest(data)

    counts = _replay(np3_org, manifest)
    updated = np3.correct_np3_timestamps(np3_org["url"], np3_org["name"], manifest)
    report = np3.verify_np3(np3_org["url"], np3_org["name"], manifest)

    assert counts == {"staff": 2, "profile": 1, "attestations": 39, "logs": 64, "skipped": 0}
    assert updated == 103
    assert report == {
        "np3_record_count": {"expected": 103, "actual": 103},
        "np3_record_content": {"expected": 103, "actual": 103},
        "np3_staff": {"expected": 2, "actual": 2},
        "np3_profile": {"expected": 1, "actual": 1},
        "np3_date_mismatches": 0,
    }
    policy_dates = db.execute(
        text(
            "SELECT (r.created_at AT TIME ZONE 'Pacific/Auckland')::date, "
            "(a.timestamp AT TIME ZONE 'Pacific/Auckland')::date "
            "FROM compliance_records r JOIN audit_logs a ON a.entity_id = r.id "
            "WHERE r.org_id = :org AND r.control_id = 'recall-policy' AND r.details->>'how_we_meet' IS NOT NULL "
            "AND a.org_id = :org AND a.entity = 'compliance_record' AND a.action = 'create'"
        ),
        {"org": np3_org["org"].id},
    ).one()
    assert policy_dates == (date(2026, 9, 23), date(2026, 9, 23))


def test_replay_is_idempotent(db, np3_org):
    manifest = np3.parse_np3_manifest(_manifest())
    _replay(np3_org, manifest)

    second = _replay(np3_org, manifest)

    assert (second["staff"], second["attestations"], second["logs"]) == (0, 0, 0)
    assert second["skipped"] == 4
    assert np3.verify_np3(np3_org["url"], np3_org["name"], manifest)["np3_record_count"] == {"expected": 3, "actual": 3}


def test_snapshot_round_trips_and_a_reset_replay_reproduces_the_evidence(db, np3_org):
    manifest = np3.parse_np3_manifest(_manifest())
    _replay(np3_org, manifest)
    np3.correct_np3_timestamps(np3_org["url"], np3_org["name"], manifest)

    snapshot = np3._snapshot_org(np3_org["url"], np3_org["name"], manifest, np3_org["admin_email"])
    snapshotted = np3.parse_np3_manifest(snapshot)

    assert snapshot["staff"] == [{"email": STAFF_EMAIL, "role": "member"}]
    assert snapshot["profile"]["settings"] == MANIFEST["profile"]["settings"]
    assert {r.fingerprint for r in (*snapshotted.attestations, *snapshotted.logs)} == {
        r.fingerprint for r in (*manifest.attestations, *manifest.logs)
    }
    assert (snapshotted.attestations[0].signed_on, snapshotted.attestations[0].due_date) == (
        date(2026, 3, 10),
        date(2026, 9, 10),
    )
    assert np3.np3_unsnapshotted(np3_org["url"], np3_org["name"], snapshotted, np3_org["admin_email"]) == []

    # Delete and start again from the committed snapshot alone.
    _reset(db, np3_org)
    assert np3.verify_np3(np3_org["url"], np3_org["name"], snapshotted)["np3_record_count"]["actual"] == 0
    _replay(np3_org, snapshotted)
    np3.correct_np3_timestamps(np3_org["url"], np3_org["name"], snapshotted)
    report = np3.verify_np3(np3_org["url"], np3_org["name"], snapshotted)

    assert all(pair["expected"] == pair["actual"] for pair in report.values() if isinstance(pair, dict))
    assert report["np3_date_mismatches"] == 0


def test_snapshot_keeps_dates_already_set_in_the_manifest(db, np3_org):
    manifest = np3.parse_np3_manifest(_manifest())
    _replay(np3_org, manifest)  # deliberately NOT dated: the database says "today"

    fresh = np3._snapshot_org(np3_org["url"], np3_org["name"], None, np3_org["admin_email"])
    kept = np3._snapshot_org(np3_org["url"], np3_org["name"], manifest, np3_org["admin_email"])

    # The snapshot dates rows in the org's local (NZ) day, not the runner's: CI is UTC, so
    # date.today() is a day behind between 12:00 and 24:00 UTC.
    assert fresh["attestations"][0]["signed_on"] == datetime.now(np3._LOCAL_TZ).date().isoformat()
    assert (kept["attestations"][0]["signed_on"], kept["attestations"][0]["due_date"]) == (SIGNED_ON, "2026-09-10")


def test_reset_guard_reports_evidence_the_manifest_lacks(db, np3_org):
    manifest = np3.parse_np3_manifest(_manifest())
    _replay(np3_org, manifest)
    assert np3.np3_unsnapshotted(np3_org["url"], np3_org["name"], manifest, np3_org["admin_email"]) == []

    np3_org["client"].post(
        "/api/compliant/np3-audit/attestations",
        {"control_id": "staff-competency", "how_we_meet": "Typed after the snapshot.", "confirmed": True},
    )

    reasons = np3.np3_unsnapshotted(np3_org["url"], np3_org["name"], manifest, np3_org["admin_email"])
    assert len(reasons) == 1 and "not in the manifest" in reasons[0]
    assert np3.np3_unsnapshotted(np3_org["url"], "no-such-org-" + uuid4().hex, manifest) == []


def test_snapshot_refuses_evidence_it_cannot_replay(db, np3_org):
    db.execute(
        text(
            "INSERT INTO compliance_records (id, org_id, framework_slug, control_id, record_type, status, title, "
            "source_refs, details, created_at, updated_at) VALUES (:id, :o, 'np3-food-control', 'staff-competency', "
            "'attestation', 'complete', 'linked', CAST(:refs AS jsonb), CAST(:details AS jsonb), now(), now())"
        ),
        {
            "id": str(uuid4()),
            "o": np3_org["org"].id,
            "refs": f'["{uuid4()}"]',
            "details": '{"how_we_meet": "Linked to a Core record.", "review_interval_months": 6}',
        },
    )
    db.commit()

    with pytest.raises(np3.Np3SnapshotError, match="source_refs"):
        np3._snapshot_org(np3_org["url"], np3_org["name"], None, np3_org["admin_email"])


def test_snapshot_is_only_permitted_for_the_test_tenant():
    with pytest.raises(ValueError, match="only permitted"):
        np3.snapshot_np3("postgresql://unused", "Some Other Org")
