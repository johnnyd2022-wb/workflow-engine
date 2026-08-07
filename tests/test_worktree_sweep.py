"""Unit tests for scripts/worktree_sweep.py -- the herdr/entrypoint worktree cleanup tool.

The one thing this tool must never do is delete uncommitted work. Live-tested against the
real repo before these were written: three worktrees with genuinely merged MRs
(feat/session-sweep, review/compliance-checks, review/process-design) all currently carry
uncommitted changes. `test_dirty_worktree_never_becomes_remove_candidate_even_when_merged`
and `test_apply_refuses_dirty_worktree_even_if_requested` pin exactly that case against a
real, disposable git repo -- not a mock -- so a future change to the classifier can't
silently regress it.

glab and herdr are never shelled out to under test: `glab_resolve_ref`/`glab_available`/
`herdr_open_workspaces` are monkeypatched, same "resolver is injected" principle
test_skill_metrics.py uses for skill_metrics.sweep().
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

# Registered in sys.modules *before* exec: worktree_sweep.py uses `from __future__ import
# annotations`, and @dataclass resolves its field types through `sys.modules[cls.__module__]`,
# which is None for a module that isn't registered yet (see tests/test_session_sweep.py).
_SPEC = importlib.util.spec_from_file_location(
    "worktree_sweep", Path(__file__).resolve().parents[1] / "scripts" / "worktree_sweep.py"
)
worktree_sweep = importlib.util.module_from_spec(_SPEC)
sys.modules["worktree_sweep"] = worktree_sweep
_SPEC.loader.exec_module(worktree_sweep)

_WATCH_SPEC = importlib.util.spec_from_file_location(
    "worktree_sweep_watch", Path(__file__).resolve().parents[1] / "scripts" / "worktree_sweep_watch.py"
)
worktree_sweep_watch = importlib.util.module_from_spec(_WATCH_SPEC)
_WATCH_SPEC.loader.exec_module(worktree_sweep_watch)


# --- porcelain / status parser tests ------------------------------------------------------

PORCELAIN_FIXTURE = """\
worktree /repo
HEAD aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
branch refs/heads/main

worktree /repo/../wt-feature
HEAD bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb
branch refs/heads/feat/x

worktree /repo/../wt-locked
HEAD cccccccccccccccccccccccccccccccccccccccc
branch refs/heads/y
locked claude session findings-index (pid 123)

worktree /repo/../wt-detached
HEAD dddddddddddddddddddddddddddddddddddddddd
detached
"""


def test_parse_worktree_porcelain_counts_all_blocks():
    entries = worktree_sweep.parse_worktree_porcelain(PORCELAIN_FIXTURE)
    assert len(entries) == 4


def test_parse_worktree_porcelain_reads_branch_names():
    entries = worktree_sweep.parse_worktree_porcelain(PORCELAIN_FIXTURE)
    branches = {e.branch for e in entries}
    assert branches == {"main", "feat/x", "y", None}


def test_parse_worktree_porcelain_captures_lock_reason():
    entries = worktree_sweep.parse_worktree_porcelain(PORCELAIN_FIXTURE)
    locked = [e for e in entries if e.locked]
    assert len(locked) == 1
    assert "pid 123" in locked[0].lock_reason


def test_parse_worktree_porcelain_detached_has_no_branch():
    entries = worktree_sweep.parse_worktree_porcelain(PORCELAIN_FIXTURE)
    detached = [e for e in entries if e.branch is None]
    assert len(detached) == 1
    assert detached[0].locked is False


def test_parse_status_branch_clean_in_sync():
    s = worktree_sweep.parse_status_branch("## feat/x...origin/feat/x\n")
    assert s.dirty is False
    assert s.has_upstream is True
    assert (s.ahead, s.behind) == (0, 0)


def test_parse_status_branch_dirty_modified_file():
    s = worktree_sweep.parse_status_branch("## feat/x...origin/feat/x\n M app/foo.py\n")
    assert s.dirty is True


def test_parse_status_branch_dirty_on_untracked_file_alone():
    s = worktree_sweep.parse_status_branch("## feat/x...origin/feat/x\n?? scratch.txt\n")
    assert s.dirty is True


def test_parse_status_branch_ahead_and_behind():
    s = worktree_sweep.parse_status_branch("## feat/x...origin/feat/x [ahead 1, behind 3]\n")
    assert (s.ahead, s.behind) == (1, 3)


def test_parse_status_branch_no_upstream():
    s = worktree_sweep.parse_status_branch("## feat/x\n")
    assert s.has_upstream is False


def test_parse_status_branch_detached_head():
    s = worktree_sweep.parse_status_branch("## HEAD (no branch)\n")
    assert s.has_upstream is False
    assert s.dirty is False


def test_parse_status_branch_missing_header_is_treated_as_dirty():
    """No `##` line at all shouldn't happen from real git, but if it ever does, fail safe."""
    s = worktree_sweep.parse_status_branch("")
    assert s.dirty is True


