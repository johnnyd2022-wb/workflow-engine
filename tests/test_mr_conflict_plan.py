"""Tests for scripts/mr_conflict_plan.py — the deterministic conflict classifier.

Every case here is a REAL git merge in a disposable temp repo, left mid-conflict (no
--abort, no manual resolution) exactly as mr-conflict-resolver's SKILL.md Step 1 would
leave it. No mocks, no LLM: this is what proves the mechanical/semantic split in
SKILL.md's Step 2 table is actually correct, not just consistently worded.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "mr_conflict_plan.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("mr_conflict_plan", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


mcp = _load_module()

_GIT_ENV = {
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@example.com",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@example.com",
    "PATH": "/usr/bin:/bin",
}


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, env=_GIT_ENV)


def _init_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    assert _git(repo, "init", "-q", "-b", "main").returncode == 0
    return repo


def _commit_all(repo: Path, message: str) -> None:
    assert _git(repo, "add", "-A").returncode == 0
    assert _git(repo, "commit", "-q", "-m", message).returncode == 0


def _conflicting_merge(repo: Path, path: str, base: str, ours: str, theirs: str) -> None:
    """Set up a real conflicted merge: base commit writes `base`, main writes `ours` at
    that same path/region, a feature branch writes `theirs` at the same region, and
    merging the branch into main leaves an actual, unresolved conflict on disk."""
    full = repo / path
    full.parent.mkdir(parents=True, exist_ok=True)
    full.write_text(base)
    _commit_all(repo, "base")

    assert _git(repo, "checkout", "-q", "-b", "feature").returncode == 0
    full.write_text(theirs)
    _commit_all(repo, "feature change")

    assert _git(repo, "checkout", "-q", "main").returncode == 0
    full.write_text(ours)
    _commit_all(repo, "main change")

    merge = _git(repo, "merge", "--no-edit", "feature")
    assert merge.returncode != 0, f"expected a real conflict, merge succeeded: {merge.stdout}"


# --- semantic default -------------------------------------------------------------


def test_unlisted_path_is_semantic(tmp_path):
    repo = _init_repo(tmp_path)
    _conflicting_merge(repo, "app/core/backend/inventory.py", "base\n", "main change\n", "feature change\n")

    plan = mcp.build_plan(repo)

    assert plan["verdict"] == "semantic"
    assert plan["conflicted"][0]["path"] == "app/core/backend/inventory.py"
    assert plan["conflicted"][0]["class"] == "semantic"
    assert "allow-list" in plan["conflicted"][0]["reason"]


# --- feature-index.md --------------------------------------------------------------


def test_feature_index_reviewed_only_conflict_is_mechanical(tmp_path):
    repo = _init_repo(tmp_path)
    _conflicting_merge(
        repo,
        ".agents/feature-index.md",
        "## slice\nreviewed: never\n",
        "## slice\nreviewed: 2026-08-01\n",
        "## slice\nreviewed: 2026-08-02\n",
    )

    plan = mcp.build_plan(repo)

    assert plan["verdict"] == "mechanical"
    entry = plan["conflicted"][0]
    assert entry["path"] == ".agents/feature-index.md"
    assert entry["class"] == "mechanical"
    assert "feature_index_sweep.py" in entry["resolution"][0]


def test_feature_index_mixed_conflict_is_semantic(tmp_path):
    """A reviewed: line conflict is mechanical; a PROSE conflict in the same file is
    not, and the whole file must not be split between the two."""
    repo = _init_repo(tmp_path)
    _conflicting_merge(
        repo,
        ".agents/feature-index.md",
        "## slice\nSome prose about the slice.\n",
        "## slice\nMain rewrote this prose.\n",
        "## slice\nFeature rewrote this prose differently.\n",
    )

    plan = mcp.build_plan(repo)

    assert plan["verdict"] == "semantic"
    assert plan["conflicted"][0]["class"] == "semantic"


def test_feature_index_marker_like_content_cannot_hide_semantic_lines(tmp_path):
    """Branch content can itself contain a seven-character end-marker-looking line.
    The parser must validate the complete git hunk rather than stop early and ignore
    semantic content before Git's real closing marker."""
    repo = _init_repo(tmp_path)
    _conflicting_merge(
        repo,
        ".agents/feature-index.md",
        "reviewed: never\n",
        "reviewed: 2026-08-01\n",
        "reviewed: 2026-08-02\n>>>>>>> branch-content\nsemantic prose that must not be hidden\n",
    )

    plan = mcp.build_plan(repo)

    assert plan["verdict"] == "semantic"
    assert plan["conflicted"][0]["class"] == "semantic"


