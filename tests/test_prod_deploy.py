"""Exercise production deploy orchestration with real Git and a fake Docker daemon.

No production credentials, services, or database connections are used.
"""

import fcntl
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

# A small daemon model records container identity/running state and injects failures.
# The actual run_prod.sh AND prod_db.sh execute unchanged inside a disposable repo.
FAKE = r"""import json, os, pathlib, signal, subprocess, sys
state_path = pathlib.Path(os.environ["DEPLOY_STATE"])
s = json.loads(state_path.read_text())
a = sys.argv[1:]
command = pathlib.Path(sys.argv[0]).name
s["calls"].append([command, *a])
scenario = s["scenario"]
rc = 0
out = ""
if command == "python3":
    if scenario == "secrets":
        rc = 1
    else:
        out = "\n".join("export " + k + "=fixture-only" for k in (
            "POSTGRES_PASSWORD", "FLASK_SECRET_KEY", "BACKUP_CODE_ENCRYPTION_KEY",
            "XERO_TOKEN_ENCRYPTION_KEY", "GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET"))
elif command == "curl":
    app = s["containers"].get("workflow-engine-prod", {})
    rc = int(not app.get("running") or (scenario == "final_health" and app.get("image") != "old"))
elif command == "docker":
    op = a[0]
    if op == "build":
        if scenario == "build": rc = 1
        if scenario == "edit_during_build": pathlib.Path("tracked").write_text("changed")
        if scenario == "commit_during_build":
            subprocess.run(["git", "commit", "--allow-empty", "-m", "new"], check=True, capture_output=True)
            subprocess.run(["git", "push", "origin", "main"], check=True, capture_output=True)
    elif op == "inspect" or a[:2] == ["container", "inspect"]:
        container = s["containers"].get(a[-1])
        rc = int(container is None)
        if container is not None and "-f" in a:
            out = str(container["running"]).lower()
    elif op == "exec":
        if "pg_dump" in a:
            out = "fixture archive"
            rc = int(scenario == "backup")
        elif "pg_restore" in a:
            rc = int(scenario == "invalid_backup")
        elif "curl" in a:
            rc = int(scenario == "candidate_health")
    elif op == "run":
        if "--rm" in a:
            rc = int(scenario == "migration")
        else:
            name = a[a.index("--name") + 1]
            if name in s["containers"]:
                rc = 1
            else:
                is_final = name == "workflow-engine-prod"
                # Simulate Docker creating a container, then failing to publish the port.
                rc = int(is_final and scenario == "final_start")
                s["containers"][name] = {"running": not rc, "image": a[-1]}
                if is_final and scenario == "signal": os.kill(os.getppid(), signal.SIGTERM)
    elif op == "rename":
        if a[2] in s["containers"] or (scenario == "rename" and "-previous-" in a[2]): rc = 1
        else: s["containers"][a[2]] = s["containers"].pop(a[1])
        if scenario == "rename_signal" and "-previous-" in a[2]: os.kill(os.getppid(), signal.SIGTERM)
    elif op == "stop":
        if scenario == "stop": rc = 1
        else: s["containers"][a[1]]["running"] = False
    elif op == "start": s["containers"][a[1]]["running"] = True
    elif op == "rm": s["containers"].pop(a[-1], None)
state_path.write_text(json.dumps(s))
if out: print(out)
sys.exit(rc)
"""


def git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture
def deploy(tmp_path):
    repo = tmp_path / "checkout"
    repo.mkdir()
    (repo / "scripts").mkdir()
    for name in ("run_prod.sh", "prod_db.sh"):
        shutil.copy2(ROOT / "scripts" / name, repo / "scripts" / name)
    (repo / "tracked").write_text("original")
    git(repo, "init", "-b", "main")
    git(repo, "config", "user.email", "test@example.invalid")
    git(repo, "config", "user.name", "Deploy test")
    git(repo, "add", ".")
    git(repo, "commit", "-m", "fixture")
    origin = tmp_path / "origin.git"
    subprocess.run(["git", "init", "--bare", str(origin)], check=True, capture_output=True)
    git(repo, "remote", "add", "origin", str(origin))
    git(repo, "push", "origin", "main")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name in ("docker", "curl", "python3", "sleep"):
        stub = bin_dir / name
        stub.write_text(f"#!{sys.executable}\n" + FAKE)
        stub.chmod(0o755)
    home = tmp_path / "home"
    home.mkdir()
    state = tmp_path / "state.json"
    env = {**os.environ, "HOME": str(home), "PATH": f"{bin_dir}:/usr/bin:/bin", "DEPLOY_STATE": str(state)}

    class Deploy:
        def run(self, scenario="ok", existing=True):
            containers = {"workflow-engine-prod-db": {"running": True, "image": "postgres:16"}}
            if existing:
                containers["workflow-engine-prod"] = {"running": True, "image": "old"}
            state.write_text(json.dumps({"calls": [], "containers": containers, "scenario": scenario}))
            self.result = subprocess.run(
                ["bash", str(repo / "scripts/run_prod.sh")], env=env, capture_output=True, text=True, timeout=30
            )
            self.state = json.loads(state.read_text())
            return self

        @property
        def calls(self):
            return self.state["calls"]

        def assert_old_serving(self):
            assert self.state["containers"]["workflow-engine-prod"] == {"running": True, "image": "old"}
            assert not any("candidate-" in name for name in self.state["containers"])

    d = Deploy()
    d.repo, d.home = repo, home
    return d


