#!/usr/bin/env python3
"""Find worktrees (herdr-launched, entrypoint-queued, or plain `git worktree add`) whose
branch's MR is already merged, and remove them -- tactfully.

`/entrypoint` cuts a fresh worktree + branch per code task off `origin/main` (Step 4 of
`.claude/skills/entrypoint/SKILL.md`) and says, in prose only, that once the MR merges "the
worktree should go". Nothing ever did that. This is the tool: deterministic, no LLM involved,
reusing the same "ask glab what became of a branch" lookup skill_metrics.py already built for
the evaluation ledger (`glab_resolve_ref`).

Safety model -- read this before trusting `--apply`:

  A worktree is only ever a REMOVE candidate when *all* of these hold:
    - glab confirms its MR state is "merged" (not "closed", not "opened", not unknown)
    - the branch tip is confirmed an ancestor of origin/main (a second, independent signal --
      this repo doesn't squash-merge, so a real merge and a genuine ancestor should always
      agree; disagreement is itself evidence something's off, not something to paper over)
    - the worktree has no uncommitted changes (staged, unstaged, or untracked)
    - the branch has an upstream and no unpushed commits
    - it isn't git-locked, isn't detached, isn't main/master, isn't the current checkout

  Everything close-but-not-clean (merged-but-dirty, merged-but-ancestry-disagrees, an MR that
  closed without merging) lands in `needs_human`, never `remove_candidates`. Live-tested
  against this repo: three worktrees with genuinely merged MRs (feat/session-sweep,
  review/compliance-checks, review/process-design) all currently carry uncommitted changes --
  exactly the case this safety model exists for.

  `--apply` re-verifies every item live, immediately before touching it (a report can be
  minutes old by the time a human acts on it). Removal never passes a force flag
  (`herdr worktree remove` without `--force`, `git worktree remove` without `--force`,
  `git branch -d` not `-D`) -- git's and herdr's own guards are a second backstop if this
  script's own checks are ever wrong. Nothing here ever touches a remote branch; GitLab
  already deletes the remote branch on merge (`force_remove_source_branch` on this project's
  MRs), so cleanup here is local-only: the worktree, the local branch ref, and
  `git fetch --prune` for stale remote-tracking refs.

Usage:
    python3 scripts/worktree_sweep.py                 # human-readable report, changes nothing
    python3 scripts/worktree_sweep.py --json           # machine-readable report
    python3 scripts/worktree_sweep.py --apply           # remove every current remove_candidate
    python3 scripts/worktree_sweep.py --apply <path>...  # remove only these (still re-verified)

Exit codes: 0 = ran cleanly (including "found nothing to do"), 1 = a real error (not a git
repo, `--apply` had a failure removing something it re-verified as safe).
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

PROTECTED_BRANCHES = {"main", "master"}

_TRACKING_RE = re.compile(r"^(?P<branch>\S+?)(?:\.\.\.(?P<upstream>\S+))?(?:\s+\[(?P<info>[^\]]*)\])?$")


def _import_glab_resolver() -> tuple[Any, Any]:
    """Reuse skill_metrics.py's glab lookup rather than a second, differently-broken copy of
    it. Optional: a missing/broken skill_metrics.py degrades to "can't verify any MR", not a
    crash -- see the `glab_available` fallback below."""
    try:
        import skill_metrics  # noqa: PLC0415 -- optional dependency of the glab lookup only

        return skill_metrics.glab_resolve_ref, skill_metrics.glab_available
    except ImportError:
        return (lambda ref: None), (lambda: False)


glab_resolve_ref, glab_available = _import_glab_resolver()


# --- data shapes -------------------------------------------------------------------------


@dataclass
class WorktreeEntry:
    path: str
    branch: str | None
    head: str
    locked: bool = False
    lock_reason: str | None = None


@dataclass
class WorktreeStatus:
    dirty: bool
    ahead: int
    behind: int
    has_upstream: bool


@dataclass
class Classification:
    path: str
    branch: str | None
    bucket: str  # "remove_candidates" | "needs_human" | "informational"
    reason: str
    mr_state: str | None = None
    herdr_workspace: str | None = None


@dataclass
class SweepReport:
    generated_at: str
    warnings: list[str] = field(default_factory=list)
    remove_candidates: list[Classification] = field(default_factory=list)
    needs_human: list[Classification] = field(default_factory=list)
    informational: list[Classification] = field(default_factory=list)


# --- pure parsers (no subprocess -- unit-testable on fixed strings) ----------------------


def parse_worktree_porcelain(text: str) -> list[WorktreeEntry]:
    """Parse `git worktree list --porcelain` output. Blocks are separated by blank lines;
    each block is one worktree. `detached` (bare keyword, no value) means no branch."""
    entries: list[WorktreeEntry] = []
    block: dict[str, str] = {}

    def flush() -> None:
        path = block.get("worktree")
        if not path:
            return
        if "detached" in block:
            branch = None
        else:
            branch_ref = block.get("branch")
            branch = branch_ref.removeprefix("refs/heads/") if branch_ref else None
        entries.append(
            WorktreeEntry(
                path=path,
                branch=branch,
                head=block.get("HEAD", ""),
                locked="locked" in block,
                lock_reason=block.get("locked") or None,
            )
        )

    for line in text.splitlines():
        if not line.strip():
            flush()
            block = {}
            continue
        if line.startswith("worktree "):
            block["worktree"] = line[len("worktree ") :].strip()
        elif line.startswith("HEAD "):
            block["HEAD"] = line[len("HEAD ") :].strip()
        elif line.startswith("branch "):
            block["branch"] = line[len("branch ") :].strip()
        elif line == "detached":
            block["detached"] = ""
        elif line.startswith("locked"):
            block["locked"] = line[len("locked") :].strip()
        # "prunable", "bare" and anything else: not needed for classification, ignored.
    flush()
    return entries


def parse_status_branch(text: str) -> WorktreeStatus:
    """Parse `git status --porcelain=v1 --branch` output. Any file line at all (including
    untracked `??`) counts as dirty -- deliberately conservative: an untracked file might be
    forgotten work, and a false "needs_human" costs a glance while a false "safe to remove"
    costs the file."""
    lines = text.splitlines()
    if not lines or not lines[0].startswith("##"):
        return WorktreeStatus(dirty=True, ahead=0, behind=0, has_upstream=False)
    header = lines[0][2:].strip()
    dirty = any(line.strip() for line in lines[1:])
    if header.startswith("HEAD (no branch)"):
        return WorktreeStatus(dirty=dirty, ahead=0, behind=0, has_upstream=False)
    m = _TRACKING_RE.match(header)
    has_upstream = bool(m and m.group("upstream"))
    ahead = behind = 0
    if m and m.group("info"):
        am = re.search(r"ahead (\d+)", m.group("info"))
        bm = re.search(r"behind (\d+)", m.group("info"))
        ahead = int(am.group(1)) if am else 0
        behind = int(bm.group(1)) if bm else 0
    return WorktreeStatus(dirty=dirty, ahead=ahead, behind=behind, has_upstream=has_upstream)


# --- classification (pure decision table -- the safety-critical part) --------------------


def classify(
    *,
    branch: str | None,
    locked: bool,
    lock_reason: str | None,
    is_current: bool,
    dirty: bool,
    ahead: int,
    has_upstream: bool,
    mr_state: str | None,
    ancestry_ok: bool | None,
) -> tuple[str, str]:
    """Returns (bucket, reason). Ordered most-protective-first: every early return is a
    reason to never touch this worktree, regardless of what the MR/merge signals say."""
    if branch is None:
        return "informational", "detached HEAD -- no branch to check for a merged MR"
    if branch in PROTECTED_BRANCHES:
        return "informational", f"protected branch name ({branch}) -- never touched"
    if is_current:
        return "informational", "currently checked out in the primary worktree"
    if locked:
        reason = f"git-locked ({lock_reason})" if lock_reason else "git-locked"
        return "informational", f"{reason} -- never touched regardless of merge status"
    if mr_state is None:
        return "informational", "no MR found for this branch (glab has no record, or glab is unavailable)"
    if mr_state != "merged":
        return "needs_human", f"MR state is {mr_state!r} (not merged) -- left for a human call"
    if dirty:
        return "needs_human", "MR merged but the worktree has uncommitted changes -- check before removing"
    if not has_upstream:
        return (
            "needs_human",
            "MR merged but branch has no upstream tracking ref -- can't confirm nothing is stranded locally-only",
        )
    if ahead > 0:
        return "needs_human", f"MR merged but {ahead} local commit(s) not pushed to its remote branch"
    if ancestry_ok is not True:
        return (
            "needs_human",
            "MR merged per GitLab but branch tip is not confirmed as an ancestor of origin/main -- signals disagree",
        )
    return "remove_candidates", "MR merged, branch is an ancestor of origin/main, worktree is clean"


# --- subprocess-backed gathering ----------------------------------------------------------


def _run(args: list[str], cwd: Path, timeout: int = 30) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, cwd=cwd, capture_output=True, text=True, timeout=timeout)


def list_worktrees(repo_root: Path) -> list[WorktreeEntry]:
    proc = _run(["git", "worktree", "list", "--porcelain"], repo_root)
    if proc.returncode != 0:
        raise RuntimeError(f"git worktree list failed: {proc.stderr.strip()}")
    return parse_worktree_porcelain(proc.stdout)


def worktree_status(path: Path) -> WorktreeStatus:
    proc = _run(["git", "status", "--porcelain=v1", "--branch"], path)
    if proc.returncode != 0:
        # can't read status -- treat as dirty, never as safe to remove
        return WorktreeStatus(dirty=True, ahead=0, behind=0, has_upstream=False)
    return parse_status_branch(proc.stdout)


def is_ancestor(repo_root: Path, branch: str, target: str = "origin/main") -> bool | None:
    proc = _run(["git", "merge-base", "--is-ancestor", branch, target], repo_root)
    if proc.returncode in (0, 1):
        return proc.returncode == 0
    return None  # unknown ref or other failure -- can't evaluate, not "no"


def current_branch(repo_root: Path) -> str | None:
    proc = _run(["git", "branch", "--show-current"], repo_root)
    branch = proc.stdout.strip()
    return branch or None


def herdr_open_workspaces(repo_root: Path) -> dict[str, str]:
    """path -> open workspace_id, for worktrees herdr currently has a live pane on. Empty
    dict (not an error) if herdr isn't installed or the call fails -- plain `git worktree
    remove` is always the fallback."""
    if not shutil.which("herdr"):
        return {}
    try:
        proc = _run(["herdr", "worktree", "list", "--json"], repo_root, timeout=15)
    except (OSError, subprocess.SubprocessError):
        return {}
    if proc.returncode != 0:
        return {}
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return {}
    out: dict[str, str] = {}
    for wt in data.get("result", {}).get("worktrees", []):
        ws = wt.get("open_workspace_id")
        if ws:
            out[wt["path"]] = ws
    return out


def gather(repo_root: Path) -> SweepReport:
    report = SweepReport(generated_at=datetime.now(UTC).isoformat(timespec="seconds"))
    resolved_root = repo_root.resolve()

    # Read-only (fetch never moves a local branch), but load-bearing for the ancestry check
    # below: a stale local origin/main understates what's actually merged, which only ever
    # makes this run *more* conservative (a just-merged branch parks in needs_human instead
    # of remove_candidates) -- never the reverse, so skipping this on failure is safe too.
    fetch = _run(["git", "fetch", "origin", "main"], repo_root, timeout=30)
    if fetch.returncode != 0:
        report.warnings.append(
            f"git fetch origin main failed -- ancestry checks may be using a stale origin/main: {fetch.stderr.strip()}"
        )

    entries = list_worktrees(repo_root)
    cur = current_branch(repo_root)
    herdr_ws = herdr_open_workspaces(repo_root)
    glab_ok = glab_available()
    if not glab_ok:
        report.warnings.append("glab unavailable or unauthenticated -- no MR status could be verified this run")

    for e in entries:
        if Path(e.path).resolve() == resolved_root:
            continue  # never consider the primary worktree

        status = worktree_status(Path(e.path))
        is_current = bool(cur) and e.branch == cur

        mr_state = None
        ancestry_ok = None
        if e.branch and not e.locked and glab_ok:
            mr_state = glab_resolve_ref(e.branch)
            if mr_state == "merged":
                ancestry_ok = is_ancestor(repo_root, e.branch)

        bucket, reason = classify(
            branch=e.branch,
            locked=e.locked,
            lock_reason=e.lock_reason,
            is_current=is_current,
            dirty=status.dirty,
            ahead=status.ahead,
            has_upstream=status.has_upstream,
            mr_state=mr_state,
            ancestry_ok=ancestry_ok,
        )
        classification = Classification(
            path=e.path,
            branch=e.branch,
            bucket=bucket,
            reason=reason,
            mr_state=mr_state,
            herdr_workspace=herdr_ws.get(e.path),
        )
        getattr(report, bucket).append(classification)

    return report


# --- apply (the only mutating path) -------------------------------------------------------


def remove_one(repo_root: Path, classification: Classification) -> tuple[bool, str]:
    """Never passes a force flag anywhere in this function -- see module docstring."""
    path = classification.path
    branch = classification.branch
    assert branch is not None  # classify() never puts a detached entry in remove_candidates

    if classification.herdr_workspace and shutil.which("herdr"):
        proc = _run(["herdr", "worktree", "remove", "--workspace", classification.herdr_workspace], repo_root)
    else:
        proc = _run(["git", "worktree", "remove", path], repo_root)
    if proc.returncode != 0:
        return False, f"worktree removal failed: {(proc.stderr or proc.stdout).strip()}"

    bproc = _run(["git", "branch", "-d", branch], repo_root)
    if bproc.returncode != 0:
        return (
            False,
            f"worktree removed, but branch delete failed (git refused -- check manually): {(bproc.stderr or bproc.stdout).strip()}",
        )

    return True, "removed worktree and deleted local branch"


def apply_removals(repo_root: Path, requested_paths: list[str] | None) -> dict[str, Any]:
    """Re-gathers fresh (never trusts an earlier report) and only ever acts on whatever is a
    remove_candidate *right now*. A path requested that no longer qualifies is skipped with
    the current reason, not forced through."""
    fresh = gather(repo_root)
    candidates_by_path = {c.path: c for c in fresh.remove_candidates}
    stale_by_path = {c.path: c for c in (fresh.needs_human + fresh.informational)}

    targets = requested_paths if requested_paths else list(candidates_by_path)

    removed: list[dict[str, str]] = []
    failed: list[dict[str, str]] = []
    skipped: list[dict[str, str]] = []

    for path in targets:
        classification = candidates_by_path.get(path)
        if classification is None:
            stale = stale_by_path.get(path)
            reason = stale.reason if stale else "not a known worktree as of this run"
            skipped.append({"path": path, "reason": f"no longer a safe remove-candidate: {reason}"})
            continue
        ok, message = remove_one(repo_root, classification)
        record = {"path": path, "branch": classification.branch or "", "message": message}
        (removed if ok else failed).append(record)

    if removed:
        _run(["git", "fetch", "--prune"], repo_root, timeout=60)

    return {"removed": removed, "failed": failed, "skipped": skipped}


# --- rendering -----------------------------------------------------------------------------


def _fmt_entry(c: Classification) -> str:
    branch = c.branch or "(detached)"
    return f"  {branch}\n    path:   {c.path}\n    reason: {c.reason}"


def _render_bucket(lines: list[str], title: str, items: list[Classification]) -> None:
    lines.append(f"{title} ({len(items)}):")
    if items:
        lines.extend(_fmt_entry(c) for c in items)
    else:
        lines.append("  (none)")
    lines.append("")


def render_human(report: SweepReport) -> str:
    lines: list[str] = [f"worktree sweep @ {report.generated_at}"]
    for w in report.warnings:
        lines.append(f"  ⚠ {w}")
    lines.append("")
    _render_bucket(lines, "remove_candidates", report.remove_candidates)
    _render_bucket(lines, "needs_human", report.needs_human)
    _render_bucket(lines, "informational, left alone", report.informational)
    return "\n".join(lines).rstrip("\n")


def report_to_dict(report: SweepReport) -> dict[str, Any]:
    def _c(c: Classification) -> dict[str, Any]:
        return {
            "path": c.path,
            "branch": c.branch,
            "reason": c.reason,
            "mr_state": c.mr_state,
            "herdr_workspace": c.herdr_workspace,
        }

    return {
        "generated_at": report.generated_at,
        "warnings": report.warnings,
        "remove_candidates": [_c(c) for c in report.remove_candidates],
        "needs_human": [_c(c) for c in report.needs_human],
        "informational": [_c(c) for c in report.informational],
    }


# --- CLI -------------------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--json", action="store_true", help="machine-readable report")
    ap.add_argument(
        "--apply",
        nargs="*",
        default=None,
        metavar="PATH",
        help="remove worktrees that are (freshly re-verified as) safe -- no PATH args means every current remove_candidate",
    )
    args = ap.parse_args(argv)

    try:
        if args.apply is not None:
            result = apply_removals(REPO_ROOT, args.apply or None)
            if args.json:
                print(json.dumps(result, indent=2))
            else:
                for r in result["removed"]:
                    print(f"  removed: {r['branch']} ({r['path']})")
                for r in result["skipped"]:
                    print(f"  skipped: {r['path']} -- {r['reason']}")
                for r in result["failed"]:
                    print(f"  FAILED:  {r['path']} -- {r['message']}", file=sys.stderr)
                if not (result["removed"] or result["skipped"] or result["failed"]):
                    print("  nothing to apply -- no remove_candidates")
            return 1 if result["failed"] else 0

        report = gather(REPO_ROOT)
        print(json.dumps(report_to_dict(report), indent=2) if args.json else render_human(report))
        return 0
    except RuntimeError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
