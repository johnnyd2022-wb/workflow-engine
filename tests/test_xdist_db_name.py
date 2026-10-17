"""Parallel test workers get their own database, and only ever in local and test environments."""

import pytest

from app.utils.config_loader import config


@pytest.mark.parametrize(("environment", "suffixed"), [("local", True), ("test", True), ("production", False)])
def test_a_worker_database_suffix_never_applies_outside_local_and_test(monkeypatch, environment, suffixed):
    monkeypatch.setenv("PYTEST_XDIST_WORKER", "gw9")
    monkeypatch.setattr(config, "_environment", environment)
    assert config.db_name.endswith("_gw9") is suffixed


def test_without_xdist_the_configured_name_is_unchanged(monkeypatch):
    monkeypatch.delenv("PYTEST_XDIST_WORKER", raising=False)
    assert config.db_name == config.get("database", "name", "workflow-engine-test-db")