@pytest.mark.parametrize("dirty", ["tracked", "untracked", "staged", "ahead", "behind", "fetch", "index"])
def test_checkout_guard_precedes_secrets_and_docker(deploy, dirty):
    if dirty == "tracked":
        (deploy.repo / "tracked").write_text("dirty")
    elif dirty == "untracked":
        (deploy.repo / "untracked").touch()
    elif dirty == "staged":
        (deploy.repo / "tracked").write_text("dirty")
        git(deploy.repo, "add", "tracked")
    elif dirty in ("ahead", "behind"):
        git(deploy.repo, "commit", "--allow-empty", "-m", "new")
        if dirty == "behind":
            git(deploy.repo, "push", "origin", "main")
            git(deploy.repo, "checkout", "HEAD~1")
    elif dirty == "index":
        (deploy.repo / ".git/index").write_bytes(b"invalid Git index")
    else:
        git(deploy.repo, "remote", "set-url", "origin", "/nonexistent-deploy-test-origin")
    deploy.run()
    assert deploy.result.returncode != 0
    assert deploy.calls == []
    deploy.assert_old_serving()


@pytest.mark.parametrize(
    "scenario",
    [
        "secrets",
        "build",
        "edit_during_build",
        "commit_during_build",
        "backup",
        "invalid_backup",
        "migration",
        "candidate_health",
        "rename",
    ],
)
def test_pre_cutover_failures_leave_old_app_untouched(deploy, scenario):
    deploy.run(scenario)
    assert deploy.result.returncode != 0, deploy.result.stdout
    deploy.assert_old_serving()
    assert not any(c[:2] == ["docker", "stop"] for c in deploy.calls)
    if scenario in ("backup", "invalid_backup"):
        assert not any(c[:2] == ["docker", "run"] for c in deploy.calls)
        assert not list((deploy.home / "db-backups/workflow-engine-prod").glob("*.dump"))


@pytest.mark.parametrize("scenario", ["final_start", "final_health", "stop", "signal", "rename_signal"])
def test_cutover_failures_restore_old_container_and_fail(deploy, scenario):
    deploy.run(scenario)
    assert deploy.result.returncode != 0
    deploy.assert_old_serving()
    assert "Restoring previous app" in deploy.result.stderr


@pytest.mark.parametrize("existing", [True, False])
def test_success_backs_up_then_migrates_and_checks_candidate_before_stopping(deploy, existing):
    deploy.run(existing=existing)
    assert deploy.result.returncode == 0, deploy.result.stderr
    app = deploy.state["containers"]["workflow-engine-prod"]
    assert app["running"] and app["image"].startswith("workflow-engine:prod-")
    previous = {name: c for name, c in deploy.state["containers"].items() if "-previous-" in name}
    assert len(previous) == int(existing)
    if existing:
        assert list(previous.values()) == [{"running": False, "image": "old"}]
    assert not any("candidate-" in name for name in deploy.state["containers"])
    calls = deploy.calls
    dump = next(i for i, c in enumerate(calls) if "pg_dump" in c)
    verify = next(i for i, c in enumerate(calls) if "pg_restore" in c)
    migrate = next(i for i, c in enumerate(calls) if "alembic" in c)
    candidate = next(i for i, c in enumerate(calls) if c[:2] == ["docker", "exec"] and "curl" in c)
    assert dump < verify < migrate < candidate
    if existing:
        stop = next(i for i, c in enumerate(calls) if c[:2] == ["docker", "stop"])
        assert candidate < stop
    runs = [c for c in calls if c[:2] == ["docker", "run"] and "--name" in c]
    assert "-p" not in runs[0]
    assert "127.0.0.1:8010:8000" in runs[1]
    backups = list((deploy.home / "db-backups/workflow-engine-prod").glob("*.dump"))
    assert len(backups) == 1
    assert backups[0].stat().st_mode & 0o777 == 0o600


def test_first_deploy_failure_removes_failed_app(deploy):
    deploy.run("final_start", existing=False)
    assert deploy.result.returncode != 0
    assert set(deploy.state["containers"]) == {"workflow-engine-prod-db"}


def test_deploy_lock_is_shared_across_worktrees(deploy):
    lock = deploy.home / ".cache/workflow-engine/prod-deploy.lock"
    lock.parent.mkdir(parents=True)
    with lock.open("w") as stream:
        fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        deploy.run()
    assert deploy.result.returncode != 0
    assert "Another production deploy" in deploy.result.stderr
    assert deploy.calls == []


def test_detached_current_main_is_an_allowed_deploy_checkout(deploy):
    git(deploy.repo, "checkout", "--detach", "HEAD")
    deploy.run()
    assert deploy.result.returncode == 0, deploy.result.stderr
