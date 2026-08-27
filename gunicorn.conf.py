"""Gunicorn config for the test and production Docker images.

Mirrors app.cli.api.start()'s dynamic host/port/SSL resolution (same config
loader, same ENVIRONMENT-driven .ini file) so gunicorn binds to exactly what
the app itself would have bound to via app.run() -- 0.0.0.0:8001 for test,
0.0.0.0:8000 for production, both with the same self-signed TLS cert.

Not used for local host-based dev (`uv run workflow start` / `python
app/app.py`) -- those keep Werkzeug's dev server for its live reloader.
Docker's test/production images use this instead.
"""

from pathlib import Path

from app.utils.config_loader import config as app_config

_app_dir = Path(__file__).parent / "app"
_cert_file = _app_dir / "tls" / "app_cert.pem"
_key_file = _app_dir / "tls" / "app_cert.key"

bind = f"{app_config.host}:{app_config.port}"

if _cert_file.exists() and _key_file.exists():
    certfile = str(_cert_file)
    keyfile = str(_key_file)

# gthread, not plain sync: this app is I/O-bound (waiting on Postgres), and the
# SPA fires several /api/core/* calls in parallel on page load -- see the
# "core: run Werkzeug dev server threaded" commit for the measured effect of
# single-threaded/single-worker request queuing on page load time. Workers give
# process-level fault isolation (one crashed worker doesn't take the others
# down); threads within each worker give the concurrency those parallel calls
# need. Values are a conservative starting point for a small self-hosted box,
# not a capacity-tested ceiling.
worker_class = "gthread"
workers = 2
threads = 4
timeout = 60

# Do not preload the app: gunicorn's --preload imports the app once in the
# master process and forks workers from it, which would fork this app's
# SQLAlchemy engine/connection pool across worker processes -- corrupted
# shared connections. Default (no preload) has each worker import the app
# fresh after fork, giving each its own engine/pool. Never change this
# without also adding a post_fork engine.dispose()-and-recreate hook.
preload_app = False

# The app's own structlog-based access middleware (app.observability.access)
# already logs every request in JSON; gunicorn's separate access log would
# just duplicate that in a different format. Errors (worker crashes, boot
# failures) still go to stdout so `docker logs` captures them.
accesslog = None
errorlog = "-"
