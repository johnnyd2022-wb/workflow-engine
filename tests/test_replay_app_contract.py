"""What the API-replay framework assumes about the app it drives, pinned against the real app.

`scripts/whistlebird_replay.py` loads a tenant by logging in over HTTP and then issuing
~625 mutating calls from a single client. That only works while three properties of the
app hold. Each was an open question in docs/whistlebird-replay-plan.md until it was
answered from code (findings-index 5c84c42e and bd5d240a); these tests keep the answers
true, so a change that breaks the replay fails here rather than at request N of a run.

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

The CSRF and 2FA tests run the real `ReplayClient` code paths. Only its transport is
swapped: Flask's test client stands in for `requests.Session`, because `ReplayClient`
itself targets a live server.
"""

import sys
from pathlib import Path
from uuid import uuid4

import pytest

from app.api.app_factory import create_app
from app.core.db.models.organisation import Organisation
from app.core.db.models.user import User
from app.core.db.repositories.user_repo import UserRepository
from app.core.security.auth_service import AuthService
from tests.factories import DEFAULT_TEST_PASSWORD, OrganisationFactory

sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))
import whistlebird_replay as replay  # noqa: E402

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
