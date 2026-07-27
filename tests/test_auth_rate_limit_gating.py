"""The auth rate-limit relaxation gate must fail closed outside local/test.

`auth_routes.USE_RELAXED_AUTH_RATE_LIMITS` raises the signup/login limit from 5/minute to
1000/minute so the test suite can run. It keys off ambient CI variables, which are
operator-fallible: a build container that also serves traffic, or a stray `export CI=true`
in a deploy script, would under a naive `if CI: relax` disable brute-force protection in
production silently -- no error, no failing test, no log line.

Escalated by the auth security audit as a deployment-config risk
(.agents/reports/auth/review.md). These tests pin the gate's contract so a future edit
cannot quietly widen it: relaxation requires ENVIRONMENT to be explicitly local or test,
and nothing else -- not production, not unset-with-CI-set, not a typo -- can turn it on.

The flag is evaluated at import time, so each case re-imports the module under a patched
environment rather than trying to mutate an already-computed constant.
"""

import importlib
import os
from unittest.mock import patch

import pytest


def _relaxed_under(env: dict[str, str]) -> bool:
    """Import auth_routes with exactly `env` for the relevant vars, return the flag."""
    cleared = {"ENVIRONMENT": "", "CI": "", "GITLAB_CI": ""}
    with patch.dict(os.environ, {**cleared, **env}, clear=False):
        for key, value in {**cleared, **env}.items():
            if value == "":
                os.environ.pop(key, None)
        module = importlib.import_module("app.api.routes.auth_routes")
        return importlib.reload(module).USE_RELAXED_AUTH_RATE_LIMITS


@pytest.fixture(autouse=True)
def _restore_module():
    """Leave the imported module matching the real environment for other tests."""
    yield
    importlib.reload(importlib.import_module("app.api.routes.auth_routes"))


# --- must NOT relax -------------------------------------------------------------------


@pytest.mark.parametrize(
    "env",
    [
        pytest.param({"ENVIRONMENT": "production"}, id="production-alone"),
        pytest.param({"ENVIRONMENT": "production", "CI": "true"}, id="production-with-CI"),
        pytest.param({"ENVIRONMENT": "production", "GITLAB_CI": "true"}, id="production-with-GITLAB_CI"),
        pytest.param(
            {"ENVIRONMENT": "production", "CI": "true", "GITLAB_CI": "true"},
            id="production-with-both",
        ),
        pytest.param({"ENVIRONMENT": "PRODUCTION", "CI": "true"}, id="production-uppercase"),
        pytest.param({"ENVIRONMENT": "staging", "CI": "true"}, id="unknown-env-fails-closed"),
        pytest.param({"ENVIRONMENT": "prod", "CI": "true"}, id="typo-env-fails-closed"),
    ],
)
def test_rate_limits_are_not_relaxed(env):
    """No combination of CI markers may relax limits outside the allowlisted envs.

    `production-with-CI` is the exact regression this guards: it passed under the old
    denylist-free `CI or GITLAB_CI or ENVIRONMENT==test` logic.
    """
    assert _relaxed_under(env) is False


# --- must relax (the suite depends on it) ---------------------------------------------


@pytest.mark.parametrize(
    "env",
    [
        pytest.param({"ENVIRONMENT": "test"}, id="test-env"),
        pytest.param({"ENVIRONMENT": "local", "CI": "true"}, id="local-in-CI"),
        pytest.param({"CI": "true"}, id="unset-env-defaults-local-in-CI"),
        pytest.param({"ENVIRONMENT": "local", "GITLAB_CI": "true"}, id="local-in-gitlab-CI"),
    ],
)
def test_rate_limits_are_relaxed(env):
    assert _relaxed_under(env) is True


def test_local_without_ci_markers_keeps_strict_limits():
    """Plain local dev is not CI: it should get the real 5/minute limit, so a developer
    exercises the same protection production does."""
    assert _relaxed_under({"ENVIRONMENT": "local"}) is False
