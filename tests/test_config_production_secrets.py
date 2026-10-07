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


@pytest.mark.parametrize(
    ("environment", "expected"), [("prod", True), ("production", True), ("test", False), ("local", False)]
)
def test_both_production_spellings_count_as_production(environment, expected):
    """scripts/run_prod.sh and the image run as ``prod``; code asking ``is_production`` must agree."""
    assert _config(environment).is_production is expected


def test_production_image_and_run_script_use_the_config_file_name():
    """``ENVIRONMENT`` picks ``app/config/<name>.ini``; only ``prod.ini`` exists."""
    dockerfile = (REPO_ROOT / "Dockerfile.multi").read_text()
    production_stage = dockerfile.split("as production", 1)[1]
    assert "ENV ENVIRONMENT=prod\n" in production_stage
    assert "ENVIRONMENT=prod" in (REPO_ROOT / "scripts" / "run_prod.sh").read_text()
    assert (REPO_ROOT / "app" / "config" / "prod.ini").is_file()
    assert not (REPO_ROOT / "app" / "config" / "production.ini").exists()


@pytest.mark.parametrize("environment", ["prod", "production"])
def test_production_refuses_the_built_in_backup_code_key(environment, monkeypatch):
    """2FA backup codes must never be encrypted with the development default in production."""
    from app.core.security import backup_code_encryption
    from app.utils import config_loader

    monkeypatch.delenv("BACKUP_CODE_ENCRYPTION_KEY", raising=False)
    monkeypatch.setattr(config_loader, "config", _config(environment))
    with pytest.raises(RuntimeError, match="BACKUP_CODE_ENCRYPTION_KEY"):
        backup_code_encryption.BackupCodeEncryption()

    monkeypatch.setattr(config_loader, "config", _config("test"))
    assert (
        backup_code_encryption.BackupCodeEncryption().decrypt(
            backup_code_encryption.BackupCodeEncryption().encrypt("ABCD-1234")
        )
        == "ABCD-1234"
    )


def test_production_config_keeps_uploads_on_a_volume_and_the_database_off_the_host():
    parser = configparser.ConfigParser()
    parser.read(REPO_ROOT / "app" / "config" / "prod.ini")
    assert parser.get("evidence", "storage_root") == "/data/evidence"
    assert parser.get("process_docs", "storage_root") == "/data/process_docs"
    assert parser.get("database", "host") == "workflow-engine-prod-db"
    assert parser.get("xero", "redirect_uri").startswith("https://")
    run_script = (REPO_ROOT / "scripts" / "run_prod.sh").read_text()
    assert "workflow-engine-prod-evidence:/data/evidence" in run_script
    assert "workflow-engine-prod-process-docs:/data/process_docs" in run_script
    # Secrets reach the container by name from the environment, never as values on the command line.
    assert "-e POSTGRES_PASSWORD=" not in run_script and "-e FLASK_SECRET_KEY=" not in run_script
    assert "127.0.0.1:${HOST_PORT}:8000" in run_script
