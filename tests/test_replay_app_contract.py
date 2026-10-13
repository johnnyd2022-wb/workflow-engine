"""What the API-replay framework assumes about the app it drives, pinned against the real app.

`scripts/whistlebird_replay.py` loads a tenant by logging in over HTTP and then issuing
~625 mutating calls from a single client. That only works while these properties of the
app hold. Each was an open question in docs/whistlebird-replay-plan.md until it was
answered from code (findings-index 5c84c42e, bd5d240a, 84760d00 and 497d155a); these tests
keep the answers true, so a change that breaks the replay fails here rather than at request
N of a run. (The remaining one -- that completing a step through the real route consumes
its `actual_inputs` -- is pinned where the route is tested, in
tests/test_executions.py::TestConsumptionOnlyStepCompletion.)

1. No app-wide rate limit. Flask-Limiter is built with no `default_limits`, so only routes
   that carry an explicit `@limiter.limit` are throttled. Adding a default limit is a
   reasonable hardening step -- when it happens, this test going red is the prompt to
   decide how the replay / demo-reset tooling is exempted, not a reason to loosen the test.
   It pins the business routes the replay calls and deliberately says nothing about
   `/auth/*`, so limiting those (e.g. `/auth/verify-2fa`, F6 in
   .agents/reports/auth/security-audit.md) is not blocked by it.
2. A CSRF handshake a script can satisfy: `/auth/*` is exempt (so login needs no token),
   every other mutating route needs `X-CSRFToken`, and the token is published as a
   `<meta name="csrf-token">` on the authenticated SPA shell.
3. The replay cannot drive a 2FA-gated account -- `ReplayClient.login` refuses one -- so
   the deterministic replay admin must keep 2FA off.
4. A trial is a regular execution, not a separate kind of thing: it replays through the same
   two endpoints (create an execution, complete its steps) as a production batch.
5. A customs lodgement is a Compliant record: the replay's payload is accepted by
   `POST /api/compliant/records` as it stands.

The CSRF and 2FA tests run the real `ReplayClient` code paths. Only its transport is
swapped: Flask's test client stands in for `requests.Session`, because `ReplayClient`
itself targets a live server.
"""

import sys
from datetime import date
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest

from app.api.app_factory import create_app
from app.core.db.models.organisation import Organisation
from app.core.db.models.user import User
from app.core.db.repositories.feature_subscription_repo import FeatureSubscriptionRepository
from app.core.db.repositories.user_repo import UserRepository
from app.core.security.auth_service import AuthService
from app.features.compliant.models import ComplianceProfile, ComplianceRecord
from tests.factories import DEFAULT_TEST_PASSWORD, OrganisationFactory

sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))
import whistlebird_migration as wm  # noqa: E402
import whistlebird_replay as replay  # noqa: E402
import whistlebird_replay_timeline as timeline  # noqa: E402

BASE_URL = "https://localhost"

# Sized to the replay itself (~625 calls; the plan says "~700+"). Flask-Limiter buckets a
# default limit per endpoint, so hitting one endpoint this often catches any default limit
# the replay's busiest endpoint could trip -- a smaller probe would miss e.g. "200 per hour".
PROBES_PER_ROUTE = 700

UNKNOWN_ID = "00000000-0000-0000-0000-000000000000"


def _https_client(flask_app):
    client = flask_app.test_client()
    client.environ_base["wsgi.url_scheme"] = "https"
    client.environ_base["HTTP_X_FORWARDED_PROTO"] = "https"
    return client


@pytest.fixture
def flask_app():
    """A real app with CSRF protection and the rate limiter left exactly as configured."""
    app = create_app()
    app.config["TESTING"] = True
    with app.app_context():
        yield app


# --- 1. no app-wide rate limit --------------------------------------------------------


