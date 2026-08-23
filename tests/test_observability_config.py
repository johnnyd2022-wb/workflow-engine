"""Tests for local observability configuration and KeePassXC precedence."""

from __future__ import annotations

import configparser
from pathlib import Path

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


def test_observability_data_exports_default_to_disabled():
    config = _local_config()

    assert config.grafana_data_enabled is False
    assert config.posthog_data_enabled is False


def test_all_environment_configs_disable_observability_data_exports():
    config_dir = Path(__file__).resolve().parents[1] / "app" / "config"

    for environment in ("local", "prod", "test"):
        parser = configparser.ConfigParser()
        parser.read(config_dir / f"{environment}.ini")

        assert parser.getboolean("observability", "grafana_data_enabled") is False
        assert parser.getboolean("observability", "posthog_data_enabled") is False


def test_test_environment_disables_rum_entirely():
    """[REGRESSION] test.ini's rum_enabled must stay False.

    grafana_data_enabled/posthog_data_enabled already gate the server-side telemetry
    proxy and the client-side SDK init (app_factory._telemetry_response,
    observability-rum.js), but test.biz-e.app is a publicly reachable environment whose
    local observability stack (Alloy/PostHog) isn't guaranteed to be running — and rum
    upstream hosts (rum_faro_upstream etc.) only resolve inside the Docker network at all.
    rum_enabled=True there means the browser RUM SDK loads and repeatedly POSTs to
    /telemetry regardless of those data-export gates, producing 503 console noise on every
    page. Belt-and-braces: this flag must independently be off for `test`, not just rely
    on the data-export gates.
    """
    config_dir = Path(__file__).resolve().parents[1] / "app" / "config"
    parser = configparser.ConfigParser()
    parser.read(config_dir / "test.ini")

    assert parser.getboolean("observability", "rum_enabled") is False
