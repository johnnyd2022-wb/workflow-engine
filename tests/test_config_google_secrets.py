"""Google credentials resolve per environment without exposing secret values."""

import configparser
from pathlib import Path

import pytest

from app.utils.config_loader import Config
from scripts import local_secrets


@pytest.mark.parametrize("filename", ["local.ini", "local.ini.template", "test.ini", "test.ini.template"])
def test_dev_test_google_configs_use_provisioned_keepass_entries(filename):
    cfg = configparser.ConfigParser()
    cfg.read(Path(__file__).resolve().parents[1] / "app" / "config" / filename)
    assert cfg.get("google_sign_in", "keepass_client_id_entry") == "workflow-engine/GOOGLE_CLIENT_ID"
    assert cfg.get("google_sign_in", "keepass_client_secret_entry") == "workflow-engine/GOOGLE_CLIENT_SECRET"


@pytest.mark.parametrize("environment", ["test", "prod", "production"])
def test_google_keepass_is_used_for_test_host_only(environment, monkeypatch):
    cfg = Config.__new__(Config)
    cfg._environment = environment
    cfg._google_keepass_creds = {}
    cfg._observability_keepass_creds = {}
    cfg.config = configparser.ConfigParser()
    cfg.config.read_dict(
        {
            "google_sign_in": {
                "enabled": "true",
                "keepass_client_id_entry": "workflow-engine/GOOGLE_CLIENT_ID",
                "keepass_client_secret_entry": "workflow-engine/GOOGLE_CLIENT_SECRET",
            }
        }
    )
    monkeypatch.delenv("GOOGLE_CLIENT_ID", raising=False)
    monkeypatch.delenv("GOOGLE_CLIENT_SECRET", raising=False)
    requested = []

    def entry(*, entry_name):
        requested.append(entry_name)
        return {"Password": "test-value"}

    monkeypatch.setattr(local_secrets, "get_keepass_entry", entry)
    cfg._load_keepass_creds()
    if environment == "test":
        assert requested == ["workflow-engine/GOOGLE_CLIENT_ID", "workflow-engine/GOOGLE_CLIENT_SECRET"]
        assert cfg.google_client_id == cfg.google_client_secret == "test-value"
    else:
        assert requested == []
        assert not cfg.google_client_id and not cfg.google_client_secret


def test_injected_google_credentials_skip_keepass(monkeypatch):
    cfg = Config.__new__(Config)
    cfg._environment = "test"
    cfg._google_keepass_creds = {}
    cfg._observability_keepass_creds = {}
    cfg.config = configparser.ConfigParser()
    cfg.config.read_dict({"google_sign_in": {"enabled": "true"}})
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "injected-client")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "injected-secret")
    monkeypatch.setattr(local_secrets, "get_keepass_entry", lambda **kwargs: pytest.fail("Unexpected KeePass access"))
    cfg._load_keepass_creds()
    assert cfg.google_client_id == "injected-client"
    assert cfg.google_client_secret == "injected-secret"
