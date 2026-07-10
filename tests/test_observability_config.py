"""Tests for local observability configuration and KeePassXC precedence."""

from __future__ import annotations

import configparser

from app.utils.config_loader import Config


def _local_config() -> Config:
    config = Config.__new__(Config)
    config._environment = "local"
    config._observability_keepass_creds = {"posthog_project_api_key": "keepass-project-key"}
    config.config = configparser.ConfigParser()
    config.config.read_dict(
        {
            "observability": {
                "rum_posthog_api_key": "ini-project-key",
                "keepass_posthog_project_api_key_entry": "custom/observability/posthog-key",
            }
        }
    )
    return config


def test_local_posthog_api_key_prefers_environment_then_keepass_then_ini(monkeypatch):
    config = _local_config()

    monkeypatch.delenv("POSTHOG_PROJECT_API_KEY", raising=False)
    assert config.rum_posthog_api_key == "keepass-project-key"

    monkeypatch.setenv("POSTHOG_PROJECT_API_KEY", "environment-project-key")
    assert config.rum_posthog_api_key == "environment-project-key"


def test_local_posthog_keepass_entry_path_is_configured():
    assert _local_config().keepass_posthog_project_api_key_entry == "custom/observability/posthog-key"
