"""deploy_test_simple.sh starts the MCP server once the app is healthy, and never rolls the app back for it.

Public MCP 8.2d (AC31, AC32). Runs the real deploy script, and through it the real run_mcp.sh, with a
fake docker on PATH. The CI job rolls the app back only on exit 3 ("the new app never became
healthy"), so an MCP failure must exit with something else.
"""

from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "deploy_test_simple.sh"
APP_REF = "registry.example/app:test-abc"
MCP_REF = "registry.example/mcp:test-abc"


def _exe(path: Path, body: str) -> None:
    path.write_text("#!/bin/bash\n" + body)
    path.chmod(path.stat().st_mode | stat.S_IEXEC)


def _deploy(tmp_path, *args, app_healthy=True, mcp_healthy=True, mcp_pull_ok=True):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    calls = tmp_path / "calls.log"
    _exe(
        bin_dir / "docker",
        f'echo "docker $*" >> {calls}\n'
        'case "$1" in\n'
        "  inspect) echo true ;;\n"
        '  logs) echo "boot log line" ;;\n'
        f'  pull) case "$2" in *mcp*) {"exit 0" if mcp_pull_ok else "exit 1"} ;; esac ;;\n'
        '  exec) case "$*" in\n'
        f"    *healthz*) {'exit 0' if mcp_healthy else 'exit 1'} ;;\n"
        f"    *) {'exit 0' if app_healthy else 'exit 1'} ;;\n"
        "  esac ;;\n"
        "esac\n"
        "exit 0\n",
    )
    _exe(bin_dir / "curl", "exit 99\n")
    env = {
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "FLASK_SECRET_KEY": "x" * 40,
        "GOOGLE_CLIENT_ID": "id",
        "GOOGLE_CLIENT_SECRET": "secret",
        "POSTGRES_PASSWORD": "leak-canary-77c1",
        "DEPLOY_HEALTH_ATTEMPTS": "3",
        "DEPLOY_HEALTH_INTERVAL": "0",
        "MCP_HEALTH_ATTEMPTS": "3",
        "MCP_HEALTH_INTERVAL": "0",
        "HOME": str(tmp_path),
    }
    argv = ["bash", str(SCRIPT), *args]
    out = subprocess.run(argv, cwd=ROOT, env=env, capture_output=True, text=True, timeout=60)
    log = calls.read_text().splitlines() if calls.exists() else []
    return out, log


def _app_probe(log):
    return next(i for i, line in enumerate(log) if line.startswith("docker exec workflow-engine-test "))


def test_the_mcp_server_is_pulled_and_started_after_the_app_is_healthy(tmp_path):
    out, log = _deploy(tmp_path, APP_REF, MCP_REF)
    assert out.returncode == 0, out.stdout + out.stderr
    assert f"docker pull {MCP_REF}" in log
    app_up = _app_probe(log)
    mcp_runs = [i for i, line in enumerate(log) if line.startswith("docker run") and "workflow-engine-mcp-test" in line]
    assert len(mcp_runs) == 2, "a candidate, then the real container"
    assert min(mcp_runs) > app_up
    assert MCP_REF in log[mcp_runs[-1]]
    assert "-p 127.0.0.1:8030:8030" in log[mcp_runs[-1]]
    assert "MCP server up" in out.stdout


def test_no_app_secret_reaches_the_mcp_container(tmp_path):
    _out, log = _deploy(tmp_path, APP_REF, MCP_REF)
    for line in log:
        if line.startswith("docker run") and "workflow-engine-mcp-test" in line:
            assert "leak-canary-77c1" not in line
            assert "FLASK_SECRET_KEY" not in line
            assert "GOOGLE_CLIENT" not in line


def test_an_unhealthy_mcp_server_fails_the_deploy_with_4_and_leaves_the_app_alone(tmp_path):
    out, log = _deploy(tmp_path, APP_REF, MCP_REF, mcp_healthy=False)
    assert out.returncode == 4, out.stdout + out.stderr
    assert out.returncode != 3, "exit 3 would make the CI job roll the app back"
    assert "left alone" in out.stdout
    after = log[_app_probe(log) :]
    for line in after:
        words = line.split()
        if words[1:2] and words[1] in ("stop", "rm", "rename", "kill", "restart"):
            assert "workflow-engine-test" not in words[2:], line
    assert "workflow-engine-test did not pass" not in out.stdout


def test_a_failed_mcp_pull_fails_the_deploy_with_4_and_starts_nothing(tmp_path):
    out, log = _deploy(tmp_path, APP_REF, MCP_REF, mcp_pull_ok=False)
    assert out.returncode == 4, out.stdout + out.stderr
    assert not any(line.startswith("docker run") and "workflow-engine-mcp" in line for line in log)


def test_a_rollback_to_test_stable_leaves_the_mcp_server_as_it_is(tmp_path):
    """The CD job redeploys :test-stable with only the app image."""
    out, log = _deploy(tmp_path, "registry.example/app:test-stable")
    assert out.returncode == 0, out.stdout + out.stderr
    assert "leaving the MCP server as it is" in out.stdout
    assert not any("mcp" in line for line in log)


def test_an_unhealthy_app_exits_3_and_never_reaches_the_mcp_step(tmp_path):
    out, log = _deploy(tmp_path, APP_REF, MCP_REF, app_healthy=False)
    assert out.returncode == 3
    assert not any("mcp" in line for line in log)
