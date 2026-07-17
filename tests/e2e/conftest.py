"""E2E fixtures: a real browser against a real app over real TLS.

Owned by the e2e-playwright skill; spec at .agents/specs/playwright-e2e.md.

Design decisions worth not re-deriving (spec D1-D5):

- **ENVIRONMENT stays unset** (-> local.ini, test DB on :8401). `ENVIRONMENT=test` points
  at `host.docker.internal`, which only resolves inside Docker, so it hangs from a host
  shell. Playwright needs a host-reachable URL, so local is the only workable env. Set
  ENVIRONMENT=test and this suite skips rather than hanging (D1).
- **The app under test is `app.app:app`, NOT a bare `create_app()`.** `app/app.py:24`
  calls `create_app()` and then registers `/`, `/dashboard`, `/landing-diagram`,
  `/healthcheck` and `/initialize` on that instance. `create_app()` alone returns a
  blueprint-only app with no landing page, so the login modal the browser needs simply
  isn't there and every navigation 404s.
- **Real TLS, not HTTP.** `SESSION_COOKIE_SECURE` defaults True and HSTS is only set on
  secure requests (app_factory.py:51,337), so an HTTP boot would break auth and make the
  cookie/HSTS security assertions untestable. We serve the same self-signed cert app.py
  uses and tell the browser to ignore it. This is the production shape.
- **Absent dependency is a skip with a reason, never a failure** (D4, suite-warden's rule
  — same shape as the `live_server` gate in tests/conftest.py).
- Rate limits are NOT relaxed here. `USE_RELAXED_AUTH_RATE_LIMITS` is only on when
  CI/GITLAB_CI/ENVIRONMENT=test (auth_routes.py:72), none of which apply locally. That is
  deliberate: the limiter keys on `ip:email` (auth_routes.py:get_rate_limit_key), so
  tests using distinct factory-sequenced emails get their own bucket and never collide.
  Tests that exhaust a bucket on purpose are testing the limiter, which is a real
  security control worth exercising rather than switching off.
"""

from __future__ import annotations

import os
import re
import socket
import ssl
import threading
import time
import uuid
from pathlib import Path

import pytest
from playwright.sync_api import expect

REPO_ROOT = Path(__file__).resolve().parents[2]
CERT_FILE = REPO_ROOT / "app" / "tls" / "app_cert.pem"
KEY_FILE = REPO_ROOT / "app" / "tls" / "app_cert.key"

BIND_HOST = "127.0.0.1"
BOOT_TIMEOUT = 20.0


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind((BIND_HOST, 0))
        return int(sock.getsockname()[1])


