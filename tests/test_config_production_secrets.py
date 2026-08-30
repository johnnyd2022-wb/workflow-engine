"""Production database credentials must come from the deployment environment, never
from a tracked config file.

Findings-Index: eb1dcecd -- ``app/config/prod.ini`` is tracked and carried a
``[database] password`` value. The engineering half of that finding is "require a
deployment secret/environment value at production startup"; these tests pin that
behaviour so a tracked-file fallback can never quietly return.
"""

from __future__ import annotations

import configparser
from pathlib import Path

import pytest

from app.utils.config_loader import Config

REPO_ROOT = Path(__file__).resolve().parents[1]


def _config(environment: str, *, ini_password: str = "value-from-tracked-file") -> Config:
    """A Config bound to *environment* with a populated ``[database]`` section but no
    KeePassXC creds -- exactly the shape a container sees at startup."""
    cfg = Config.__new__(Config)
    cfg._environment = environment
    cfg._keepass_creds = None
    cfg.config = configparser.ConfigParser()
    cfg.config.read_dict(
        {
            "database": {
                "host": "db.internal",
                "port": "5432",
                "name": "workflow-engine",
                "user": "workflow_rw",
                "password": ini_password,
            }
        }
    )
    return cfg


@pytest.mark.parametrize("environment", ["production", "prod"])
def test_production_db_password_requires_env_secret(environment, monkeypatch):
    """No POSTGRES_PASSWORD -> startup-time failure, not a silent tracked-file read."""
    monkeypatch.delenv("POSTGRES_PASSWORD", raising=False)
    cfg = _config(environment, ini_password="value-from-tracked-file")

    with pytest.raises(RuntimeError, match="POSTGRES_PASSWORD"):
        _ = cfg.db_password


@pytest.mark.parametrize("environment", ["production", "prod"])
def test_production_db_password_reads_env_secret(environment, monkeypatch):
    monkeypatch.setenv("POSTGRES_PASSWORD", "env-test")
    cfg = _config(environment, ini_password="value-from-tracked-file")

    assert cfg.db_password == "env-test"
    # And never the value sitting in the ini section.
    assert cfg.db_password != "value-from-tracked-file"


def test_production_db_password_strips_wrapping_quotes(monkeypatch):
    monkeypatch.setenv("POSTGRES_PASSWORD", "'quoted-secret'")
    cfg = _config("production")

    assert cfg.db_password == "quoted-secret"


def test_production_blank_env_secret_is_treated_as_missing(monkeypatch):
    monkeypatch.setenv("POSTGRES_PASSWORD", "   ")
    cfg = _config("production", ini_password="value-from-tracked-file")

    with pytest.raises(RuntimeError, match="POSTGRES_PASSWORD"):
        _ = cfg.db_password


def test_local_db_password_still_reads_config_file(monkeypatch):
    """[REGRESSION] The fail-fast rule is production-only; local/dev behaviour is unchanged."""
    monkeypatch.delenv("POSTGRES_PASSWORD", raising=False)
    cfg = _config("local", ini_password="local-dev-password")

    assert cfg.db_password == "local-dev-password"


def test_test_env_without_use_env_var_still_reads_config_file(monkeypatch):
    """[REGRESSION] ENVIRONMENT=test with use_env_var unset keeps reading the ini."""
    monkeypatch.delenv("POSTGRES_PASSWORD", raising=False)
    monkeypatch.delenv("POSTGRES_PASSWORD_TEST", raising=False)
    cfg = _config("test", ini_password="test-ini-password")

    assert cfg.db_password == "test-ini-password"


def test_tracked_prod_ini_carries_no_plaintext_db_password():
    parser = configparser.ConfigParser()
    parser.read(REPO_ROOT / "app" / "config" / "prod.ini")

    assert parser.get("database", "password", fallback="").strip() == "", (
        "app/config/prod.ini must not carry a plaintext database password; "
        "production reads POSTGRES_PASSWORD from the deployment environment"
    )


def test_prod_ini_template_carries_no_plaintext_db_password():
    parser = configparser.ConfigParser()
    parser.read(REPO_ROOT / "app" / "config" / "prod.ini.template")

    assert parser.get("database", "password", fallback="").strip() == "", (
        "prod.ini.template documents POSTGRES_PASSWORD as the source of truth; "
        "it must not seed a literal password value"
    )
