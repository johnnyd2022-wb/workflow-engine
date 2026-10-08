"""The shipped production config keeps agreeing with the scripts and routes it depends on.

Findings-Index: a569e705, 08d4fee9, ae250540, 051d8270 -- ``docs/production-bringup-checklist.md`` §3
listed four ``prod.ini`` gaps. Each has since been closed in the file itself; nothing pinned them, so the
checklist kept reading as open and any of them could regress unnoticed. Every test here compares the
config with the other half of the contract (a route, a ``docker run`` mount, a container name), because
a value that is merely present can still be wrong.
"""

from __future__ import annotations

import re
from configparser import ConfigParser
from pathlib import Path
from urllib.parse import urlsplit

import pytest

from app.utils.config_loader import Config

ROOT = Path(__file__).resolve().parents[1]
CONFIG_DIR = ROOT / "app" / "config"
SHIPPED_PRODUCTION_CONFIGS = ("prod.ini", "prod.ini.template")


def _config_for(name: str) -> Config:
    cfg = Config.__new__(Config)
    cfg.environment = "production"
    cfg.config = ConfigParser()
    assert cfg.config.read(CONFIG_DIR / name), f"{name} not found"
    return cfg


def _script_constant(script: str, name: str) -> str:
    """The value of a plain ``NAME=value`` assignment in a shell script under ``scripts/``."""
    match = re.search(rf"^{name}=(\S+)$", (ROOT / "scripts" / script).read_text(), re.MULTILINE)
    assert match, f"scripts/{script} no longer assigns {name}=..."
    return match.group(1)


@pytest.mark.parametrize("name", SHIPPED_PRODUCTION_CONFIGS)
def test_xero_redirect_uri_is_the_public_https_callback(name):
    """Without ``[xero] redirect_uri`` the connect route answers ``xero_not_configured``."""
    # The raw key, not ``Config.xero_redirect_uri``: that property prefers $XERO_REDIRECT_URI, so a
    # shell with the variable set would make this test check the environment instead of the file.
    redirect = _config_for(name).get("xero", "redirect_uri", "")
    parsed = urlsplit(redirect)

    assert parsed.scheme == "https", f"{name}: [xero] redirect_uri must be https, got {redirect!r}"
    assert parsed.hostname, f"{name}: [xero] redirect_uri has no host: {redirect!r}"
    assert parsed.path == "/crm/xero/callback"
    routes = (ROOT / "app" / "features" / "crm" / "routes" / "oauth_routes.py").read_text()
    assert f'route("{parsed.path}"' in routes, "no CRM route serves the callback path prod.ini registers"


@pytest.mark.parametrize("name", SHIPPED_PRODUCTION_CONFIGS)
def test_upload_storage_roots_are_the_volumes_run_prod_mounts(name):
    """Unset, both roots fall back to a path inside the container and uploads vanish on redeploy."""
    cfg = _config_for(name)
    mounted = set(re.findall(r"-v \S+:(/data/\S+)", (ROOT / "scripts" / "run_prod.sh").read_text()))

    assert mounted, "scripts/run_prod.sh mounts no /data volumes"
    assert cfg.evidence_storage_root in mounted, f"{name}: [evidence] storage_root is not a mounted volume"
    assert cfg.process_docs_storage_root in mounted, f"{name}: [process_docs] storage_root is not a mounted volume"
    assert cfg.evidence_storage_root != cfg.process_docs_storage_root
    # Raw keys, not the accessors: those fall back to non-empty defaults, so they would pass with the
    # keys deleted. The file should state its limits rather than lean on in-code defaults.
    for section in ("evidence", "process_docs"):
        for key in ("max_file_size_mb", "allowed_mime_types"):
            assert cfg.config.has_option(section, key), f"{name}: [{section}] {key} is missing"


@pytest.mark.parametrize("name", SHIPPED_PRODUCTION_CONFIGS)
def test_google_sign_in_is_only_on_when_production_receives_its_credentials(name):
    """With the switch on and no ``GOOGLE_CLIENT_ID`` / ``GOOGLE_CLIENT_SECRET`` in its environment
    ``register_google_client`` raises at startup, and production never reads the KeePass entries named
    in this section. ``scripts/run_prod.sh`` is what hands the container its environment, so turning the
    switch on is only coherent in the same change that forwards both variables there."""
    if not _config_for(name).getboolean("google_sign_in", "enabled", False):
        return

    forwarded = (ROOT / "scripts" / "run_prod.sh").read_text()
    for variable in ("GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET"):
        assert f"-e {variable}" in forwarded, (
            f"{name}: [google_sign_in] enabled = true, but scripts/run_prod.sh does not pass {variable} to the "
            "container, so the app would refuse to start"
        )


def test_prod_database_settings_match_the_database_container_script():
    """``scripts/prod_db.sh`` creates the container the app must reach by name on the shared network,
    and publishes it to loopback on the port ``[docker]`` records. A rename in one place only leaves
    production pointing at a host that does not resolve."""
    cfg = _config_for("prod.ini")
    container = _script_constant("prod_db.sh", "CONTAINER")

    assert cfg.get("database", "host", "") == container
    assert cfg.get("database", "port", "") == "5432"  # Postgres' own port: the app is on the container's network
    assert cfg.get("database", "name", "") == _script_constant("prod_db.sh", "DB_NAME")
    assert cfg.get("database", "user", "") == _script_constant("prod_db.sh", "DB_USER")
    assert cfg.get("docker", "container_name", "") == container
    assert cfg.get("docker", "host_port", "") == _script_constant("prod_db.sh", "HOST_PORT")
    assert cfg.get("docker", "container_port", "") == cfg.get("database", "port", "")
    assert not cfg.getboolean("docker", "enabled", False), "production's database is managed by scripts/prod_db.sh"
