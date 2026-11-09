"""uv_audit blocks a merge request only on advisories it introduces; main blocks on any."""

import json

import pytest

from scripts import uv_audit_gate as gate


def _report(*pairs):
    return {
        "summary": {"audited_packages": 9, "vulnerabilities": len(pairs)},
        "vulnerabilities": [{"dependency": {"name": p}, "id": v} for p, v in pairs],
        "adverse_statuses": [],
    }


@pytest.fixture
def run(monkeypatch, tmp_path):
    def _run(head, base, base_sha="b" * 40):
        monkeypatch.setattr(gate, "audit", lambda _project: (1 if head else 0, _report(*head)))
        monkeypatch.setattr(gate, "base_findings", lambda _sha: None if base is None else set(base))
        monkeypatch.setattr(gate, "deps_changed", lambda _base: False)  # these MRs don't touch uv.lock
        argv = ["--out", str(tmp_path / "out.json")] + (["--base", base_sha] if base_sha else [])
        return gate.main(argv)

    return _run


def test_advisory_already_on_target_branch_only_warns(run, capsys):
    """The 2026-10/11 pattern: one new advisory turned every open MR red at once."""
    assert run([("pypdf", "GHSA-1")], [("pypdf", "GHSA-1")]) == gate.WARN == 3
    assert "EXISTING pypdf: GHSA-1" in capsys.readouterr().out


def test_advisory_the_mr_introduces_blocks(run, capsys):
    assert run([("pypdf", "GHSA-1"), ("jwt", "GHSA-2")], [("pypdf", "GHSA-1")]) == 1
    out = capsys.readouterr().out
    assert "NEW      jwt: GHSA-2" in out and "EXISTING pypdf: GHSA-1" in out


def test_same_advisory_id_on_a_different_package_counts_as_new(run):
    assert run([("other", "GHSA-1")], [("pypdf", "GHSA-1")]) == 1


def test_base_that_cannot_be_audited_fails_closed(run, capsys):
    assert run([("pypdf", "GHSA-1")], None) == 1
    assert "fail closed" in capsys.readouterr().out


def test_main_blocks_on_any_advisory(run):
    assert run([("pypdf", "GHSA-1")], [("pypdf", "GHSA-1")], base_sha="") == 1


@pytest.mark.parametrize("base_sha", ["", "b" * 40])
def test_clean_audit_passes_and_writes_the_report(run, tmp_path, base_sha):
    assert run([], [], base_sha=base_sha) == 0
    assert json.loads((tmp_path / "out.json").read_text())["summary"]["vulnerabilities"] == 0


def test_unparseable_audit_output_fails(monkeypatch, tmp_path):
    monkeypatch.setattr(gate, "audit", lambda _project: (2, {}))
    assert gate.main(["--out", str(tmp_path / "o.json"), "--base", "b" * 40]) == 1


def test_ci_job_allows_only_the_warning_exit_code():
    text = open(gate.Path(__file__).resolve().parents[1] / ".gitlab-ci.yml").read()
    job = text.split("\nuv_audit:\n", 1)[1].split("\n\n", 1)[0]
    assert "scripts/uv_audit_gate.py" in job
    assert "exit_codes: [3]" in job
    assert "allow_failure: false" not in job and "allow_failure: true" not in job


# --- the scan's own exit code (review round 1: a non-zero run with an empty summary passed) ---


@pytest.mark.parametrize("base_sha", ["", "b" * 40])
def test_a_scan_that_exits_outside_0_and_1_fails_closed_even_with_no_findings(tmp_path, monkeypatch, base_sha):
    import os

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    stub = bin_dir / "uv"
    stub.write_text('#!/bin/sh\necho \'{"summary": {"audited_packages": 0}, "vulnerabilities": []}\'\nexit 2\n')
    stub.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}:{os.environ['PATH']}")
    argv = ["--out", str(tmp_path / "o.json")] + (["--base", base_sha] if base_sha else [])
    assert gate.main(argv) == 1


def test_exit_1_with_no_findings_is_not_trusted():
    assert gate.distrust(1, _report()) == "exited 1 but reported no findings"
    assert gate.distrust(0, _report()) is None
    assert gate.distrust(1, _report(("pypdf", "GHSA-1"))) is None
    assert gate.distrust(2, _report(("pypdf", "GHSA-1"))) == "exited 2"
    assert gate.distrust(0, {}) == "produced no report (exit 0)"


def test_base_audit_that_exits_badly_fails_closed(monkeypatch):
    monkeypatch.setattr(gate.subprocess, "run", lambda *a, **k: gate.subprocess.CompletedProcess(a, 0, "x", ""))
    monkeypatch.setattr(gate, "audit", lambda _p: (2, _report()))
    assert gate.base_findings("b" * 40) is None


# --- an MR that re-locks dependencies is also judged against the target's tip ---


@pytest.fixture
def relock(monkeypatch, tmp_path):
    def _run(head, base, tip, *, deps_changed=True, target="FETCH_HEAD"):
        monkeypatch.setattr(gate, "audit", lambda _project: (1 if head else 0, _report(*head)))
        sets = {"b" * 40: base, "FETCH_HEAD": tip}
        monkeypatch.setattr(gate, "base_findings", lambda ref: None if sets.get(ref) is None else set(sets[ref]))
        monkeypatch.setattr(gate, "deps_changed", lambda _base: deps_changed)
        return gate.main(["--out", str(tmp_path / "o.json"), "--base", "b" * 40, "--target", target])

    return _run


def test_relocked_mr_reintroducing_an_advisory_the_target_has_fixed_blocks(relock):
    """Branched before main bumped pypdf, then re-locked the old version: not pre-existing any more."""
    assert relock([("pypdf", "GHSA-1")], base=[("pypdf", "GHSA-1")], tip=[]) == 1


def test_relocked_mr_with_an_advisory_still_on_the_target_only_warns(relock):
    assert relock([("pypdf", "GHSA-1")], base=[("pypdf", "GHSA-1")], tip=[("pypdf", "GHSA-1")]) == gate.WARN


def test_relocked_mr_without_a_target_tip_fails_closed(relock):
    assert relock([("pypdf", "GHSA-1")], base=[("pypdf", "GHSA-1")], tip=None) == 1
    assert relock([("pypdf", "GHSA-1")], base=[("pypdf", "GHSA-1")], tip=[("pypdf", "GHSA-1")], target="") == 1


def test_mr_that_leaves_dependencies_alone_ignores_the_target_tip(relock):
    """Untouched pyproject/uv.lock: every head advisory came from the base by construction."""
    assert relock([("pypdf", "GHSA-1")], base=[("pypdf", "GHSA-1")], tip=None, deps_changed=False) == gate.WARN
