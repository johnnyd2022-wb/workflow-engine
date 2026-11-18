"""preflight.py reports the shared rate-limit store (design review S4) without connecting to it."""

from __future__ import annotations

import configparser
import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def preflight(monkeypatch):
    spec = importlib.util.spec_from_file_location("preflight_s4", ROOT / "scripts" / "preflight.py")
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, "preflight_s4", module)  # dataclasses look their module up there
    spec.loader.exec_module(module)
    monkeypatch.setattr(module.shutil, "which", lambda name: "/usr/bin/docker")
    return module


def _cfg(**ratelimit) -> configparser.ConfigParser:
    cfg = configparser.ConfigParser()
    if ratelimit:
        cfg["ratelimit"] = ratelimit
    return cfg


def _docker(preflight, monkeypatch, states):
    def run_cmd(args, timeout=0):
        state = states.get(args[-1])
        return (0, state, "") if state else (1, "", "No such object")

    monkeypatch.setattr(preflight, "run_cmd", run_cmd)


def test_no_host_is_fine_for_one_process(preflight, monkeypatch):
    _docker(preflight, monkeypatch, {})
    check = preflight.check_valkey(_cfg())
    assert check.status == preflight.OK and "in-memory" in check.detail


def test_a_healthy_container_is_ok(preflight, monkeypatch):
    _docker(preflight, monkeypatch, {"valkey-test": "running/healthy"})
    assert preflight.check_valkey(_cfg(host="valkey-test")).status == preflight.OK


@pytest.mark.parametrize("state", [None, "running/unhealthy", "exited/"])
def test_a_missing_or_unhealthy_container_is_down_and_says_how_to_start_it(preflight, monkeypatch, state):
    _docker(preflight, monkeypatch, {"valkey-prod": state} if state else {})
    check = preflight.check_valkey(_cfg(host="valkey-prod"))
    assert check.status == preflight.DOWN and "run_valkey.sh" in check.detail


def test_preflight_never_connects_to_a_container_store(preflight, monkeypatch):
    _docker(preflight, monkeypatch, {"valkey-test": "running/healthy"})
    monkeypatch.setattr(preflight, "tcp_open", lambda *a, **k: pytest.fail("no published port to connect to"))
    preflight.check_valkey(_cfg(host="valkey-test"))
