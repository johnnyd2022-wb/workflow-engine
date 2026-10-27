"""scripts/prod_secrets.py: a production secret pasted in wrong stops the deploy, instead of
surfacing as a failed Google sign-in after it."""

import importlib.util
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "prod_secrets.py"


@pytest.fixture
def prod_secrets(monkeypatch):
    monkeypatch.syspath_prepend(str(SCRIPT.parent))
    spec = importlib.util.spec_from_file_location("prod_secrets_under_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, module)  # dataclasses look their module up here
    spec.loader.exec_module(module)
    return module


def _keepass(monkeypatch, module, values):
    monkeypatch.setattr(
        module.local_secrets, "get_keepass_entry", lambda entry_name: {"Password": values.get(entry_name, "x" * 40)}
    )


def test_a_well_formed_google_client_is_exported(prod_secrets, monkeypatch, capsys):
    _keepass(
        monkeypatch,
        prod_secrets,
        {
            "workflow-engine/GOOGLE_CLIENT_ID_PROD": "123-abc.apps.googleusercontent.com",
            "workflow-engine/GOOGLE_CLIENT_SECRET_PROD": "GOCSPX-" + "a" * 28,
        },
    )
    assert prod_secrets._export("db-password") == 0
    out = capsys.readouterr().out
    assert "export GOOGLE_CLIENT_ID=123-abc.apps.googleusercontent.com" in out
    assert "look wrong" not in out


def test_a_client_secret_pasted_as_the_id_stops_the_export(prod_secrets, monkeypatch, capsys):
    _keepass(
        monkeypatch,
        prod_secrets,
        {
            "workflow-engine/GOOGLE_CLIENT_ID_PROD": "GOCSPX-" + "a" * 28,
            "workflow-engine/GOOGLE_CLIENT_SECRET_PROD": "GOCSPX-" + "a" * 28,
        },
    )
    assert prod_secrets._export("db-password") == 1
    out = capsys.readouterr().out
    assert "export GOOGLE_CLIENT_ID=" not in out
    assert "GOOGLE_CLIENT_ID_PROD does not look like a Google client id" in out
    assert out.rstrip().endswith("false")  # run_prod.sh evals this, so the deploy stops