def _tcp_open(host: str, port: int, timeout: float = 1.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _chromium_available() -> tuple[bool, str]:
    """Filesystem check only.

    Deliberately does NOT call `sync_playwright()`: pytest-playwright runs its own event
    loop, and opening a second sync context from a fixture raises "Sync API inside the
    asyncio loop" depending on which test ran first — an order-dependent skip, i.e. a
    flake. Looking for the browser on disk is decidable without starting anything.
    """
    try:
        import playwright  # noqa: F401
    except ImportError:
        return False, "playwright is not installed — run `uv sync --extra dev`"

    browsers_path = os.getenv("PLAYWRIGHT_BROWSERS_PATH")
    root = Path(browsers_path) if browsers_path else Path.home() / ".cache" / "ms-playwright"
    if not root.exists() or not any(root.glob("chromium-*")):
        return False, (f"chromium is not installed under {root} — run `uv run playwright install chromium`")
    return True, ""


@pytest.fixture(scope="session")
def e2e_preconditions() -> None:
    """Skip the whole suite with a stated reason when a dependency is absent (D4)."""
    env = os.getenv("ENVIRONMENT", "").lower()
    if env == "test":
        pytest.skip(
            "ENVIRONMENT=test targets host.docker.internal and hangs from a host shell; "
            "run E2E with ENVIRONMENT unset so it resolves to local (spec D1)"
        )

    ok, reason = _chromium_available()
    if not ok:
        pytest.skip(reason)

    if not (CERT_FILE.exists() and KEY_FILE.exists()):
        pytest.skip(f"TLS cert/key missing at {CERT_FILE.parent} — E2E serves the app over HTTPS")

    from app.utils.config_loader import config

    db_host = config.get("database", "host")
    db_port = int(config.get("database", "port"))
    if not _tcp_open(db_host, db_port):
        pytest.skip(
            f"test database is not listening on {db_host}:{db_port} — "
            "start it with `docker-compose -f docker-compose.test.yml up -d`"
        )


@pytest.fixture(scope="session")
def app_url(e2e_preconditions) -> str:
    """Boot the real app on an ephemeral port over TLS, once per session."""
    from werkzeug.serving import make_server

    # The composed app, not app_factory.create_app() — see the module docstring.
    from app.app import app

    ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ssl_context.load_cert_chain(str(CERT_FILE), str(KEY_FILE))

    port = _free_port()
    server = make_server(BIND_HOST, port, app, threaded=True, ssl_context=ssl_context)
    thread = threading.Thread(target=server.serve_forever, daemon=True, name="e2e-app-server")
    thread.start()

    url = f"https://{BIND_HOST}:{port}"
    deadline = time.monotonic() + BOOT_TIMEOUT
    while time.monotonic() < deadline:
        if _tcp_open(BIND_HOST, port):
            break
        time.sleep(0.05)
    else:  # pragma: no cover - defensive
        server.shutdown()
        pytest.fail(f"E2E app server did not come up on {url} within {BOOT_TIMEOUT}s")

    try:
        yield url
    finally:
        server.shutdown()
        thread.join(timeout=5)


@pytest.fixture(scope="session")
def browser_context_args(browser_context_args, app_url):
    """Trust the self-signed cert and default navigation to the app."""
    return {
        **browser_context_args,
        "base_url": app_url,
        "ignore_https_errors": True,
    }


@pytest.fixture(scope="session")
def e2e_user(app_url) -> dict:
    """A committed org+user the browser can genuinely log in as.

    Session-scoped: `logged_in_page` authenticates once and reuses storage state, so the
    suite does not re-click login 40 times (and does not walk into the login limiter).

    Names carry a per-run uuid rather than relying on `factory.Sequence`, which restarts
    at 0 in every process: a crashed run leaves "Test Org 0" behind and every subsequent
    run then dies on a unique-constraint violation before a single test executes.
    """
    from app.core.db import db_session
    from app.core.db.models.organisation import Organisation
    from app.core.db.models.user import User
    from tests.factories import DEFAULT_TEST_PASSWORD, OrganisationFactory, UserFactory

    run_id = uuid.uuid4().hex[:8]
    session = db_session()
    org = OrganisationFactory(name=f"E2E Org {run_id}")
    user = UserFactory(org_id=org.id, email=f"e2e-{run_id}@example.test")
    session.commit()

    record = {
        "email": user.email,
        "password": DEFAULT_TEST_PASSWORD,
        "org_id": str(org.id),
        "org_name": org.name,
        "user_id": str(user.id),
    }

    org_id, user_id = org.id, user.id
    try:
        yield record
    finally:
        session.rollback()
        purge_org(session, org_id, user_id)
        session.query(User).filter(User.id == user_id).delete(synchronize_session=False)
        session.query(Organisation).filter(Organisation.id == org_id).delete(synchronize_session=False)
        session.commit()
        db_session.remove()


def purge_org(session, org_id, user_id) -> None:
    """Delete everything this run's org/user touched, in FK-safe order.

    Derived from `Base.metadata.sorted_tables` rather than a hand-written table list:
    logging in alone writes an `audit_logs` row referencing the user, so a naive
    `DELETE FROM users` dies on a foreign key — and any test that creates a process,
    execution, or inventory row adds another table to that list. Walking the schema in
    reverse dependency order means a new model is covered the day it is added, instead of
    breaking this teardown and getting "fixed" by someone deleting the cleanup.
    """
    from sqlalchemy import or_

    from app.core.db.models.models import Base

    for table in reversed(Base.metadata.sorted_tables):
        if table.name in ("organisations", "users"):
            continue
        conditions = []
        if "org_id" in table.c:
            conditions.append(table.c.org_id == org_id)
        if "user_id" in table.c:
            conditions.append(table.c.user_id == user_id)
        if conditions:
            session.execute(table.delete().where(or_(*conditions)))
    session.commit()


@pytest.fixture()
def fresh_user(app_url):
    """Mint throwaway users that a test may mutate freely.

    `e2e_user` is session-scoped and backs the shared login state, so a test that enables
    2FA or rotates its password on that user silently breaks every later test. Anything
    destructive takes one of these instead. Distinct emails also keep each test in its own
    `ip:email` rate-limit bucket.
    """
    from app.core.db import db_session
    from app.core.db.models.organisation import Organisation
    from app.core.db.models.user import User
    from tests.factories import DEFAULT_TEST_PASSWORD, OrganisationFactory, UserFactory

    session = db_session()
    created: list[tuple] = []

    def _make() -> dict:
        run_id = uuid.uuid4().hex[:8]
        org = OrganisationFactory(name=f"E2E Fresh Org {run_id}")
        user = UserFactory(org_id=org.id, email=f"e2e-fresh-{run_id}@example.test")
        session.commit()
        created.append((org.id, user.id))
        return {"email": user.email, "password": DEFAULT_TEST_PASSWORD, "org_id": str(org.id)}

    yield _make

    session.rollback()
    for org_id, user_id in created:
        purge_org(session, org_id, user_id)
        session.query(User).filter(User.id == user_id).delete(synchronize_session=False)
        session.query(Organisation).filter(Organisation.id == org_id).delete(synchronize_session=False)
    session.commit()


@pytest.fixture()
def purge_after(app_url):
    """Clean up rows a test created through the app itself (e.g. signup), by email.

    Registered before the action, not after, so the cleanup still runs when the assertion
    in between fails — otherwise a failing signup test poisons the next run.
    """
    from app.core.db import db_session
    from app.core.db.models.organisation import Organisation
    from app.core.db.models.user import User

    session = db_session()
    emails: list[str] = []

    yield emails.append

    session.rollback()
    for email in emails:
        user = session.query(User).filter(User.email == email.lower()).one_or_none()
        if user is None:
            continue
        org_id = user.org_id
        purge_org(session, org_id, user.id)
        session.query(User).filter(User.id == user.id).delete(synchronize_session=False)
        session.query(Organisation).filter(Organisation.id == org_id).delete(synchronize_session=False)
    session.commit()


def login_through_ui(page, email: str, password: str) -> None:
    """Authenticate the way a user does: the landing page's Sign In modal.

    Not a session-cookie shortcut — the point of E2E is that the real flow works.

    No sleep here: `openModal`'s deferred reset now re-asserts display state only and
    leaves field values alone, so filling immediately is safe. The `to_have_value`
    assertions below prove that rather than assume it — if someone reintroduces a
    value-clearing timer, this fails instead of flaking.
    """
    page.goto("/")
    page.get_by_role("button", name="Sign In").first.click()

    email_input = page.locator("#login-email")
    password_input = page.locator("#login-password")
    expect(email_input).to_be_visible()

    email_input.fill(email)
    password_input.fill(password)
    expect(email_input).to_have_value(email)
    expect(password_input).to_have_value(password)

    page.locator("#login-submit-btn").click()
    page.wait_for_url(re.compile(r"/(core/)?dashboard"), timeout=15_000)


@pytest.fixture(scope="session")
def storage_state_path(tmp_path_factory, browser, e2e_user, app_url) -> str:
    """Log in once per session; every test reuses the resulting cookie state."""
    context = browser.new_context(base_url=app_url, ignore_https_errors=True)
    page = context.new_page()
    login_through_ui(page, e2e_user["email"], e2e_user["password"])
    path = tmp_path_factory.mktemp("e2e-auth") / "state.json"
    context.storage_state(path=str(path))
    context.close()
    return str(path)


@pytest.fixture()
def logged_in_page(browser, storage_state_path, app_url):
    """A page already authenticated as `e2e_user`, with a clean-page probe attached."""
    context = browser.new_context(
        base_url=app_url,
        ignore_https_errors=True,
        storage_state=storage_state_path,
    )
    page = context.new_page()
    attach_probe(page)
    try:
        yield page
    finally:
        context.close()


# ------------------------------------------------------------------------------------
# Deterministic page checks (spec D2, blocking tier)
#
# These are the checks that are allowed to stop a push: they are true or false, with no
# judgement in the middle. Heuristic checks (visual diff, agent screenshot review, tight
# perf budgets) belong in the advisory tier and must never gate — a flaky gate gets
# disabled within a month and then protects nothing.
# ------------------------------------------------------------------------------------


class PageProbe:
    """Collects the signals a broken page emits, for `assert_clean_page`."""

    def __init__(self) -> None:
        self.console_errors: list[str] = []
        self.failed_requests: list[str] = []
        self.server_errors: list[str] = []

    # Chromium logs every non-2xx fetch as a console error ("Failed to load resource: the
    # server responded with a status of 401"). HTTP status is already tracked properly
    # below — 5xx blocks, 4xx doesn't, because a 401/404 is the *assertion* in unhappy-path
    # and cross-tenant tests. Counting it here too would mean any test that deliberately
    # exercises a rejection can never also assert the page is clean. Console errors are for
    # JavaScript faults; status codes have their own channel.
    _RESOURCE_STATUS_NOISE = re.compile(r"Failed to load resource: .*status of \d{3}")

    def _on_console(self, msg) -> None:
        if msg.type == "error" and not self._RESOURCE_STATUS_NOISE.search(msg.text):
            self.console_errors.append(msg.text)

    def _on_page_error(self, exc) -> None:
        self.console_errors.append(f"uncaught: {exc}")

    def _on_request_failed(self, request) -> None:
        failure = request.failure or "unknown failure"
        self.failed_requests.append(f"{request.method} {request.url} — {failure}")

    def _on_response(self, response) -> None:
        # 5xx only. A 4xx is a legitimate outcome in unhappy-path and cross-tenant tests
        # (a 404 is the assertion there), so it cannot be a blanket failure.
        if response.status >= 500:
            self.server_errors.append(f"{response.status} {response.request.method} {response.url}")


def attach_probe(page) -> PageProbe:
    probe = PageProbe()
    page.on("console", probe._on_console)
    page.on("pageerror", probe._on_page_error)
    page.on("requestfailed", probe._on_request_failed)
    page.on("response", probe._on_response)
    page.probe = probe  # type: ignore[attr-defined]
    return probe


def assert_clean_page(page) -> None:
    """Assert the page is not visibly or silently broken.

    Applied to every page-rendering test. Catches the class of bug that a flow assertion
    sails straight past: the row is there, the JS that renders it threw.
    """
    probe: PageProbe | None = getattr(page, "probe", None)
    if probe is None:  # pragma: no cover - defensive
        raise AssertionError("no probe attached to this page; use `logged_in_page` or attach_probe")

    problems: list[str] = []

    if probe.console_errors:
        problems.append("console errors:\n  - " + "\n  - ".join(probe.console_errors))
    if probe.failed_requests:
        problems.append("failed requests:\n  - " + "\n  - ".join(probe.failed_requests))
    if probe.server_errors:
        problems.append("5xx responses:\n  - " + "\n  - ".join(probe.server_errors))

    body_box = page.locator("body").bounding_box()
    if body_box is None or body_box["height"] < 1:
        problems.append("body rendered with zero height — CSS or template breakage")

    if problems:
        raise AssertionError(f"page not clean: {page.url}\n\n" + "\n\n".join(problems))
