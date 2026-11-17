"""A real Valkey for the shared rate-limit tests (design review S4).

``VALKEY_TEST_URI`` names one, with its password in ``VALKEY_TEST_PASSWORD`` (CI runs a ``valkey/valkey``
service and sets both; the deployed stores always have a password, so the tests use one too). Without it, and with
Docker available, a throwaway container is started on a random loopback port and removed afterwards.
With neither the tests skip and say why: an absent service is a skip, never a failure.

Several test processes may share one Valkey (xdist workers, CI), so tests never flush it: every test
uses keys of its own (a fresh grant id, a fresh client address).
"""

from __future__ import annotations

import os
import secrets
import shutil
import subprocess
import time
import uuid
from urllib.parse import quote, urlsplit

import pytest

# The image scripts/run_valkey.sh deploys; tests/test_run_valkey.py pins that the two agree.
VALKEY_IMAGE = "valkey/valkey:9.1.3"


def _ping(uri: str) -> bool:
    import redis

    try:
        return bool(redis.Redis.from_url(uri, socket_connect_timeout=1, socket_timeout=1).ping())
    except redis.RedisError:
        return False


@pytest.fixture(scope="session")
def valkey_uri():
    given = os.getenv("VALKEY_TEST_URI")
    if given and os.getenv("VALKEY_TEST_PASSWORD"):
        parts = urlsplit(given)
        given = f"redis://:{quote(os.environ['VALKEY_TEST_PASSWORD'], safe='')}@{parts.hostname}:{parts.port or 6379}{parts.path}"
    if given:
        if not _ping(given):
            pytest.fail(f"VALKEY_TEST_URI is set but no Valkey answers there (host {given.rsplit('@', 1)[-1]})")
        yield given
        return
    if not shutil.which("docker"):
        pytest.skip("no Valkey: set VALKEY_TEST_URI or install Docker")
    password = secrets.token_urlsafe(16)
    name = f"valkey-pytest-{uuid.uuid4().hex[:10]}"
    started = subprocess.run(
        [
            "docker",
            "run",
            "-d",
            "--rm",
            "--name",
            name,
            "-p",
            "127.0.0.1::6379",
            "-e",
            "REDISCLI_AUTH",
            VALKEY_IMAGE,
            "sh",
            "-c",
            'printf "requirepass %s\\n" "$REDISCLI_AUTH" | exec valkey-server -',  # password never in argv
        ],
        env={**os.environ, "REDISCLI_AUTH": password},
        capture_output=True,
        text=True,
        check=False,
    )
    if started.returncode != 0:
        pytest.skip(f"no Valkey: could not start {VALKEY_IMAGE} ({started.stderr.strip()[:200]})")
    try:
        port = (
            subprocess.run(["docker", "port", name, "6379/tcp"], capture_output=True, text=True, check=True)
            .stdout.split(":")[-1]
            .strip()
        )
        uri = f"redis://:{password}@127.0.0.1:{port}/0"
        for _ in range(50):
            if _ping(uri):
                break
            time.sleep(0.1)
        else:
            pytest.skip("no Valkey: the throwaway container never answered")
        yield uri
    finally:
        subprocess.run(["docker", "rm", "-f", name], capture_output=True, check=False)