def test_limiter_enforces_a_limit_in_this_app(flask_app):
    """Positive control for the test below: a route that *does* carry a limit is throttled
    here, so "no 429 on the other routes" reflects the routes, not a disabled limiter."""

    def probe():
        return "ok"

    probe.__name__ = f"limiter_probe_{uuid4().hex}"
    flask_app.add_url_rule("/_limiter_probe", view_func=flask_app.limiter.limit("3 per minute")(probe))

    client = _https_client(flask_app)
    statuses = [client.get("/_limiter_probe").status_code for _ in range(5)]

    assert statuses == [200, 200, 200, 429, 429]


@pytest.mark.parametrize(
    "path",
    [
        pytest.param("/api/core/inventory", id="inventory-list"),
        pytest.param(f"/api/core/executions/{UNKNOWN_ID}", id="execution-read"),
    ],
)
def test_business_routes_the_replay_calls_are_never_throttled(flask_app, path):
    """The replay's ~625 sequential calls must not hit a 429 partway through a run.

    Unauthenticated GETs are enough: Flask-Limiter runs in `before_request`, ahead of both
    the auth decorators and the view, so a default limit would surface as a 429 here
    instead of the 401/302 an anonymous caller otherwise gets. Asserting that set of
    statuses (rather than only "no 429") also proves the probe reached a real, guarded
    route -- a 404/405 would skip the limiter and make the test pass vacuously.
    """
    client = _https_client(flask_app)

    statuses = {client.get(path).status_code for _ in range(PROBES_PER_ROUTE)}

    assert statuses <= {401, 302}, f"{path} answered {sorted(statuses)}; the replay assumes no default limit"


# --- 2 & 3. the login / CSRF / 2FA handshake -----------------------------------------


class _Response:
    """The slice of `requests.Response` that ReplayClient reads."""

    def __init__(self, response):
        self.status_code = response.status_code
        self.text = response.get_data(as_text=True)
        self._response = response

    def json(self):
        return self._response.get_json()


class _WsgiSession:
    """Stands in for `requests.Session`, routing ReplayClient's calls into Flask's test client."""

    def __init__(self, client):
        self._client = client

    def _path(self, url):
        assert url.startswith(BASE_URL), url
        return url[len(BASE_URL) :]

    def get(self, url, timeout=None):
        return _Response(self._client.get(self._path(url)))

    def post(self, url, json=None, headers=None, timeout=None):
        return _Response(self._client.post(self._path(url), json=json, headers=headers or {}))


@pytest.fixture
def replay_env(db, flask_app):
    """One org + user (2FA off, the column default, as `ensure_target_org_admin` leaves it),
    plus a ReplayClient wired to the real app and the raw test client it sits on."""
    org = OrganisationFactory()
    db.commit()
    org_id = org.id

    email = f"replay_{uuid4()}@test.com"
    user = UserRepository(db).create_user(
        org_id=org_id,
        email=email,
        password_hash=AuthService.hash_password(DEFAULT_TEST_PASSWORD),
        is_active=True,
    )
    db.commit()
    user_id = user.id

    raw_client = _https_client(flask_app)
    replay_client = replay.ReplayClient(BASE_URL)
    replay_client.session = _WsgiSession(raw_client)

    yield {"email": email, "user_id": user_id, "replay_client": replay_client, "raw_client": raw_client}

    db.rollback()
    db.query(Organisation).filter(Organisation.id == org_id).delete(synchronize_session=False)
    db.commit()


