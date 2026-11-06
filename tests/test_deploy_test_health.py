"""deploy_test must not report success until the deployed app answers /healthcheck.

cd_e2e started against a container that was still booting and failed on
ERR_CONNECTION_REFUSED (main 2026-09-30, 10-14, 10-25). Runs the real script with fake
docker and curl on PATH.
"""

import os
import re
import stat
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "deploy_test_simple.sh"


def _exe(path: Path, body: str) -> None:
    path.write_text("#!/bin/bash\n" + body)
    path.chmod(path.stat().st_mode | stat.S_IEXEC)


def _run(tmp_path, *, healthy_after: int | None, running: str = "true"):
    """healthy_after: curl succeeds from this attempt on (None = never)."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    calls = tmp_path / "calls.log"
    _exe(
        bin_dir / "docker",
        f'echo "docker $*" >> {calls}\n'
        f'if [ "$1" = inspect ]; then echo {running}; fi\n'
        'if [ "$1" = logs ]; then echo "boot log line"; fi\n'
        "exit 0\n",
    )
    count = tmp_path / "curl.count"
    _exe(
        bin_dir / "curl",
        f"n=$(( $(cat {count} 2>/dev/null || echo 0) + 1 )); echo $n > {count}\n"
        f'echo "curl $*" >> {calls}\n'
        + (f"[ $n -ge {healthy_after} ] && exit 0\n" if healthy_after else "")
        + "exit 7\n",
    )
    env = {
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "FLASK_SECRET_KEY": "x" * 40,
        "GOOGLE_CLIENT_ID": "id",
        "GOOGLE_CLIENT_SECRET": "secret",
        "DEPLOY_HEALTH_ATTEMPTS": "5",
        "DEPLOY_HEALTH_INTERVAL": "0",
        "HOME": str(tmp_path),
    }
    out = subprocess.run(
        ["bash", str(SCRIPT), "registry.example/app:test-abc"], cwd=ROOT, env=env, capture_output=True, text=True
    )
    curls = int(count.read_text()) if count.exists() else 0
    return out, curls, calls.read_text()


def test_waits_until_the_app_is_healthy(tmp_path):
    out, curls, calls = _run(tmp_path, healthy_after=3)
    assert out.returncode == 0, out.stdout + out.stderr
    assert curls == 3
    assert "https://127.0.0.1:8001/healthcheck" in calls
    assert "passed its health check" in out.stdout


def test_never_healthy_exits_3_with_the_app_logs(tmp_path):
    out, curls, _calls = _run(tmp_path, healthy_after=None)
    assert out.returncode == 3
    assert curls == 5
    assert "boot log line" in out.stdout
    assert "✅" not in out.stdout


def test_container_that_exits_during_startup_fails_without_waiting(tmp_path):
    out, curls, _calls = _run(tmp_path, healthy_after=1, running="false")
    assert out.returncode == 3
    assert curls == 0
    assert "exited during startup" in out.stdout


def _job_script() -> str:
    text = (ROOT / ".gitlab-ci.yml").read_text()
    job = text.split("\ndeploy_test:\n", 1)[1].split("\n  environment:", 1)[0]
    block = re.search(r"    - \|\n((?:      .*\n|\s*\n)+)", job + "\n").group(1)
    return "\n".join(line[6:] for line in block.splitlines())


@pytest.mark.parametrize(("code", "rolled_back"), [(0, False), (1, False), (3, True)])
def test_job_rolls_back_to_test_stable_only_when_the_new_app_is_unhealthy(tmp_path, code, rolled_back):
    """A failed pull (exit 1) leaves the old app serving; exit 3 means it is already gone."""
    (tmp_path / "scripts").mkdir()
    log = tmp_path / "deploys.log"
    _exe(
        tmp_path / "scripts" / "deploy_test_simple.sh",
        f'echo "$1" >> {log}\ncase "$1" in *test-stable) exit 0;; esac\nexit {code}\n',
    )
    env = {**os.environ, "CI_REGISTRY_IMAGE": "reg/app", "CI_COMMIT_SHORT_SHA": "abc"}
    out = subprocess.run(
        ["bash", "-eo", "pipefail", "-c", _job_script()], cwd=tmp_path, env=env, capture_output=True, text=True
    )
    assert out.returncode == code
    deploys = log.read_text().split()
    assert deploys[0] == "reg/app/app:test-abc"
    assert ("reg/app/app:test-stable" in deploys) is rolled_back


def test_a_failed_start_after_the_old_app_is_removed_exits_3_for_rollback(tmp_path):
    """Review round 1 (claude-2): `docker run -d` failing after stop/rm exited 125 and skipped the rollback."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _exe(
        bin_dir / "docker",
        'if [ "$1" = run ] && [ "$2" = -d ]; then echo "Conflict. The container name is already in use" >&2; exit 125; fi\n'
        "exit 0\n",
    )
    _exe(bin_dir / "curl", "exit 0\n")
    env = {
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "FLASK_SECRET_KEY": "x" * 40,
        "GOOGLE_CLIENT_ID": "id",
        "GOOGLE_CLIENT_SECRET": "secret",
        "HOME": str(tmp_path),
    }
    out = subprocess.run(
        ["bash", str(SCRIPT), "registry.example/app:test-abc"], cwd=ROOT, env=env, capture_output=True, text=True
    )
    assert out.returncode == 3, out.stdout + out.stderr
    assert "Could not start" in out.stdout


def test_job_reports_a_failed_rollback_and_still_fails(tmp_path):
    (tmp_path / "scripts").mkdir()
    _exe(tmp_path / "scripts" / "deploy_test_simple.sh", 'case "$1" in *test-stable) exit 1;; esac\nexit 3\n')
    env = {**os.environ, "CI_REGISTRY_IMAGE": "reg/app", "CI_COMMIT_SHORT_SHA": "abc"}
    out = subprocess.run(
        ["bash", "-eo", "pipefail", "-c", _job_script()], cwd=tmp_path, env=env, capture_output=True, text=True
    )
    assert out.returncode == 3
    assert "Rollback to :test-stable failed too" in out.stdout
