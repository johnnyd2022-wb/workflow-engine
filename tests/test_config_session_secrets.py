"""Session signing must never use a public development key in any environment."""

import configparser
import secrets

import pytest
from flask import Flask
from flask.sessions import SecureCookieSessionInterface
from werkzeug.test import EnvironBuilder

from app.utils.config_loader import Config
from scripts import local_secrets


def _config(environment):
    cfg = Config.__new__(Config)
    cfg.environment = environment
    cfg.config = configparser.ConfigParser()
    cfg._session_keepass_key = ""
    return cfg


@pytest.mark.parametrize("environment", ["local", "test", "prod", "production"])
@pytest.mark.parametrize("value", ["", "short", "PROTECTED", "dev-secret-key-change-in-production"])
def test_missing_or_unsafe_session_key_fails_closed(environment, value, monkeypatch):
    monkeypatch.setenv("FLASK_SECRET_KEY", value)
    monkeypatch.setattr(local_secrets, "get_keepass_entry", lambda **kwargs: {})
    with pytest.raises(RuntimeError, match="strong session-signing key"):
        _config(environment).session_secret_key


@pytest.mark.parametrize("environment", ["local", "test"])
def test_session_key_loads_and_caches_environment_keepass_entry(environment, monkeypatch):
    monkeypatch.delenv("FLASK_SECRET_KEY", raising=False)
    key = secrets.token_urlsafe(48)
    requested = []

    def entry(*, entry_name):
        requested.append(entry_name)
        return {"Password": key}

    monkeypatch.setattr(local_secrets, "get_keepass_entry", entry)
    cfg = _config(environment)
    assert cfg.session_secret_key == key
    assert cfg.session_secret_key == key
    assert requested == [f"workflow-engine/FLASK_SECRET_KEY_{environment.upper()}"]


@pytest.mark.parametrize("environment", ["local", "test", "prod", "production"])
def test_injected_session_key_needs_no_keepass(environment, monkeypatch):
    key = secrets.token_urlsafe(48)
    monkeypatch.setenv("FLASK_SECRET_KEY", key)
    monkeypatch.setattr(local_secrets, "get_keepass_entry", lambda **kwargs: pytest.fail("Unexpected KeePass access"))
    assert _config(environment).session_secret_key == key


def test_app_rejects_cookie_forged_with_old_public_key(monkeypatch):
    from app.api.app_factory import create_app

    key = secrets.token_urlsafe(48)
    monkeypatch.setenv("FLASK_SECRET_KEY", key)
    app = create_app()
    assert app.secret_key == key
    old_app = Flask("old_key")
    old_app.secret_key = "dev-secret-key-change-in-production"
    forged = SecureCookieSessionInterface().get_signing_serializer(old_app).dumps({"user_id": "forged"})
    request = EnvironBuilder(path="/", headers={"Cookie": f"session={forged}"}).get_request()
    assert not app.session_interface.open_session(app, request)
    signed = app.session_interface.get_signing_serializer(app).dumps({"user_id": "valid"})
    request = EnvironBuilder(path="/", headers={"Cookie": f"session={signed}"}).get_request()
    assert app.session_interface.open_session(app, request)["user_id"] == "valid"


def test_all_workers_load_the_same_injected_key(monkeypatch):
    from app.api.app_factory import create_app

    key = secrets.token_urlsafe(48)
    monkeypatch.setenv("FLASK_SECRET_KEY", key)
    first, second = create_app(), create_app()
    cookie = first.session_interface.get_signing_serializer(first).dumps({"user_id": "valid"})
    request = EnvironBuilder(path="/", headers={"Cookie": f"session={cookie}"}).get_request()
    assert second.session_interface.open_session(second, request)["user_id"] == "valid"