# --- classify() truth table ---------------------------------------------------------------

_CLEAN_MERGED = dict(
    branch="feat/x",
    locked=False,
    lock_reason=None,
    is_current=False,
    dirty=False,
    ahead=0,
    has_upstream=True,
    mr_state="merged",
    ancestry_ok=True,
)


@pytest.mark.parametrize(
    ("overrides", "expected_bucket"),
    [
        ({}, "remove_candidates"),
        ({"branch": None}, "informational"),
        ({"branch": "main"}, "informational"),
        ({"branch": "master"}, "informational"),
        ({"is_current": True}, "informational"),
        ({"locked": True, "lock_reason": "claude session (pid 1)"}, "informational"),
        ({"mr_state": None}, "informational"),
        ({"mr_state": "closed"}, "needs_human"),
        ({"dirty": True}, "needs_human"),
        ({"has_upstream": False}, "needs_human"),
        ({"ahead": 2}, "needs_human"),
        ({"ancestry_ok": False}, "needs_human"),
        ({"ancestry_ok": None}, "needs_human"),
    ],
    ids=[
        "clean-merged-is-a-candidate",
        "detached-head",
        "protected-main",
        "protected-master",
        "current-checkout",
        "locked",
        "no-mr-found",
        "mr-closed-not-merged",
        "dirty-worktree",
        "no-upstream",
        "unpushed-commits",
        "ancestry-disagrees",
        "ancestry-unknown",
    ],
)
def test_classify_truth_table(overrides, expected_bucket):
    kwargs = {**_CLEAN_MERGED, **overrides}
    bucket, reason = worktree_sweep.classify(**kwargs)
    assert bucket == expected_bucket, f"reason was: {reason}"


def test_classify_lock_wins_over_dirty_and_unmerged():
    """Locked is checked before mr_state/dirty -- a locked worktree is never touched even
    when it also looks unmerged and dirty, because the lock is a human-set signal."""
    bucket, reason = worktree_sweep.classify(
        branch="y",
        locked=True,
        lock_reason="pid 123",
        is_current=False,
        dirty=True,
        ahead=5,
        has_upstream=False,
        mr_state=None,
        ancestry_ok=None,
    )
    assert bucket == "informational"
    assert "lock" in reason.lower()


# --- real, disposable git repo (no mocks) --------------------------------------------------


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "test",
        "GIT_AUTHOR_EMAIL": "test@test.invalid",
        "GIT_COMMITTER_NAME": "test",
        "GIT_COMMITTER_EMAIL": "test@test.invalid",
    }
    return subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True, env=env)


