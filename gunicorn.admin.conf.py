"""Gunicorn config for the admin site image (Dockerfile.multi target `admin`).

Same self-signed TLS certificate as the customer app, so the tunnel in front treats both
alike. One worker: the admin site has a handful of users, and a single process keeps the
sign-in rate limits (held in memory) exactly as configured.
"""

import os
from pathlib import Path

_app_dir = Path(__file__).parent / "app"
_cert_file = _app_dir / "tls" / "app_cert.pem"
_key_file = _app_dir / "tls" / "app_cert.key"

bind = f"0.0.0.0:{os.getenv('ADMIN_PORT', '8020')}"

if _cert_file.exists() and _key_file.exists():
    certfile = str(_cert_file)
    keyfile = str(_key_file)

worker_class = "gthread"
workers = 1
threads = int(os.getenv("GUNICORN_THREADS", "8"))
timeout = int(os.getenv("GUNICORN_TIMEOUT", "60"))
preload_app = False
accesslog = None
errorlog = "-"
