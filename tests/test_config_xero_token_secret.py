"""Xero OAuth tokens at rest must never be sealed under a key that is public source.

Findings-Index: 9e07b1a1 -- ``docs/production-bringup-checklist.md`` §3 ("``[app]`` has no
``secret_key``"). ``XeroOAuthService`` derived its Fernet key from ``[app] secret_key``, which
no ini file sets, so every environment -- production included -- silently fell back to the
string ``dev-secret-key-change-in-production`` that sits in this repository. Anyone holding a
database dump could decrypt every org's Xero refresh token.

These tests pin the fix: production takes the key from ``XERO_TOKEN_ENCRYPTION_KEY`` only (never
a tracked file), fails at startup when it is absent or weak, and local/test keep the historical
derivation so tokens already stored there keep decrypting.
"""

from __future__ import annotations

import base64
import configparser
import hashlib
import secrets

import pytest
from cryptography.fernet import Fernet, InvalidToken

from app.utils.config_loader import Config

DEV_DEFAULT = "dev-secret-key-change-in-production"


def _config(environment: str, *, ini_secret: str | None = None) -> Config:
    cfg = Config.__new__(Config)
    cfg.environment = environment
    cfg.config = configparser.ConfigParser()
    if ini_secret is not None:
        cfg.config.read_dict({"app": {"secret_key": ini_secret}})
    return cfg


def _fernet_from(secret: str) -> Fernet:
    """The derivation ``XeroOAuthService`` has always used (sha256 -> urlsafe b64)."""
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(secret.encode()).digest()))


@pytest.mark.parametrize("environment", ["production", "prod"])
@pytest.mark.parametrize("value", [None, "", "   ", "short", DEV_DEFAULT])
def test_production_rejects_missing_or_weak_token_key(environment, value, monkeypatch):
    if value is None:
        monkeypatch.delenv("XERO_TOKEN_ENCRYPTION_KEY", raising=False)
    else:
        monkeypatch.setenv("XERO_TOKEN_ENCRYPTION_KEY", value)

    with pytest.raises(RuntimeError, match="XERO_TOKEN_ENCRYPTION_KEY"):
        _config(environment).xero_token_secret


@pytest.mark.parametrize("environment", ["production", "prod"])
def test_production_never_reads_the_key_from_the_tracked_ini(environment, monkeypatch):
    """A strong ``[app] secret_key`` in a committed file must not stand in for the secret."""
    monkeypatch.delenv("XERO_TOKEN_ENCRYPTION_KEY", raising=False)
    cfg = _config(environment, ini_secret=secrets.token_urlsafe(48))

    with pytest.raises(RuntimeError, match="XERO_TOKEN_ENCRYPTION_KEY"):
        cfg.xero_token_secret


@pytest.mark.parametrize("environment", ["production", "prod"])
def test_production_reads_the_key_from_the_environment(environment, monkeypatch):
    key = secrets.token_urlsafe(48)
    monkeypatch.setenv("XERO_TOKEN_ENCRYPTION_KEY", f"'{key}'")  # wrapping quotes are stripped

    assert _config(environment, ini_secret="from-the-ini-file").xero_token_secret == key


@pytest.mark.parametrize("environment", ["local", "test"])
def test_local_and_test_keep_the_historical_derivation(environment, monkeypatch):
    """[REGRESSION] Tokens already stored in local/test DBs were sealed under these values."""
    monkeypatch.delenv("XERO_TOKEN_ENCRYPTION_KEY", raising=False)

    assert _config(environment).xero_token_secret == DEV_DEFAULT
    assert _config(environment, ini_secret="configured-in-ini").xero_token_secret == "configured-in-ini"


def test_service_seals_production_tokens_under_the_injected_key_not_the_public_one(monkeypatch):
    from app.features.crm.services import xero_oauth_service
    from app.features.crm.services.xero_oauth_service import XeroOAuthService

    key = secrets.token_urlsafe(48)
    monkeypatch.setenv("XERO_TOKEN_ENCRYPTION_KEY", key)
    monkeypatch.setattr(xero_oauth_service, "config", _config("production"))

    sealed = XeroOAuthService.encrypt("xero-refresh-token")

    assert XeroOAuthService.decrypt(sealed) == "xero-refresh-token"
    assert _fernet_from(key).decrypt(sealed.encode()) == b"xero-refresh-token"
    with pytest.raises(InvalidToken):
        _fernet_from(DEV_DEFAULT).decrypt(sealed.encode())


def test_service_still_opens_tokens_sealed_under_the_historical_local_key(monkeypatch):
    from app.features.crm.services import xero_oauth_service
    from app.features.crm.services.xero_oauth_service import XeroOAuthService

    monkeypatch.setattr(xero_oauth_service, "config", _config("local"))
    stored_earlier = _fernet_from(DEV_DEFAULT).encrypt(b"stored-before-the-fix").decode()

    assert XeroOAuthService.decrypt(stored_earlier) == "stored-before-the-fix"


def test_production_app_refuses_to_start_without_a_token_key(monkeypatch):
    """Must fail at startup: inside ``decrypt`` the error would be swallowed into
    ``XeroTokenExpiredError`` and ``_refresh_token`` would then invalidate every stored token."""
    from app.api.app_factory import create_app
    from app.utils.config_loader import config

    monkeypatch.setattr(config, "environment", "production")
    monkeypatch.setenv("FLASK_SECRET_KEY", secrets.token_urlsafe(48))
    monkeypatch.delenv("XERO_TOKEN_ENCRYPTION_KEY", raising=False)

    with pytest.raises(RuntimeError, match="XERO_TOKEN_ENCRYPTION_KEY"):
        create_app()