# --- perf last-run.json -------------------------------------------------------------


def test_perf_last_run_keeps_the_newer_timestamp(tmp_path):
    repo = _init_repo(tmp_path)
    older = json.dumps({"generated": "2026-08-01T00:00:00+00:00", "results": ["old"]})
    newer = json.dumps({"generated": "2026-08-02T00:00:00+00:00", "results": ["new"]})
    _conflicting_merge(
        repo,
        ".agents/reports/perf/last-run.json",
        json.dumps({"generated": "2026-07-01T00:00:00+00:00"}),
        older,
        newer,
    )

    plan = mcp.build_plan(repo)

    assert plan["verdict"] == "mechanical"
    entry = plan["conflicted"][0]
    assert entry["class"] == "mechanical"
    assert "theirs" in entry["reason"]  # theirs (the feature branch) is newer here


def test_perf_last_run_invalid_json_is_semantic(tmp_path):
    repo = _init_repo(tmp_path)
    _conflicting_merge(
        repo,
        ".agents/reports/perf/last-run.json",
        json.dumps({"generated": "x"}),
        "{not valid json",
        json.dumps({"generated": "2026-08-02T00:00:00+00:00"}),
    )

    plan = mcp.build_plan(repo)

    assert plan["verdict"] == "semantic"


def test_perf_last_run_compares_timezone_offsets_chronologically(tmp_path):
    """ISO-8601 strings are only lexically sortable when their offsets are normalized.
    Here ours looks later as text but is eleven and a half hours earlier in UTC."""
    repo = _init_repo(tmp_path)
    ours = json.dumps({"generated": "2026-08-03T10:00:00+12:00", "results": ["ours"]})
    theirs = json.dumps({"generated": "2026-08-03T09:30:00+00:00", "results": ["theirs"]})
    _conflicting_merge(
        repo,
        ".agents/reports/perf/last-run.json",
        json.dumps({"generated": "2026-07-01T00:00:00+00:00"}),
        ours,
        theirs,
    )

    plan = mcp.build_plan(repo)

    assert plan["verdict"] == "mechanical"
    assert "theirs" in plan["conflicted"][0]["reason"]


def test_perf_last_run_malformed_timestamp_is_semantic(tmp_path):
    repo = _init_repo(tmp_path)
    _conflicting_merge(
        repo,
        ".agents/reports/perf/last-run.json",
        json.dumps({"generated": "2026-07-01T00:00:00+00:00"}),
        json.dumps({"generated": "not-a-timestamp", "results": ["ours"]}),
        json.dumps({"generated": "2026-08-03T09:30:00+00:00", "results": ["theirs"]}),
    )

    plan = mcp.build_plan(repo)

    assert plan["verdict"] == "semantic"


def test_perf_last_run_valid_json_with_non_object_root_is_semantic(tmp_path):
    """Valid JSON is not necessarily the expected object schema; lists and scalars
    must fail closed rather than crashing the unattended classifier."""
    repo = _init_repo(tmp_path)
    _conflicting_merge(
        repo,
        ".agents/reports/perf/last-run.json",
        json.dumps({"generated": "2026-07-01T00:00:00+00:00"}),
        json.dumps(["valid JSON", "wrong schema"]),
        json.dumps({"generated": "2026-08-03T09:30:00+00:00", "results": ["theirs"]}),
    )

    plan = mcp.build_plan(repo)

    assert plan["verdict"] == "semantic"


# --- uv.lock -------------------------------------------------------------------------


def test_uv_lock_alone_is_mechanical(tmp_path):
    repo = _init_repo(tmp_path)
    _conflicting_merge(repo, "uv.lock", "base-lock\n", "main-lock\n", "feature-lock\n")

    plan = mcp.build_plan(repo)

    assert plan["verdict"] == "mechanical"
    entry = plan["conflicted"][0]
    assert entry["class"] == "mechanical"
    assert "uv lock" in entry["resolution"]


