"""scripts/run_mcp.sh: candidate -> health check -> swap, and the previous container survives a failure.

Public MCP 8.2d (spec .agents/specs/public-mcp.md, "Deploy (8.2d)"; AC31). The real script runs
unchanged against a small fake Docker daemon that remembers which containers exist, so the order
of events and what is left behind can be asserted. Nothing here touches a real container or image.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "run_mcp.sh"
IMAGE = "registry.example/mcp:test-abc123"
# Design review S4: the one secret the container gets, by name only (run_prod.sh / deploy_test_simple.sh export it).
VALKEY_PASSWORD = "canary-mcp-valkey-password"

# A fake `docker`: containers live in a JSON file; a scenario injects one kind of failure.
#   candidate_health  the candidate never answers /healthz
#   final_health      the replacement answers nothing once it holds the name and the port
#   final_start       `docker run -p ...` for the replacement fails (e.g. the port is taken)
FAKE_DOCKER = r"""import json, os, pathlib, re, sys
state_path = pathlib.Path(os.environ["MCP_FAKE_STATE"])
s = json.loads(state_path.read_text())
a = sys.argv[1:]
s["calls"].append(a)
scenario = s["scenario"]
rc, out = 0, ""
op = a[0]


def flag(name):
    return a[a.index(name) + 1] if name in a else None


if op == "run":
    name = flag("--name")
    if name in s["containers"]:
        rc = 1
    else:
        fails = "-p" in a and scenario == "final_start"
        s["containers"][name] = {"running": not fails, "image": a[-1], "args": a[1:-1]}
        rc = 125 if fails else 0
elif op == "inspect" or a[:2] == ["container", "inspect"]:
    c = s["containers"].get(a[-1])
    rc = int(c is None)
    if c is not None and "-f" in a:
        out = str(c["running"]).lower()
elif op == "exec":
    c = s["containers"].get(a[1])
    healthy = bool(c and c["running"])
    if "-candidate-" in a[1] and scenario == "candidate_health":
        healthy = False
    if "-candidate-" not in a[1] and c and c["image"] != "old" and scenario == "final_health":
        healthy = False
    rc = int(not healthy)
elif op == "rename":
    if a[2] in s["containers"]:
        rc = 1
    else:
        s["containers"][a[2]] = s["containers"].pop(a[1])
elif op == "stop":
    s["containers"][a[1]]["running"] = False
elif op == "start":
    s["containers"][a[1]]["running"] = True
elif op == "rm":
    for name in a[1:]:
        s["containers"].pop(name, None)
elif op == "ps":
    pattern = re.compile(next(x.split("name=", 1)[1] for x in a if "name=" in x))
    out = "\n".join(n for n in s["containers"] if pattern.search(n))
elif op == "logs":
    out = "boot log line"
elif op == "pull":
    rc = int(scenario == "pull")
elif op == "build":
    rc = int(scenario == "build")
    s["built"] = a
state_path.write_text(json.dumps(s))
if out:
    print(out)
