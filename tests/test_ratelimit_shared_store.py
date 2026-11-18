"""Design review S4: rate limits must be shared by every gunicorn worker.

gunicorn runs two workers in the test and production images, and the limiter kept its counts in
process memory unless ``[ratelimit] storage_uri`` was set (the templates left it commented out). So
every limit was really twice as loose: 120 bearer requests a minute per grant became 240, and the
sign-in brute-force limits doubled too. The fix points the limiter at Valkey (``valkey-test`` /
``valkey-prod``), built from ``[ratelimit] host/port/db`` and the ``VALKEY_PASSWORD`` secret.

"Two workers" is modelled the only way it can be in one process: two limiters that share nothing
but the store, exactly what two forked workers share.
"""

from __future__ import annotations

import configparser
import socket
import uuid
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from flask import Flask, jsonify
from flask_limiter import Limiter

from app.utils.config_loader import Config
from tests.valkey_support import valkey_uri  # noqa: F401  (fixture)

ROOT = Path(__file__).resolve().parents[1]


def _config(environment: str, ratelimit: dict[str, str] | None = None) -> Config:
    """The real Config class over a tracked ini, without the KeePassXC lookups its constructor does."""
    cfg = Config.__new__(Config)
    cfg.config = configparser.ConfigParser()
    cfg.config.read(ROOT / "app" / "config" / f"{environment}.ini")
    cfg.environment = environment
    if ratelimit is not None:
        if cfg.config.has_section("ratelimit"):
            cfg.config.remove_section("ratelimit")
        cfg.config.add_section("ratelimit")
        for key, value in ratelimit.items():
            cfg.config.set("ratelimit", key, value)
    return cfg


def _config_for_store(uri: str, monkeypatch) -> Config:
    """A config whose [ratelimit] section names the Valkey at ``uri`` the way test.ini/prod.ini do."""
    parts = urlsplit(uri)
    assert parts.password, "the deployed stores always have a password; so does every test store"
    monkeypatch.setenv("VALKEY_PASSWORD", parts.password)
    monkeypatch.setattr(Config, "_valkey_keepass_password", lambda self: "", raising=False)
    return _config("local", {"host": parts.hostname, "port": str(parts.port), "db": parts.path.lstrip("/") or "0"})


# --- the deployed configs -----------------------------------------------------------------------


@pytest.mark.parametrize("environment,host", [("test", "valkey-test"), ("prod", "valkey-prod")])
def test_s4_the_deployed_configs_point_the_limiter_at_their_own_valkey(monkeypatch, environment, host):
    from app.api.ratelimit_store import storage_uri

    monkeypatch.setenv("VALKEY_PASSWORD", "p@ss/w:rd")
    assert storage_uri(_config(environment)) == f"redis://:p%40ss%2Fw%3Ard@{host}:6379/0"


@pytest.mark.parametrize("environment", ["test", "prod"])
def test_s4_without_the_password_there_is_no_shared_store(monkeypatch, environment):
    from app.api.ratelimit_store import storage_uri

    monkeypatch.delenv("VALKEY_PASSWORD", raising=False)
    monkeypatch.setattr(Config, "_valkey_keepass_password", lambda self: "", raising=False)
    assert storage_uri(_config(environment)) is None


def test_s4_local_dev_needs_no_store(monkeypatch):
    from app.api.ratelimit_store import shared_store_problem, storage_uri

    monkeypatch.delenv("WEB_CONCURRENCY", raising=False)
    cfg = _config("local", {})
    assert storage_uri(cfg) is None
    assert shared_store_problem(cfg) is None, "one Werkzeug process: memory is shared by definition"


def test_s4_two_workers_and_no_store_is_a_problem(monkeypatch):
    from app.api.ratelimit_store import shared_store_problem

    monkeypatch.setenv("WEB_CONCURRENCY", "2")
    problem = shared_store_problem(_config("local", {}))
    assert problem and "2 workers" in problem and "Valkey" in problem


def test_s4_an_explicit_storage_uri_still_wins(monkeypatch):
    from app.api.ratelimit_store import shared_store_problem, storage_uri

    monkeypatch.setenv("WEB_CONCURRENCY", "2")
    cfg = _config("local", {"storage_uri": "redis://elsewhere:6379/3", "host": "ignored"})
    assert storage_uri(cfg) == "redis://elsewhere:6379/3"
    assert shared_store_problem(cfg) is None


