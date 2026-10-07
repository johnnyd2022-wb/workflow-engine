"""Admin-site settings, resolved once at startup and failing closed.

Everything comes from the `[admin_site]` section of the environment's ini file or from
the environment; nothing here has a development default that would be unsafe if it
reached production.
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass

# The people who may use the admin site. An ini file can replace the list
# (`[admin_site] allowed_emails`), but it can never be empty.
DEFAULT_ALLOWED_EMAILS = ("johnny@whistlebird.co.nz", "niko@whistlebird.co.nz")

SESSION_HOURS = 12  # sign in again at least this often
IDLE_MINUTES = 30  # and after this long without a request


@dataclass(frozen=True)
class AdminSettings:
    environment: str
    allowed_emails: frozenset[str]
    require_authoritative_email: bool
    secret_key: str
    google_client_id: str
    google_client_secret: str
    google_redirect_uri: str
    customer_app_url: str

    def permits(self, email: str | None) -> bool:
        return isinstance(email, str) and email.strip().lower() in self.allowed_emails


def parse_allowed_emails(raw: str | None) -> frozenset[str]:
    if raw is None or not raw.strip():
        return frozenset(DEFAULT_ALLOWED_EMAILS)
    emails = frozenset(part.strip().lower() for part in raw.split(",") if part.strip())
    if not emails or any(email.count("@") != 1 or not all(email.split("@")) for email in emails):
        raise RuntimeError("[admin_site] allowed_emails must be a comma-separated list of email addresses")
    return emails


def _secret_key(config) -> str:
    """The admin site never shares a session-signing key with the customer app."""
    value = (os.getenv("ADMIN_FLASK_SECRET_KEY") or "").strip()
    if not value and config.environment in {"local", "test"}:
        # Local and test have one provisioned key; derive a distinct one from it.
        value = hashlib.sha256(b"admin-site:" + config.session_secret_key.encode()).hexdigest()
    if len(value.encode()) < 32:
        raise RuntimeError("The admin site needs ADMIN_FLASK_SECRET_KEY: a random secret of at least 32 bytes.")
    if value == (os.getenv("FLASK_SECRET_KEY") or "").strip():
        raise RuntimeError("ADMIN_FLASK_SECRET_KEY must differ from the customer app's FLASK_SECRET_KEY.")
    return value


def load_settings(config) -> AdminSettings:
    def setting(key: str, fallback: str = "") -> str:
        return (os.getenv(f"ADMIN_{key.upper()}") or config.get("admin_site", key, fallback) or "").strip()

    return AdminSettings(
        environment=config.environment,
        allowed_emails=parse_allowed_emails(config.get("admin_site", "allowed_emails", None)),
        require_authoritative_email=config.getboolean("admin_site", "require_authoritative_email", True),
        secret_key=_secret_key(config),
        google_client_id=setting("google_client_id") or config.google_client_id,
        google_client_secret=setting("google_client_secret") or config.google_client_secret,
        google_redirect_uri=setting("google_redirect_uri", "https://admin.biz-e.app/auth/google/callback"),
        customer_app_url=setting("customer_app_url", "https://biz-e.app").rstrip("/"),
    )
