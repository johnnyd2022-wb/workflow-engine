"""Recovery safety tests; do not import app configuration or connect to any DB."""

import importlib.util
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

SPEC = importlib.util.spec_from_file_location("database_recovery", Path(__file__).parents[1] / "database_recovery.py")
recovery = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(recovery)


def archive_pair(tmp_path):
    archive = tmp_path / "workflow-db-test.dump"
    archive.write_bytes(b"PGDMPexample")
    manifest = {"archive": archive.name, "sha256": recovery.digest(archive), "source_image": "sha256:example"}
    archive.with_suffix(".json").write_text(json.dumps(manifest))
    return SimpleNamespace(archive=archive, evidence=tmp_path / "proof.json", startup_timeout=1)


def test_corrupt_archive_never_starts_docker(tmp_path, monkeypatch):
    args = archive_pair(tmp_path)
    args.archive.write_bytes(b"corrupt")
    monkeypatch.setattr(recovery, "docker", lambda *a, **k: pytest.fail("Docker must not start"))
    with pytest.raises(ValueError, match="SHA256"):
        recovery.rehearse(args)
    assert not args.evidence.exists()


def test_public_backup_directory_rejected(tmp_path, monkeypatch):
    tmp_path.chmod(0o755)
    monkeypatch.setattr(recovery, "docker", lambda *a, **k: pytest.fail("Docker must not start"))
    with pytest.raises(ValueError, match="private"):
        recovery.backup(SimpleNamespace(directory=tmp_path))


def test_failed_dump_removes_partial_archive(tmp_path, monkeypatch):
    tmp_path.chmod(0o700)

    def fake_docker(*args, **kwargs):
        if args[0] == "inspect":
            return SimpleNamespace(stdout="sha256:example\n")
        kwargs["stdout"].write(b"partial")
        raise subprocess.CalledProcessError(1, ["docker", "exec"])

    monkeypatch.setattr(recovery, "docker", fake_docker)
    with pytest.raises(subprocess.CalledProcessError):
        recovery.backup(SimpleNamespace(directory=tmp_path, container="synthetic", user="test", database="test"))
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("failure", ["start", "restore", "cleanup", None])
def test_restore_isolation_cleanup_and_evidence(tmp_path, monkeypatch, failure):
    args = archive_pair(tmp_path)
    calls = []

    def fake_docker(*parts, **kwargs):
        calls.append(parts)
        if (
            (failure == "start" and parts[0] == "start")
            or (failure == "cleanup" and parts[0] == "rm")
            or (failure == "restore" and "pg_restore" in parts)
        ):
            raise subprocess.CalledProcessError(1, ["docker", *parts])
        return SimpleNamespace(stdout='{"tables": 3, "constraints": 2, "database_bytes": 100}')

    monkeypatch.setattr(recovery, "docker", fake_docker)
    monkeypatch.setattr(recovery.subprocess, "run", lambda *a, **k: SimpleNamespace(returncode=0))
    if failure:
        with pytest.raises(subprocess.CalledProcessError):
            recovery.rehearse(args)
        assert not args.evidence.exists()
    else:
        recovery.rehearse(args)
        assert json.loads(args.evidence.read_text())["tables"] == 3
    create = calls[0]
    assert create[create.index("--network") + 1] == "none"
    assert "--publish" not in create and "-p" not in create
    assert "--volume" not in create and "-v" not in create
    name = create[create.index("--name") + 1]
    assert name.startswith("workflow-restore-rehearsal-")
    assert calls[-1] == ("rm", "--force", "--volumes", name)