def test_s4_the_images_tell_the_app_how_many_workers_gunicorn_runs():
    """The app (and `docker exec ... workflow mcp enable`) reads WEB_CONCURRENCY; the images must set it."""
    dockerfile = (ROOT / "Dockerfile.multi").read_text()
    for stage in ("AS test", "AS production"):
        body = dockerfile.split(stage, 1)[1].split("\nFROM ", 1)[0]
        assert "ENV WEB_CONCURRENCY=2" in body, stage
    assert 'os.environ.setdefault("WEB_CONCURRENCY"' in (ROOT / "gunicorn.conf.py").read_text()


# --- two workers, one budget -------------------------------------------------------------------


def _worker(cfg: Config) -> Flask:
    """One gunicorn worker's worth of limiter: its own Limiter object, its own process memory."""
    from app.api.ratelimit_store import configure_ratelimit

    app = Flask(f"worker-{uuid.uuid4().hex[:6]}")
    limiter = Limiter(key_func=lambda: app.config["CALLER"])
    app.config["CALLER"] = "unset"

    def login():  # a stand-in for /auth/login: one limited view, nothing else
        return jsonify({"ok": True})

    app.add_url_rule("/auth/login", "login", limiter.limit("3 per minute")(login), methods=["POST"])

    configure_ratelimit(app, limiter, cfg)
    return app


def _alternate(apps, caller, n):
    codes = []
    for i in range(n):
        app = apps[i % len(apps)]
        app.config["CALLER"] = caller
        codes.append(app.test_client().post("/auth/login").status_code)
    return codes


def test_s4_with_no_store_each_worker_counts_alone_so_the_limit_doubles(monkeypatch):
    """The finding itself: two workers, memory storage, 3/min is really 6/min."""
    monkeypatch.delenv("WEB_CONCURRENCY", raising=False)
    apps = [_worker(_config("local", {})), _worker(_config("local", {}))]
    assert _alternate(apps, f"caller-{uuid.uuid4()}", 6) == [200] * 6


def test_s4_with_valkey_two_workers_share_one_sign_in_budget(valkey_uri, monkeypatch):  # noqa: F811
    cfg = _config_for_store(valkey_uri, monkeypatch)
    apps = [_worker(cfg), _worker(cfg)]
    assert _alternate(apps, f"caller-{uuid.uuid4()}", 6) == [200, 200, 200, 429, 429, 429]


def _closed_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_s4_an_unreachable_store_fails_closed_with_a_503(monkeypatch):
    """ASSUMPTION: no in-memory fallback and no swallowed errors. A store outage refuses sign-in
    attempts (503, try again) rather than quietly reverting to per-worker buckets."""
    monkeypatch.setenv("VALKEY_PASSWORD", "irrelevant")
    cfg = _config("local", {"host": "127.0.0.1", "port": str(_closed_port()), "db": "0"})
    app = _worker(cfg)
    resp = app.test_client().post("/auth/login")
    assert resp.status_code == 503
    assert resp.headers.get("Retry-After")
    assert "irrelevant" not in resp.get_data(as_text=True)


# --- the MCP per-grant limit -------------------------------------------------------------------


def _hit_from_two_workers(uri: str, grant_id) -> list[int | None]:
    from app.features.mcp_oauth.services import rate_limit

    app = Flask("bearer")
    app.config["RATELIMIT_STORAGE_URI"] = uri
    results = []
    with app.app_context():
        rate_limit._state.clear()
        for _ in range(rate_limit.BEARER_REQUESTS_PER_MINUTE):
            results.append(rate_limit.hit_bearer(grant_id))
        rate_limit._state.clear()  # the second worker: a process with its own memory
        results.append(rate_limit.hit_bearer(grant_id))
        rate_limit._state.clear()
    return results


def test_s4_with_no_store_the_121st_bearer_request_gets_through_on_another_worker():
    results = _hit_from_two_workers("memory://", uuid.uuid4())
    assert results[-1] is None, "documents the bug: a fresh worker has a fresh bucket"


def test_s4_with_valkey_the_121st_bearer_request_is_refused_on_any_worker(valkey_uri):  # noqa: F811
    results = _hit_from_two_workers(valkey_uri, uuid.uuid4())
    assert results[:-1] == [None] * (len(results) - 1)
    assert isinstance(results[-1], int) and results[-1] >= 1


def test_s4_a_store_uri_with_its_password_never_reaches_a_log():
    from app.observability.logging_config import scrub_text

    line = "connecting to redis://:Sup3r-s3cret@valkey-prod:6379/0 failed"
    assert "Sup3r-s3cret" not in scrub_text(line)
    assert "valkey-prod:6379" in scrub_text(line)
