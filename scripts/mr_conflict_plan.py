#!/usr/bin/env python3
"""Deterministic classifier for merge-conflicted files, matching
`.claude/skills/mr-conflict-resolver/SKILL.md` Step 2's mechanical allow-list exactly.

Why this exists: asking the model to classify a conflict as "mechanical" vs "semantic"
in prose is not something a test can verify without actually invoking the model — round
2 of this feature's review could only prove the classification story was written down
consistently, not that it would be applied correctly. This script makes the classification
itself a deterministic, testable function: run it against an ALREADY-MERGED (conflicted)
git worktree and it emits a JSON plan naming exactly which conflicted files are
mechanical (with the resolution command that applies), which are semantic, and a whole-
plan verdict. **The SKILL.md is now the reader's explanation of this script's behavior,
not an independent decision-maker** — every row of the allow-list below is exactly, and
only, what SKILL.md Step 2 documents. The agent executes this plan; it does not classify.

One conflicted file outside the allow-list makes the WHOLE plan `semantic` — never a
partial one. `git merge --abort` discards the entire merge attempt regardless of how many
files would have resolved mechanically, so there is no such thing as "resolve the
mechanical ones and escalate only the rest" in a single run (see SKILL.md Step 3).

Usage:
    python3 scripts/mr_conflict_plan.py --worktree <path>                  # print the plan
    python3 scripts/mr_conflict_plan.py --worktree <path> --baseline-file <path>
        # also report any path dirty/untracked now that wasn't in the baseline
"""

from __future__ import annotations

import argparse
import difflib
import fnmatch
import json
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

# Every row here is exactly SKILL.md Step 2's table. Adding a new mechanical case means
# updating both this list (or a new classify_* function) and that table together --
# never one without the other.
_LEDGER_UNION_PATTERNS = (".agents/metrics/*.jsonl", ".agents/history/*.jsonl")
_FEATURE_INDEX_PATH = ".agents/feature-index.md"
_PERF_LAST_RUN_PATH = ".agents/reports/perf/last-run.json"
_UV_LOCK_PATH = "uv.lock"
_PYPROJECT_PATH = "pyproject.toml"

_REVIEWED_LINE_RE = re.compile(r"^\s*reviewed:")


def _run_git(worktree: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=worktree, capture_output=True, text=True)


def conflicted_paths(worktree: Path) -> list[str]:
    """Every path git currently has marked conflicted (U/A/D) in `worktree`."""
    proc = _run_git(worktree, "diff", "--name-only", "--diff-filter=U")
    if proc.returncode != 0:
        raise RuntimeError(f"git diff --diff-filter=U failed: {proc.stderr.strip()}")
    return [line for line in proc.stdout.splitlines() if line.strip()]


def _classify_feature_index(worktree: Path, path: str) -> dict:
    """Mechanical only if EVERY line that actually differs between ours and theirs is a
    `reviewed:` line -- anything else conflicting (prose, slice tables) makes the whole
    file semantic. Doesn't split a file between mechanical and semantic treatment.

    Reads ours/theirs directly from git's own stage 2/3 objects rather than parsing
    `<<<<<<<`/`=======`/`>>>>>>>` markers out of the merged working-tree file. A
    hand-rolled marker parser is exploitable: branch CONTENT can itself contain a line
    that looks like a marker (e.g. literal prose reading `>>>>>>> some-branch-name`),
    which makes the parser treat that content line as git's real closing marker and
    silently drop everything genuine past it -- a real semantic conflict then gets
    classified mechanical. Diffing the two git-known sides directly has no such
    ambiguity: there is nothing to parse, only lines to compare, and there's no string
    that can impersonate a diff opcode.
    """
    sides: dict[str, list[str]] = {}
    for stage, label in (("2", "ours"), ("3", "theirs")):
        proc = _run_git(worktree, "show", f":{stage}:{path}")
        if proc.returncode != 0:
            return {"path": path, "class": "semantic", "reason": f"could not read {label} side: {proc.stderr.strip()}"}
        sides[label] = proc.stdout.splitlines()

    matcher = difflib.SequenceMatcher(None, sides["ours"], sides["theirs"], autojunk=False)
    changed_lines: list[str] = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue
        changed_lines.extend(sides["ours"][i1:i2])
        changed_lines.extend(sides["theirs"][j1:j2])

    if not changed_lines:
        return {
            "path": path,
            "class": "semantic",
            "reason": "no differing lines found between ours and theirs (unexpected)",
        }

    if not all(_REVIEWED_LINE_RE.match(line) for line in changed_lines):
        return {
            "path": path,
            "class": "semantic",
            "reason": "at least one differing line between ours and theirs is not a bare 'reviewed:' line",
        }

    return {
        "path": path,
        "class": "mechanical",
        "reason": "every differing line between ours and theirs is a 'reviewed:' line",
        "resolution": ["python3 scripts/feature_index_sweep.py"],
    }


def _parse_aware_timestamp(value: object) -> datetime | None:
    """Parse `value` as a timezone-AWARE ISO-8601 datetime, or None if it can't be
    trusted for a chronological comparison. ISO-8601 strings are only lexically
    sortable when every offset is identical -- `2026-08-03T10:00:00+12:00` reads as
    "later" than `2026-08-03T09:30:00+00:00` by raw string comparison while actually
    being 11.5 hours earlier in UTC. A naive (offset-less) value is rejected too: there
    is no safe way to compare it against an aware one, and guessing UTC would be a
    silent correctness bug, not a conservative default."""
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