sys.exit(rc)
"""


class Run:
    """One run_mcp.sh invocation against the fake daemon."""

    def __init__(self, tmp_path: Path):
        self.tmp = tmp_path
        self.bin = tmp_path / "bin"
        self.bin.mkdir()
        stub = self.bin / "docker"
        stub.write_text(f"#!{sys.executable}\n" + FAKE_DOCKER)
        stub.chmod(0o755)
        (tmp_path / "home").mkdir()
        self.state_path = tmp_path / "state.json"

    def run(self, target="test", *, scenario="ok", existing=True, env=None, args=None, valkey=True):
        containers = {}
        if existing:
            name = "workflow-engine-mcp-test" if target == "test" else "workflow-engine-mcp"
            containers[name] = {"running": True, "image": "old", "args": []}
        self.state_path.write_text(json.dumps({"calls": [], "containers": containers, "scenario": scenario}))
        environment = {
            "PATH": f"{self.bin}:/usr/bin:/bin",
            "HOME": str(self.tmp / "home"),
            "MCP_FAKE_STATE": str(self.state_path),
            "MCP_IMAGE": IMAGE,
            "MCP_HEALTH_ATTEMPTS": "3",
            "MCP_HEALTH_INTERVAL": "0",
            **({"VALKEY_PASSWORD": VALKEY_PASSWORD} if valkey else {}),
            **(env or {}),
        }
        self.result = subprocess.run(
            ["bash", str(SCRIPT), *(args if args is not None else [target])],
            env=environment,
            capture_output=True,
            text=True,
            timeout=60,
            cwd=ROOT,
        )
        self.state = json.loads(self.state_path.read_text())
        return self

    @property
    def calls(self) -> list[list[str]]:
        return self.state["calls"]

    @property
    def containers(self) -> dict:
        return self.state["containers"]

    def runs(self) -> list[list[str]]:
        return [c for c in self.calls if c[0] == "run"]

    def stray(self) -> list[str]:
        return [n for n in self.containers if "-candidate-" in n]

    def previous(self) -> list[str]:
        return [n for n in self.containers if "-previous-" in n]


@pytest.fixture
def mcp(tmp_path) -> Run:
    return Run(tmp_path)


def _envs(call: list[str]) -> dict[str, str | None]:
    """``-e NAME=value`` as NAME: value; ``-e NAME`` (passed by name from the script's env) as NAME: None."""
    pairs = (a.split("=", 1) for i, a in enumerate(call) if call[i - 1] == "-e")
    return {p[0]: (p[1] if len(p) == 2 else None) for p in pairs}


def _flag(call: list[str], name: str) -> str:
    return call[call.index(name) + 1]


def test_success_swaps_the_candidate_in_and_keeps_the_old_one_stopped(mcp):
    mcp.run("test")
    assert mcp.result.returncode == 0, mcp.result.stdout + mcp.result.stderr
    live = mcp.containers["workflow-engine-mcp-test"]
    assert live["running"] and live["image"] == IMAGE
    assert mcp.stray() == []
    assert [mcp.containers[n] for n in mcp.previous()] == [{"running": False, "image": "old", "args": []}]


def test_the_candidate_is_checked_alongside_the_old_container_before_it_is_touched(mcp):
    mcp.run("test")
    candidate, final = mcp.runs()
    # The candidate has no host port and no restart policy: a bad one can never take over traffic.
    assert "-p" not in candidate and "--restart" not in candidate
    assert _flag(final, "--restart") == "unless-stopped"
    ops = [c[0] for c in mcp.calls]
    first_probe = ops.index("exec")
    assert ops.index("run") < first_probe < ops.index("rename") < ops.index("stop")


def test_the_container_is_published_on_loopback_only(mcp):
    mcp.run("test")
    final = mcp.runs()[-1]
    assert _flag(final, "-p") == "127.0.0.1:8030:8030"
    assert not any(re.fullmatch(r"(0\.0\.0\.0:)?\d+:\d+", a) for a in final)


def test_it_joins_the_test_apps_network_and_calls_the_app_by_its_container_name(mcp):
    mcp.run("test")
    final = mcp.runs()[-1]
    assert _flag(final, "--network") == "workflow-observability"
    env = _envs(final)
    assert env["BIZE_API_BASE_URL"] == "https://workflow-engine-test:8001"
    assert env["MCP_PUBLIC_URL"] == "https://mcp-test.biz-e.app/mcp"
    assert env["BIZE_ISSUER_URL"] == "https://test.biz-e.app"


def test_prod_uses_its_own_name_port_network_and_app(mcp):
    mcp.run("prod")
    assert mcp.result.returncode == 0, mcp.result.stdout + mcp.result.stderr
    final = mcp.runs()[-1]
    assert _flag(final, "--name") == "workflow-engine-mcp"
    assert _flag(final, "-p") == "127.0.0.1:8031:8030"
    assert _flag(final, "--network") == "workflow-engine-prod"
    env = _envs(final)
    assert env["BIZE_API_BASE_URL"] == "https://workflow-engine-prod:8000"
    assert env["MCP_PUBLIC_URL"] == "https://mcp.biz-e.app/mcp"
    assert env["BIZE_ISSUER_URL"] == "https://biz-e.app"


def test_the_public_urls_are_read_from_the_apps_own_config(mcp):
    """The resource a token is bound to is the app's [mcp] resource; the server must advertise the same."""
    for target in ("test", "prod"):
        mcp.run(target)
        env = _envs(mcp.runs()[-1])
        section = (ROOT / f"app/config/{target}.ini").read_text().split("[mcp]", 1)[1]
        assert env["MCP_PUBLIC_URL"] == re.search(r"(?m)^resource\s*=\s*(\S+)", section).group(1)
        assert env["BIZE_ISSUER_URL"] == re.search(r"(?m)^issuer\s*=\s*(\S+)", section).group(1)


def test_ambient_settings_in_the_operators_shell_never_reach_a_deploy(mcp):
    """docs/public-mcp-server.md tells people to export these for local runs; a deploy must not use them."""
    mcp.run(
        "prod",
        env={
            "BIZE_API_BASE_URL": "https://dev.biz-e.app",
            "MCP_PUBLIC_URL": "http://localhost:8030/mcp",
            "BIZE_ISSUER_URL": "http://localhost:8005",
        },
    )
    env = _envs(mcp.runs()[-1])
    assert env["BIZE_API_BASE_URL"] == "https://workflow-engine-prod:8000"
    assert env["MCP_PUBLIC_URL"] == "https://mcp.biz-e.app/mcp"
    assert env["BIZE_ISSUER_URL"] == "https://biz-e.app"


@pytest.mark.parametrize("target", ["test", "prod"])
def test_no_secret_is_passed_to_the_container(mcp, target):
    canary = "leak-canary-9f3a"
    mcp.run(
        target,
        env={
            "POSTGRES_PASSWORD": canary,
            "FLASK_SECRET_KEY": canary,
            "BACKUP_CODE_ENCRYPTION_KEY": canary,
            "GOOGLE_CLIENT_SECRET": canary,
        },
    )
    assert mcp.result.returncode == 0
    assert canary not in json.dumps(mcp.calls)
    assert VALKEY_PASSWORD not in json.dumps(mcp.calls) + mcp.result.stdout + mcp.result.stderr
    for call in mcp.runs():
        # The three addresses, the TLS switch and the rate-limit store's address as NAME=value; the one
        # secret, VALKEY_PASSWORD, by name only (design review S4). Nothing else inherited.
        env = _envs(call)
        assert set(env) == {
            "BIZE_API_BASE_URL",
            "MCP_PUBLIC_URL",
            "BIZE_ISSUER_URL",
            "BIZE_API_VERIFY_TLS",
            "BIZE_RATELIMIT_URI",
            "VALKEY_PASSWORD",
        }
        assert env["VALKEY_PASSWORD"] is None, "passed by name: the value never reaches the command line"
        assert env["BIZE_RATELIMIT_URI"] == f"redis://valkey-{target}:6379/0"
        assert [n for n, v in env.items() if v is None] == ["VALKEY_PASSWORD"]
        assert "--env-file" not in call and "-v" not in call and "--volume" not in call


def test_prod_without_the_valkey_password_starts_nothing(mcp):
    mcp.run("prod", valkey=False)
    assert mcp.result.returncode == 1
    assert "VALKEY_PASSWORD" in mcp.result.stderr
    assert mcp.runs() == []


def test_test_without_the_valkey_password_counts_in_process(mcp):
    mcp.run("test", valkey=False)
    assert mcp.result.returncode == 0, mcp.result.stdout + mcp.result.stderr
    env = _envs(mcp.runs()[-1])
    assert "BIZE_RATELIMIT_URI" not in env and "VALKEY_PASSWORD" not in env


def test_the_container_is_locked_down(mcp):
    mcp.run("test")
    final = mcp.runs()[-1]
    assert _flag(final, "--cap-drop") == "ALL"
    assert _flag(final, "--security-opt") == "no-new-privileges:true"
    assert "--privileged" not in final


def test_a_failing_candidate_keeps_the_previous_container_and_fails(mcp):
    mcp.run("test", scenario="candidate_health")
    assert mcp.result.returncode != 0
    assert mcp.containers == {"workflow-engine-mcp-test": {"running": True, "image": "old", "args": []}}
    assert not any(c[0] in ("rename", "stop") for c in mcp.calls)
    assert len(mcp.runs()) == 1, "the real container must never be started after a bad candidate"
    assert "boot log line" in mcp.result.stderr
    assert "did not pass its health check" in mcp.result.stderr


def test_a_replacement_that_fails_after_the_swap_is_rolled_back_to_the_previous_container(mcp):
    mcp.run("test", scenario="final_health")
    assert mcp.result.returncode != 0
    assert mcp.containers == {"workflow-engine-mcp-test": {"running": True, "image": "old", "args": []}}
    assert "Restoring the previous MCP container" in mcp.result.stderr


def test_a_replacement_that_cannot_start_is_rolled_back_to_the_previous_container(mcp):
    mcp.run("test", scenario="final_start")
    assert mcp.result.returncode != 0
    assert mcp.containers == {"workflow-engine-mcp-test": {"running": True, "image": "old", "args": []}}


def test_a_failed_first_deploy_leaves_nothing_behind(mcp):
    mcp.run("test", scenario="final_health", existing=False)
    assert mcp.result.returncode != 0
    assert mcp.containers == {}


def test_a_first_deploy_has_nothing_to_rename(mcp):
    mcp.run("test", existing=False)
    assert mcp.result.returncode == 0, mcp.result.stdout + mcp.result.stderr
    assert not any(c[0] in ("rename", "stop") for c in mcp.calls)
    assert mcp.containers["workflow-engine-mcp-test"]["image"] == IMAGE


def test_last_deploys_stopped_container_is_cleared_before_the_next_one_is_kept(mcp):
    stale = "workflow-engine-mcp-test-previous-1700000000-1"
    mcp.run("test")
    assert len(mcp.previous()) == 1
    # A second deploy on the same daemon state: the earlier leftover goes, the newest is kept.
    state = json.loads(mcp.state_path.read_text())
    state["containers"][stale] = {"running": False, "image": "older", "args": []}
    state["calls"], state["scenario"] = [], "ok"
    mcp.state_path.write_text(json.dumps(state))
    subprocess.run(
        ["bash", str(SCRIPT), "test"],
        env={
            "PATH": f"{mcp.bin}:/usr/bin:/bin",
            "HOME": str(mcp.tmp / "home"),
            "MCP_FAKE_STATE": str(mcp.state_path),
            "MCP_IMAGE": IMAGE,
            "MCP_HEALTH_ATTEMPTS": "3",
            "MCP_HEALTH_INTERVAL": "0",
        },
        capture_output=True,
        cwd=ROOT,
        timeout=60,
    )
    after = json.loads(mcp.state_path.read_text())["containers"]
    assert stale not in after
    assert len([n for n in after if "-previous-" in n]) == 1


def test_a_replacement_that_cannot_start_is_never_probed(mcp):
    mcp.run("test", scenario="final_start", existing=False)
    assert mcp.result.returncode != 0
    assert not any(c[0] == "exec" and "-candidate-" not in c[1] for c in mcp.calls)


def test_the_health_probe_runs_inside_the_container(mcp):
    """A CI job runs in a container of its own, so the Docker host's loopback is not reachable from it."""
    mcp.run("test")
    probes = [c for c in mcp.calls if c[0] == "exec"]
    assert probes
    for probe in probes:
        assert "curl" in probe and any(a.startswith("http://127.0.0.1:8030/healthz") for a in probe)


def test_the_probe_checks_the_path_to_the_app_not_only_the_server(mcp):
    """/healthz?deep=1 calls the app's /healthcheck, so a wrong address or TLS setting fails the deploy."""
    mcp.run("test")
    assert all(any("deep=1" in a for a in c) for c in mcp.calls if c[0] == "exec")


def test_the_container_trusts_the_apps_self_signed_certificate_only_on_the_private_network(mcp):
    mcp.run("test")
    assert _envs(mcp.runs()[-1])["BIZE_API_VERIFY_TLS"] == "false"


def test_a_prepared_image_is_used_as_it_is_and_nothing_is_built_or_pulled(mcp):
    mcp.run("test")
    assert not any(c[0] in ("build", "pull") for c in mcp.calls)
    assert mcp.runs()[-1][-1] == IMAGE


def test_an_unknown_target_is_a_usage_error_before_any_docker_call(mcp):
    mcp.run(args=["staging"])
    assert mcp.result.returncode == 2
    assert "Usage" in mcp.result.stderr
    assert mcp.calls == []


def test_the_default_target_is_test(mcp):
    mcp.run(args=[])
    assert mcp.result.returncode == 0, mcp.result.stdout + mcp.result.stderr
    assert "workflow-engine-mcp-test" in mcp.containers


def test_a_deploy_is_locked_per_target(mcp):
    import fcntl

    lock = mcp.tmp / "home/.cache/workflow-engine/mcp-test-deploy.lock"
    lock.parent.mkdir(parents=True)
    with lock.open("w") as stream:
        fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        mcp.run("test")
    assert mcp.result.returncode != 0
    assert "deploy is running" in mcp.result.stderr
    assert mcp.calls == []


def test_the_script_has_no_syntax_errors():
    subprocess.run(["bash", "-n", str(SCRIPT)], check=True)