def test_csrf_protects_business_routes_and_the_replay_handshake_satisfies_it(replay_env):
    replay_client = replay_env["replay_client"]
    body = {}  # invalid on purpose: nothing is created; only *why* it is rejected matters

    # Control: the same request from a logged-in session that has no token is a CSRF failure.
    replay_env["raw_client"].post("/auth/login", json={"email": replay_env["email"], "password": DEFAULT_TEST_PASSWORD})
    without_token = replay_env["raw_client"].post(
        "/api/core/inventory", json=body, headers={"Referer": f"{BASE_URL}/core/dashboard"}
    )
    assert without_token.status_code == 400
    assert "CSRF" in without_token.get_data(as_text=True)

    # login() needs no token (`/auth/*` is CSRF-exempt) and must find the meta tag on /core/dashboard.
    replay_client.login(replay_env["email"], DEFAULT_TEST_PASSWORD)

    # With the token (and the Referer Flask-WTF demands over HTTPS) the request clears the CSRF
    # layer and is rejected by the route's own validation. Match that JSON error rather than the
    # absence of "CSRF": a missing Referer fails with Flask-WTF's HTML 400 "The referrer header is
    # missing.", which never contains the word.
    with pytest.raises(replay.ReplayRejectedError) as rejected:
        replay_client.post("/api/core/inventory", body)
    assert '{"error":"quantity is required"}' in str(rejected.value)


def test_replay_client_refuses_an_account_with_2fa_enabled(db, replay_env):
    db.query(User).filter(User.id == replay_env["user_id"]).update({"two_factor_enabled": True})
    db.commit()

    # ReplayClient's message always starts "login failed or requires 2FA", so match the
    # response it echoes: a wrong password, a lockout or a 429 must not satisfy this test.
    with pytest.raises(replay.ReplayRejectedError, match=r'requires 2FA: 200 \{"requires_2fa":\s*true'):
        replay_env["replay_client"].login(replay_env["email"], DEFAULT_TEST_PASSWORD)


# --- 4. a trial is a regular execution ------------------------------------------------


class _RecordingClient:
    """Captures what an executor would POST, without sending it anywhere."""

    def __init__(self):
        self.posts = []

    def post(self, path, payload):
        self.posts.append((path, payload))
        return {"id": str(uuid4())}


class _TrialStore:
    """Just enough MarkerStore for `_execute_create_execution` on a trial that has not run yet."""

    def __init__(self, process_id):
        self._process_id = process_id
        self.created = []

    def existing_execution_id(self, marker):
        return None

    def process_id_for_workflow(self, workflow_name):
        return self._process_id

    def note_created_execution(self, marker, execution_id):
        self.created.append((marker, execution_id))


def _a_trial():
    return wm.TrialRecord(
        workflow_name="Trial workflow",
        source_table="product_actions_flavor_experiments",
        source_id=1,
        source_date=date(2023, 6, 18),
        label="Trial 1",
        distillate_ml=Decimal("500"),
        library_ml=Decimal("50"),
        consumed=(),
        extra_data={},
    )


def test_a_trial_replays_through_the_same_two_endpoints_as_a_production_batch(flask_app):
    events = timeline._trial_events(_a_trial())

    # No trial-specific event type: a trial compiles to "create an execution" followed by
    # "complete its steps", and both are dispatched to the executors batches use.
    assert {event.event_type for event in events} == {"create_execution", "complete_step"}
    assert all(event.event_type in replay.DISPATCH for event in events)
    assert replay.DISPATCH["create_execution"] is replay._execute_create_execution
    assert replay.DISPATCH["complete_step"] is replay._execute_complete_step

    # The create executor posts to the plain executions route for a trial, and that route is
    # a POST in the real app -- there is no trial route to call instead.
    process_id = uuid4()
    client, store = _RecordingClient(), _TrialStore(process_id)
    assert replay.DISPATCH[events[0].event_type](client, store, events[0]) is True
    assert client.posts == [("/api/core/executions", {"process_id": str(process_id)})]
    assert any(
        rule.rule == "/api/core/executions" and "POST" in rule.methods for rule in flask_app.url_map.iter_rules()
    )
    assert store.created and store.created[0][0] == _a_trial().marker


class _TrialStepsStore:
    """MarkerStore answers for a trial whose execution exists and whose steps are all pending."""

    def __init__(self, execution_id, step_ids):
        self._execution_id = execution_id
        self._steps = [{"id": step_id, "step_number": index + 1} for index, step_id in enumerate(step_ids)]

    def existing_execution_id(self, marker):
        return self._execution_id

    def step_already_completed(self, execution_id, step_number):
        return False

    def execution_steps(self, execution_id):
        return self._steps