def _classify_perf_last_run(worktree: Path, path: str) -> dict:
    """Mechanical: it's a cached measurement, not a decision -- keep whichever side has
    the newer `generated` timestamp, whole. Any timestamp this function can't parse and
    compare with confidence fails closed to semantic -- a wrong pick here silently
    discards a real measurement, which is worse than an escalation a human clears in
    five seconds."""
    sides = {}
    for stage, label in (("2", "ours"), ("3", "theirs")):
        proc = _run_git(worktree, "show", f":{stage}:{path}")
        if proc.returncode != 0:
            return {"path": path, "class": "semantic", "reason": f"could not read {label} side: {proc.stderr.strip()}"}
        try:
            decoded = json.loads(proc.stdout)
        except json.JSONDecodeError as exc:
            return {"path": path, "class": "semantic", "reason": f"{label} side is not valid JSON: {exc}"}
        if not isinstance(decoded, dict):
            # Valid JSON is not necessarily the expected object schema -- a list or a
            # bare scalar parses fine and then crashes the next .get() call. An
            # unattended classifier must fail closed here, never raise.
            return {
                "path": path,
                "class": "semantic",
                "reason": f"{label} side is valid JSON but not an object (got {type(decoded).__name__})",
            }
        sides[label] = decoded

    parsed: dict[str, datetime] = {}
    for label in ("ours", "theirs"):
        raw = sides[label].get("generated")
        dt = _parse_aware_timestamp(raw)
        if dt is None:
            return {
                "path": path,
                "class": "semantic",
                "reason": (
                    f"{label} side's 'generated' value ({raw!r}) is missing, not a string, "
                    "unparseable, or timezone-naive -- cannot compare with confidence"
                ),
            }
        parsed[label] = dt

    winner = "theirs" if parsed["theirs"] > parsed["ours"] else "ours"
    stage = "3" if winner == "theirs" else "2"
    return {
        "path": path,
        "class": "mechanical",
        "reason": f"{winner} side is newer ({sides[winner]['generated']})",
        "resolution": [f"git show :{stage}:{path} > {path}", f"git add {path}"],
    }


def _classify_uv_lock(path: str, conflicted: set[str]) -> dict:
    if _PYPROJECT_PATH in conflicted:
        return {
            "path": path,
            "class": "semantic",
            "reason": f"{_PYPROJECT_PATH} is also conflicted -- a real dependency decision, not mechanical",
        }
    return {
        "path": path,
        "class": "mechanical",
        "reason": "no pyproject.toml conflict -- regenerate the lock from the merged manifest",
        "resolution": [f"rm {path}", "uv lock", f"git add {path}"],
    }


def classify_file(worktree: Path, path: str, conflicted: set[str]) -> dict:
    """One row of SKILL.md Step 2's table, or the semantic default. `conflicted` is the
    full set of conflicted paths in this merge -- needed by the uv.lock row, which
    depends on whether a SIBLING path also conflicted."""
    if any(fnmatch.fnmatch(path, pat) for pat in _LEDGER_UNION_PATTERNS):
        # `.gitattributes` declares `merge=union` for these -- if one is still
        # conflicted here, the driver isn't doing its job. Not a safe case.
        return {"path": path, "class": "semantic", "reason": "union-merge ledger still conflicted (broken driver?)"}
    if path == _FEATURE_INDEX_PATH:
        return _classify_feature_index(worktree, path)
    if path == _PERF_LAST_RUN_PATH:
        return _classify_perf_last_run(worktree, path)
    if path == _UV_LOCK_PATH:
        return _classify_uv_lock(path, conflicted)
    return {"path": path, "class": "semantic", "reason": "not in the mechanical allow-list"}


def build_plan(worktree: Path) -> dict:
    paths = conflicted_paths(worktree)
    conflicted_set = set(paths)
    entries = [classify_file(worktree, p, conflicted_set) for p in paths]
    semantic = [e for e in entries if e["class"] == "semantic"]
    mechanical = [e for e in entries if e["class"] == "mechanical"]
    verdict = "semantic" if semantic else "mechanical"
    return {
        "conflicted": entries,
        "mechanical": mechanical,
        "semantic": semantic,
        "verdict": verdict,
    }


def _paths_from_porcelain(text: str) -> set[str]:
    """Extract bare paths from `git status --porcelain` output (format: `XY <path>`, or
    `XY orig -> new` for renames). Used identically for the saved baseline and the
    current status so the two are actually comparable."""
    out = set()
    for line in text.splitlines():
        if not line.strip():
            continue
        out.add(line[3:].split(" -> ")[-1])
    return out


def unexpected_paths(worktree: Path, baseline: set[str]) -> list[str]:
    """Every path `git status --porcelain` reports right now that wasn't in `baseline`
    (the full post-merge status captured immediately after the merge attempt, per
    SKILL.md Step 1 -- both conflicted AND cleanly auto-merged paths belong in that
    baseline). A non-empty result here is SKILL.md Step 4's "something unrelated moved"
    signal.
    """
    proc = _run_git(worktree, "status", "--porcelain")
    if proc.returncode != 0:
        raise RuntimeError(f"git status --porcelain failed: {proc.stderr.strip()}")
    current = _paths_from_porcelain(proc.stdout)
    return sorted(current - baseline)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--worktree", required=True, type=Path)
    ap.add_argument(
        "--baseline-file", type=Path, default=None, help="raw `git status --porcelain` output from Step 1's baseline"
    )
    args = ap.parse_args()

    plan = build_plan(args.worktree)

    if args.baseline_file is not None:
        baseline = _paths_from_porcelain(args.baseline_file.read_text())
        plan["unexpected_paths"] = unexpected_paths(args.worktree, baseline)

    print(json.dumps(plan, indent=2))
    return 0 if plan["verdict"] == "mechanical" else 1


if __name__ == "__main__":
    sys.exit(main())
