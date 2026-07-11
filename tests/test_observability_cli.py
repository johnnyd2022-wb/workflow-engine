"""Tests for repository-managed observability Click commands."""

from __future__ import annotations

from click.testing import CliRunner

from app.cli import observability


def test_observability_group_lists_lifecycle_commands():
    result = CliRunner().invoke(observability.observability, ["--help"])

    assert result.exit_code == 0
    for command in ("config", "help", "logs", "reset", "secrets", "start", "status", "stop"):
        assert command in result.output


def test_observability_help_shows_browser_urls():
    result = CliRunner().invoke(observability.observability, ["help"])

    assert result.exit_code == 0
    assert "Grafana:" in result.output
    assert "PostHog:" in result.output
    assert "http://localhost:3000" in result.output


def test_secret_rotation_requires_volume_reset():
    result = CliRunner().invoke(observability.observability, ["reset", "--rotate-secrets"])

    assert result.exit_code == 2
    assert "requires --volumes" in result.output


def test_stack_environment_uses_local_ini_values_and_keepass_entries(monkeypatch):
    values = {
        "grafana_admin_user": "configured-admin",
        "posthog_site_url": "http://posthog.local:8000",
        "keepass_posthog_secret_entry": "posthog-secret",
        "keepass_posthog_encryption_salt_keys_entry": "encryption-salt",
        "keepass_grafana_admin_password_entry": "grafana-password",
    }
    monkeypatch.setattr(observability.app_config, "environment", "local")
    monkeypatch.setattr(
        observability.app_config, "get", lambda _section, key, fallback="": values.get(key, fallback)
    )
    def _secret_value(entry_name):
        if entry_name == "encryption-salt":
            return "a" * 32
        return f"value-for-{entry_name}"

    monkeypatch.setattr(observability, "_read_keepass_password", _secret_value)

    environment, missing = observability._stack_environment()

    assert missing == []
    assert environment["GRAFANA_ADMIN_USER"] == "configured-admin"
    assert environment["POSTHOG_SITE_URL"] == "http://posthog.local:8000"
    assert environment["POSTHOG_SECRET"] == "value-for-posthog-secret"