def test_a_trials_steps_complete_through_the_production_complete_step_route(flask_app):
    trial = _a_trial()
    events = timeline._trial_events(trial)[1:]  # the create event is covered above
    assert [event.payload["step_key"] for event in events] == list(wm.TRIAL_STEP_KEYS)

    execution_id = str(uuid4())
    step_ids = [str(uuid4()) for _ in events]
    client, store = _RecordingClient(), _TrialStepsStore(execution_id, step_ids)
    for event in events:
        assert replay.DISPATCH[event.event_type](client, store, event) is True

    assert [path for path, _ in client.posts] == [
        f"/api/core/executions/{execution_id}/steps/{step_id}/complete" for step_id in step_ids
    ]
    assert any(
        rule.rule == "/api/core/executions/<execution_id>/steps/<execution_step_id>/complete" and "POST" in rule.methods
        for rule in flask_app.url_map.iter_rules()
    )
    # The step that stocks the library is the one that reports the trial's output.
    outputs = {key: payload["actual_outputs"] for key, (_, payload) in zip(wm.TRIAL_STEP_KEYS, client.posts)}
    assert outputs["library_stock"] == [{"name": "Library stock", "quantity": "50", "unit": "mL"}]
    assert all(out == [] for key, out in outputs.items() if key != "library_stock")


# --- 5. a customs lodgement is a Compliant record --------------------------------------


class _CustomsStore:
    """MarkerStore answers for a customs lodgement that has not been loaded yet."""

    def existing_compliance_record(self, marker):
        return False

    def compliant_profile_enabled(self):
        return True

    def most_recently_created_execution_id(self):
        return None


def test_the_replays_customs_lodgement_payload_is_accepted_by_the_compliant_records_route(db, replay_env):
    user = db.get(User, replay_env["user_id"])
    org_id = user.org_id
    # Every Compliant route is gated on an active per-org subscription, and records are refused
    # until Compliance is configured -- the same enrolment `MarkerStore.compliant_profile_enabled`
    # reads before the replay attempts a lodgement.
    FeatureSubscriptionRepository(db).grant(org_id, "compliant")
    db.add(
        ComplianceProfile(
            org_id=org_id,
            enabled=True,
            industry_module="nz_alcohol",
            settings={"alcohol_product_types": ["spirits"]},
        )
    )
    db.commit()
    replay_env["replay_client"].login(replay_env["email"], DEFAULT_TEST_PASSWORD)

    row = {
        "id": 7,
        "date": date(2025, 3, 14),
        "date_period": "2025-03",
        "lal": Decimal("12.5"),
        "lodged_volume": Decimal("30"),
        "lodged_abv": Decimal("41.5"),
        "bottles": Decimal("60"),
    }
    event = timeline.ReplayEvent(
        event_id="customs:7",
        event_type="create_customs_lodgement",
        real_date=row["date"],
        depends_on=(),
        payload={"row": row},
    )
    try:
        # The real executor and the real ReplayClient: a payload the route refuses raises
        # ReplayRejectedError with the route's own message, failing this test with the reason.
        assert replay.DISPATCH[event.event_type](replay_env["replay_client"], _CustomsStore(), event) is True

        records = db.query(ComplianceRecord).filter(ComplianceRecord.org_id == org_id).all()
        assert len(records) == 1
        record = records[0]
        assert record.framework_slug == "customs-alcohol"
        assert record.control_id == "period-lodgement"
        assert record.record_type == "lodgement"
        assert record.status == "complete"
        assert record.period_start == record.period_end == row["date"]
        assert record.details["import_ref"] == "customs-7"
    finally:
        db.rollback()
        db.query(ComplianceRecord).filter(ComplianceRecord.org_id == org_id).delete(synchronize_session=False)
        db.query(ComplianceProfile).filter(ComplianceProfile.org_id == org_id).delete(synchronize_session=False)
        db.commit()