@pytest.fixture
def real_repo(tmp_path, monkeypatch):
    """A real origin + main checkout + a feature branch worked in its own worktree (mirrors
    entrypoint's own flow), merged into main with --no-ff (this repo doesn't squash-merge) and
    pushed -- so `origin/main` genuinely contains the merge and ancestry checks are real."""
    origin = tmp_path / "origin.git"
    subprocess.run(["git", "init", "--bare", "-q", str(origin)], check=True, capture_output=True, text=True)

    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "remote", "add", "origin", str(origin))
    (repo / "f.txt").write_text("hello\n")
    _git(repo, "add", "f.txt")
    _git(repo, "commit", "-q", "-m", "init")
    _git(repo, "push", "-q", "origin", "main")

    wt = tmp_path / "wt-feature"
    _git(repo, "worktree", "add", "-q", "-b", "feat/x", str(wt), "main")
    (wt / "g.txt").write_text("feature\n")
    _git(wt, "add", "g.txt")
    _git(wt, "commit", "-q", "-m", "feature work")
    # a real branch is pushed (upstream tracking set) before its MR can be opened at all --
    # mirror that so has_upstream comes out True the way it would for any real merged branch
    _git(wt, "push", "-q", "-u", "origin", "feat/x")

    _git(repo, "merge", "--no-ff", "-q", "-m", "merge feat/x", "feat/x")
    _git(repo, "push", "-q", "origin", "main")
    _git(repo, "fetch", "-q", "origin")

    monkeypatch.setattr(worktree_sweep, "glab_available", lambda: True)
    monkeypatch.setattr(worktree_sweep, "glab_resolve_ref", lambda ref: "merged" if ref == "feat/x" else None)
    monkeypatch.setattr(worktree_sweep, "herdr_open_workspaces", lambda repo_root: {})

    return repo, wt


def test_clean_merged_worktree_is_a_remove_candidate(real_repo):
    repo, wt = real_repo
    report = worktree_sweep.gather(repo)
    assert any(c.path == str(wt) and c.branch == "feat/x" for c in report.remove_candidates)
    assert report.needs_human == []


def test_dirty_worktree_never_becomes_remove_candidate_even_when_merged(real_repo):
    repo, wt = real_repo
    (wt / "scratch.txt").write_text("uncommitted work\n")
    report = worktree_sweep.gather(repo)
    assert not any(c.path == str(wt) for c in report.remove_candidates)
    assert any(c.path == str(wt) for c in report.needs_human)


def test_apply_removes_clean_merged_worktree_and_deletes_branch(real_repo):
    repo, wt = real_repo
    result = worktree_sweep.apply_removals(repo, [str(wt)])
    assert result["failed"] == []
    assert len(result["removed"]) == 1
    assert not wt.exists()
    remaining = _git(repo, "branch", "--list", "feat/x").stdout
    assert "feat/x" not in remaining


def test_apply_refuses_dirty_worktree_even_if_explicitly_requested(real_repo):
    repo, wt = real_repo
    (wt / "scratch.txt").write_text("uncommitted work\n")
    result = worktree_sweep.apply_removals(repo, [str(wt)])
    assert result["removed"] == []
    assert len(result["skipped"]) == 1
    assert wt.exists()
    remaining = _git(repo, "branch", "--list", "feat/x").stdout
    assert "feat/x" in remaining


def test_apply_with_no_paths_targets_every_current_candidate(real_repo):
    repo, wt = real_repo
    result = worktree_sweep.apply_removals(repo, None)
    assert result["failed"] == []
    assert [r["path"] for r in result["removed"]] == [str(wt)]


# --- unattended watcher ---------------------------------------------------------------


def test_watcher_dry_run_does_not_consume_notification_state(tmp_path, monkeypatch):
    state_path = tmp_path / "state.json"
    lock_path = tmp_path / "state.lock"
    report_dir = tmp_path / "reports"
    report_path = report_dir / "latest.json"
    state_path.write_text(json.dumps({"notified_branches": []}))

    candidate = worktree_sweep.Classification(
        path="/tmp/wt-feature",
        branch="feat/example",
        bucket="remove_candidates",
        reason="safe fixture",
        mr_state="merged",
    )
    report = worktree_sweep.SweepReport(
        generated_at="2026-08-07T00:00:00+00:00",
        remove_candidates=[candidate],
    )
    monkeypatch.setattr(worktree_sweep_watch, "STATE_PATH", state_path)
    monkeypatch.setattr(worktree_sweep_watch, "LOCK_PATH", lock_path)
    monkeypatch.setattr(worktree_sweep_watch, "REPORT_DIR", report_dir)
    monkeypatch.setattr(worktree_sweep_watch, "REPORT_PATH", report_path)
    monkeypatch.setattr(worktree_sweep_watch.worktree_sweep, "gather", lambda repo: report)

    assert worktree_sweep_watch.main(["--dry-run"]) == 0

    assert json.loads(state_path.read_text())["notified_branches"] == []
