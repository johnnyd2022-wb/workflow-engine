"""Shared pytest fixtures.

Before this file, every test that needed a DB session or an isolated org/user pair
redefined its own local `db` fixture and hand-rolled the setup/teardown (see
.agents/conventions.md §6). This is the single source going forward; owned by the
test-fixtures skill. Existing per-file `db` fixtures still work (a local fixture shadows
this one), so nothing already passing needed to change.

This file also owns the live-server gate (see the `live_server` marker below), which is
owned by the suite-warden skill.
"""

import socket

import pytest

from app.core.db import db_session
from app.core.db.models.organisation import Organisation
from app.core.db.models.user import User
from tests.factories import OrganisationFactory, UserFactory

# --------------------------------------------------------------------------------------
# live-server gate (owned by suite-warden)
#
# Some suites drive a real dev server over HTTPS with `requests` instead of exercising
# the app in-process. Without a server they fail with ConnectionRefusedError — a red
# suite that says nothing about the code. That trained everyone to read "30 failed" as
# noise, which is exactly how a real regression gets waved through.
#
# Mark those suites with `pytest.mark.live_server`; they run when a server is listening
# and skip with a stated reason when it isn't. Green then means green.
# --------------------------------------------------------------------------------------

LIVE_SERVER_HOST = "localhost"
LIVE_SERVER_FALLBACK_PORT = 8005


def _live_server_port() -> int:
    """Port the dev server binds, from the active config (falls back to local's 8005)."""
    try:
        from app.utils.config_loader import config

        return int(config.port)
    except Exception:
        return LIVE_SERVER_FALLBACK_PORT


def _live_server_available(host: str, port: int, timeout: float = 1.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Skip `live_server` tests when no dev server is listening.

    Probed once per session, not per test: 30 probes of a refused port is 30 timeouts.
    """
    if not any(item.get_closest_marker("live_server") for item in items):
        return

    port = _live_server_port()
    available = _live_server_available(LIVE_SERVER_HOST, port)
    if available:
        return

    skip = pytest.mark.skip(
        reason=(
            f"no dev app server listening on https://{LIVE_SERVER_HOST}:{port} — "
            "start it (uv run workflow start) to run live-server suites"
        )
    )
    for item in items:
        if item.get_closest_marker("live_server"):
            item.add_marker(skip)


@pytest.fixture
def db():
    """Per-test DB session, closed and removed after the test regardless of outcome."""
    session = db_session()
    try:
        yield session
    finally:
        session.close()
        db_session.remove()


@pytest.fixture
def two_org_two_user(db):
    """The seeded two-org/two-user world that tenant-isolation tests need: a hostile
    neighbor org must exist to prove a query can't see across it. security-audit's
    isolation checks and e2e-playwright's cross-tenant probe both assume this shape —
    use this fixture rather than reseeding it per test file.
    """
    org_a = OrganisationFactory()
    org_b = OrganisationFactory()
    user_a = UserFactory(org_id=org_a.id)
    user_b = UserFactory(org_id=org_b.id)
    db.commit()

    yield {"org_a": org_a, "org_b": org_b, "user_a": user_a, "user_b": user_b}

    db.query(User).filter(User.org_id.in_([org_a.id, org_b.id])).delete(synchronize_session=False)
    db.query(Organisation).filter(Organisation.id.in_([org_a.id, org_b.id])).delete(synchronize_session=False)
    db.commit()
