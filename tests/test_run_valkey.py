"""scripts/run_valkey.sh: the shared rate-limit store's container (design review S4).

Runs the real script against a fake docker that keeps a little state. What it must do: create
``valkey-<target>`` on the app's network from a pinned image with no published port, a named volume
and a restart policy; leave a healthy instance alone; start a stopped one; never remove a volume; and
never put the password on a command line.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest

from tests.valkey_support import VALKEY_IMAGE

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "run_valkey.sh"
PASSWORD = "canary-valkey-password"

FAKE_DOCKER = r"""import json, os, pathlib, sys
state_path = pathlib.Path(os.environ["FAKE_STATE"])
s = json.loads(state_path.read_text())
a = sys.argv[1:]
s["calls"].append(a)
s.setdefault("envs", []).append({k: os.environ.get(k) for k in ("REDISCLI_AUTH", "VALKEY_PASSWORD")})
rc, out = 0, ""
containers = s["containers"]
if a[:2] == ["network", "inspect"]:
    rc = 0 if a[2] in s["networks"] else 1
elif a[:2] == ["network", "create"]:
    s["networks"].append(a[-1])
elif a[0] == "volume":
    pass
elif a[0] == "inspect" or a[:2] == ["container", "inspect"]:
    c = containers.get(a[-1])
    rc = int(c is None)
    if c is not None and "-f" in a:
        out = "true" if c["running"] else "false"
elif a[0] == "run":
    name = a[a.index("--name") + 1]
    if name in containers:
        rc = 125
    else:
        containers[name] = {"running": True, "password": os.environ.get("REDISCLI_AUTH"), "healthy": s["new_healthy"]}
elif a[0] == "start":
    containers[a[-1]]["running"] = True
elif a[0] == "exec":
    name = next(x for x in a[1:] if not x.startswith("-") and x != "REDISCLI_AUTH")
    c = containers.get(name)
    if c is None or not c["running"]:
        rc = 1
    elif not c["healthy"]:
        rc = 1
        out = "Could not connect to Valkey"
    elif c["password"] != os.environ.get("REDISCLI_AUTH"):
        out = "AUTH failed: WRONGPASS invalid username-password pair"
    else:
        out = "PONG"
elif a[0] == "logs":
    out = "valkey log line"
state_path.write_text(json.dumps(s))
if out:
    print(out)