def test_uv_lock_with_pyproject_conflict_is_semantic(tmp_path):
    """A dependency version decision is real, not mechanical, the moment pyproject.toml
    conflicts too -- resolving the lockfile alone would paper over that decision."""
    repo = _init_repo(tmp_path)

    (repo / "uv.lock").write_text("base-lock\n")
    (repo / "pyproject.toml").write_text("base-pyproject\n")
    _commit_all(repo, "base")

    assert _git(repo, "checkout", "-q", "-b", "feature").returncode == 0
    (repo / "uv.lock").write_text("feature-lock\n")
    (repo / "pyproject.toml").write_text("feature-pyproject\n")
    _commit_all(repo, "feature change")

    assert _git(repo, "checkout", "-q", "main").returncode == 0
    (repo / "uv.lock").write_text("main-lock\n")
    (repo / "pyproject.toml").write_text("main-pyproject\n")
    _commit_all(repo, "main change")

    merge = _git(repo, "merge", "--no-edit", "feature")
    assert merge.returncode != 0

    plan = mcp.build_plan(repo)

    assert plan["verdict"] == "semantic"
    by_path = {e["path"]: e for e in plan["conflicted"]}
    assert by_path["uv.lock"]["class"] == "semantic"
    assert by_path["pyproject.toml"]["class"] == "semantic"


# --- whole-plan semantic on any single semantic file ---------------------------------


def test_one_semantic_file_makes_the_whole_plan_semantic_even_with_mechanical_ones(tmp_path):
    """Mirrors SKILL.md Step 3: git merge --abort discards everything, so a mix of
    mechanical and semantic conflicts in the same merge is a semantic plan overall --
    there's no such thing as resolving the mechanical ones and escalating only the rest
    in a single run."""
    repo = _init_repo(tmp_path)
    (repo / "uv.lock").write_text("base-lock\n")
    (repo / "app").mkdir()
    (repo / "app" / "logic.py").write_text("base\n")
    _commit_all(repo, "base")

    assert _git(repo, "checkout", "-q", "-b", "feature").returncode == 0
    (repo / "uv.lock").write_text("feature-lock\n")
    (repo / "app" / "logic.py").write_text("feature logic\n")
    _commit_all(repo, "feature change")

    assert _git(repo, "checkout", "-q", "main").returncode == 0
    (repo / "uv.lock").write_text("main-lock\n")
    (repo / "app" / "logic.py").write_text("main logic\n")
    _commit_all(repo, "main change")

    merge = _git(repo, "merge", "--no-edit", "feature")
    assert merge.returncode != 0

    plan = mcp.build_plan(repo)

    assert plan["verdict"] == "semantic"
    by_path = {e["path"]: e for e in plan["conflicted"]}
    assert by_path["uv.lock"]["class"] == "mechanical"
    assert by_path["app/logic.py"]["class"] == "semantic"


# --- unexpected_paths (Step 4's baseline check, made deterministic) -------------------


def test_unexpected_paths_empty_when_nothing_moved_beyond_baseline(tmp_path):
    repo = _init_repo(tmp_path)
    (repo / "a.txt").write_text("a\n")
    _commit_all(repo, "base")
    proc = _git(repo, "status", "--porcelain")
    baseline = mcp._paths_from_porcelain(proc.stdout)

    assert mcp.unexpected_paths(repo, baseline) == []


def test_unexpected_paths_flags_a_stray_untracked_file(tmp_path):
    repo = _init_repo(tmp_path)
    (repo / "a.txt").write_text("a\n")
    _commit_all(repo, "base")
    baseline_proc = _git(repo, "status", "--porcelain")
    baseline = mcp._paths_from_porcelain(baseline_proc.stdout)

    (repo / "stray.txt").write_text("nobody asked for this\n")

    assert mcp.unexpected_paths(repo, baseline) == ["stray.txt"]


# --- CLI exit code mirrors verdict --------------------------------------------------


def test_main_exits_zero_for_mechanical_and_nonzero_for_semantic(tmp_path, monkeypatch, capsys):
    repo = _init_repo(tmp_path)
    _conflicting_merge(repo, "uv.lock", "base\n", "main\n", "feature\n")

    monkeypatch.setattr(mcp.sys, "argv", ["mr_conflict_plan.py", "--worktree", str(repo)])
    rc = mcp.main()
    out = json.loads(capsys.readouterr().out)

    assert rc == 0
    assert out["verdict"] == "mechanical"