sys.exit(rc)
"""


@pytest.fixture
def run(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    docker = bin_dir / "docker"
    docker.write_text(f"#!{sys.executable}\n" + FAKE_DOCKER)
    docker.chmod(0o755)
    # KeePassXC is not consulted in these tests: an absent password must stay absent.
    for name in ("python3", "uv", "keepassxc-cli"):
        (bin_dir / name).write_text("#!/bin/sh\nexit 1\n")
        (bin_dir / name).chmod(0o755)
    state = tmp_path / "state.json"

    def _run(
        target="test",
        *,
        containers=None,
        networks=("workflow-observability", "workflow-engine-prod"),
        password=PASSWORD,
        new_healthy=True,
    ):
        state.write_text(
            json.dumps(
                {"calls": [], "containers": containers or {}, "networks": list(networks), "new_healthy": new_healthy}
            )
        )
        env = {
            "PATH": f"{bin_dir}:/usr/bin:/bin",
            "HOME": str(tmp_path),
            "FAKE_STATE": str(state),
            "VALKEY_HEALTH_ATTEMPTS": "3",
            "VALKEY_HEALTH_INTERVAL": "0",
        }
        if password is not None:
            env["VALKEY_PASSWORD"] = password
        import subprocess

        out = subprocess.run(["bash", str(SCRIPT), target], env=env, capture_output=True, text=True, timeout=60)
        s = json.loads(state.read_text())
        return out, s

    return _run


def _runs(state):
    return [c for c in state["calls"] if c[0] == "run"]


def _assert_nothing_destructive(state):
    for call in state["calls"]:
        assert call[:2] != ["volume", "rm"], call
        assert call[0] not in ("rm", "stop", "kill", "restart"), call
        assert "-v" not in call or call[0] == "run", call


def _assert_password_never_in_argv(out, state):
    for call in state["calls"]:
        assert PASSWORD not in " ".join(call), call
    assert PASSWORD not in out.stdout + out.stderr


@pytest.mark.parametrize(
    "target,name,network,volume",
    [
        ("test", "valkey-test", "workflow-observability", "valkey-test-data"),
        ("prod", "valkey-prod", "workflow-engine-prod", "valkey-prod-data"),
    ],
)
def test_a_missing_instance_is_created_on_the_apps_network_with_no_published_port(run, target, name, network, volume):
    out, state = run(target)
    assert out.returncode == 0, out.stdout + out.stderr
    (call,) = _runs(state)
    joined = " ".join(call)
    assert call[call.index("--name") + 1] == name
    assert call[call.index("--network") + 1] == network
    assert call[call.index("--restart") + 1] == "unless-stopped"
    assert f"{volume}:/data" in call
    assert VALKEY_IMAGE in call
    assert not any(flag in call for flag in ("-p", "--publish", "-P", "--publish-all")), "internal network only"
    assert not re.search(r"\s-p\S|--publish=", joined)
    assert "--requirepass" in joined, "the password is required, read from the environment"
    i = call.index("-e")
    assert call[i + 1] == "REDISCLI_AUTH", "passed by name: the value never reaches argv"
    assert state["containers"][name]["password"] == PASSWORD
    assert "--health-cmd" in joined
    _assert_password_never_in_argv(out, state)
    _assert_nothing_destructive(state)


def test_a_healthy_running_instance_is_left_alone(run):
    existing = {"valkey-test": {"running": True, "password": PASSWORD, "healthy": True}}
    out, state = run(containers=existing)
    assert out.returncode == 0, out.stdout + out.stderr
    assert "already up" in out.stdout
    assert not _runs(state)
    assert not any(c[0] == "start" for c in state["calls"])
    _assert_nothing_destructive(state)
    _assert_password_never_in_argv(out, state)


def test_a_stopped_instance_is_started_not_recreated(run):
    existing = {"valkey-test": {"running": False, "password": PASSWORD, "healthy": True}}
    out, state = run(containers=existing)
    assert out.returncode == 0, out.stdout + out.stderr
    assert ["start", "valkey-test"] in state["calls"]
    assert not _runs(state)
    _assert_nothing_destructive(state)


def test_a_running_instance_with_another_password_fails_and_is_not_touched(run):
    existing = {"valkey-test": {"running": True, "password": "an-older-password", "healthy": True}}
    out, state = run(containers=existing)
    assert out.returncode == 1
    assert "password" in out.stderr.lower()
    assert state["containers"]["valkey-test"]["password"] == "an-older-password"
    assert not _runs(state)
    _assert_nothing_destructive(state)
    _assert_password_never_in_argv(out, state)


def test_an_instance_that_never_answers_fails_the_script(run):
    out, state = run(new_healthy=False)
    assert out.returncode == 1
    assert "did not answer" in out.stderr
    _assert_nothing_destructive(state)


def test_no_password_stops_before_docker(run):
    out, state = run(password=None)
    assert out.returncode == 1
    assert "VALKEY_PASSWORD" in out.stderr
    assert not _runs(state)


def test_a_missing_network_is_created(run):
    out, state = run(networks=())
    assert out.returncode == 0, out.stdout + out.stderr
    assert ["network", "create", "workflow-observability"] in state["calls"]


def test_usage(run):
    out, _state = run("staging")
    assert out.returncode == 2


def test_the_image_is_pinned_to_an_exact_release_everywhere():
    script = SCRIPT.read_text()
    assert f"IMAGE={VALKEY_IMAGE}" in script
    assert re.fullmatch(r"valkey/valkey:\d+\.\d+\.\d+", VALKEY_IMAGE)
    ci = (ROOT / ".gitlab-ci.yml").read_text()
    pinned = set(re.findall(r"valkey/valkey:[\w.\-]+", ci))
    assert pinned == {VALKEY_IMAGE}, pinned
