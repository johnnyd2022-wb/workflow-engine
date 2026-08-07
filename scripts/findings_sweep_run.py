#!/usr/bin/env python3
"""Daily timer entrypoint: refresh the findings index, then work it off if affordable.

Why this is a script and not just an `ExecStart=claude -p ...` line: **the expensive part
must be conditional on the cheap part.** Refreshing the index costs nothing (ripgrep and
a markdown parser), and most days it will report that the budget is zero or that there is
nothing outstanding. Launching a model to discover that would cost real quota for no
work. So the order is always: sweep, decide, and only then spend.

    sweep (free)  ->  budget == 0 or nothing open  ->  exit 0, nothing spent
                  ->  budget >= 1 and work exists  ->  cut a worktree, run the skill

The worktree matters as much as the budget. This runs unattended against whatever branch
the main checkout happens to be sitting on, and the skill it launches edits code and opens
an MR — so it gets its own fresh checkout off `origin/main`, per the convention in
`.claude/skills/entrypoint/SKILL.md` §4.2. Without that, a daily timer would eventually
commit findings work on top of somebody's half-finished feature branch.

    python3 scripts/findings_sweep_run.py             # what the timer runs
    python3 scripts/findings_sweep_run.py --dry-run   # decide and report, launch nothing
    python3 scripts/findings_sweep_run.py --force     # ignore the budget (manual runs)

Exit codes: 0 = ran or stood down cleanly, 1 = the run failed.

Stdlib only, no app imports: this runs on a timer, before and independently of the app.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
INDEX_SCRIPT = REPO_ROOT / "scripts" / "findings_index.py"
WORKTREES_DIR = REPO_ROOT / ".claude" / "worktrees"
LOG_PATH = REPO_ROOT / ".agents" / "reports" / "findings-sweep" / "run-log.jsonl"

# Long, because a real run fixes code, runs pytest, and opens an MR. The systemd unit's
# TimeoutStartSec must stay comfortably above this or systemd will kill a healthy run.
AGENT_TIMEOUT_SEC = 5400

PROMPT = """/findings-sweep

Run the daily findings sweep, autonomously, per .claude/skills/findings-sweep/SKILL.md.

You are in a fresh worktree cut off origin/main; branch: {branch}
Budget for this run: {items} item(s) — {why}

Work to a finished, pushed MR. Do not stop to ask for permission: .agents/autonomy.md
authorises everything up to (and never including) the merge. If you cannot honestly fix
an item, record it open with a reason and say so in the run report rather than weakening
a test or a scanner rule to close it.
"""


def log(msg: str) -> None:
    print(f"[{datetime.now(UTC):%Y-%m-%d %H:%M:%S}Z] {msg}", flush=True)


def record(event: dict) -> None:
    """Append one line of run history. Best-effort: a logging failure must never be the
    reason a sweep fails, so every error here is swallowed deliberately."""
    try:
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        event["at"] = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        with LOG_PATH.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(event) + "\n")
    except OSError:
        pass


def run(argv: list[str], timeout: int = 120, cwd: Path | None = None) -> tuple[int, str, str]:
    try:
        proc = subprocess.run(
            argv, capture_output=True, text=True, timeout=timeout, cwd=str(cwd or REPO_ROOT), check=False
        )
        return proc.returncode, proc.stdout.strip(), proc.stderr.strip()
    except subprocess.TimeoutExpired:
        return 124, "", f"timed out after {timeout}s"
    except (OSError, FileNotFoundError) as exc:
        return 1, "", str(exc)


def index_json(args: list[str]) -> dict | None:
    code, out, err = run([sys.executable, str(INDEX_SCRIPT), *args])
    if code != 0 or not out:
        log(f"findings_index.py {' '.join(args)} failed: {err or out}")
        return None
    try:
        return json.loads(out)
    except json.JSONDecodeError:
        log(f"findings_index.py {' '.join(args)} returned non-JSON")
        return None


def cut_worktree(slug: str) -> tuple[Path, str] | None:
    """Fresh checkout off origin/main, per entrypoint's §4.2 convention.

    `git fetch` first: branching off a stale local `main` is how an autonomous run ends up
    re-fixing something that merged days ago and then producing a conflicted MR.
    """
    branch = f"chore/{slug}"
    path = WORKTREES_DIR / slug

    if path.exists():
        log(f"worktree {path} already exists — a previous run may still be in flight; standing down")
        return None

    code, _, err = run(["git", "fetch", "origin", "main"], timeout=180)
    if code != 0:
        log(f"git fetch failed: {err}")
        return None

    WORKTREES_DIR.mkdir(parents=True, exist_ok=True)
    code, _, err = run(["git", "worktree", "add", str(path), "-b", branch, "origin/main"], timeout=180)
    if code != 0:
        log(f"git worktree add failed: {err}")
        return None
    return path, branch


def worktree_is_untouched(path: Path, branch: str) -> bool:
    """True when the run left nothing behind: no commits past origin/main, no dirty files.

    Used to decide whether to clean up. Anything the run *did* produce is kept for a human
    to look at -- deleting an agent's only output because it failed to open an MR would
    destroy the evidence needed to understand why.
    """
    code, out, _ = run(["git", "status", "--porcelain"], cwd=path)
    if code != 0 or out.strip():
        return False
    code, out, _ = run(["git", "rev-list", "--count", f"origin/main..{branch}"], cwd=path)
    return code == 0 and out.strip() == "0"


def cleanup(path: Path, branch: str) -> None:
    if not worktree_is_untouched(path, branch):
        log(f"worktree kept for inspection: {path} ({branch})")
        return
    run(["git", "worktree", "remove", "--force", str(path)], timeout=120)
    run(["git", "branch", "-D", branch], timeout=60)
    log(f"worktree {path} was untouched; removed")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true", help="decide and report, launch nothing")
    parser.add_argument("--force", action="store_true", help="ignore the budget (manual runs)")
    parser.add_argument("--limit", type=int, default=None, help="override the item count")
    args = parser.parse_args(argv)

    # 1. Refresh the index. Free, and it self-heals: closes merged items, reopens
    #    regressions, drops human-suppressed findings.
    swept = index_json(["sweep", "--json"])
    if swept is None:
        record({"event": "sweep-failed"})
        return 1
    stats = swept.get("stats", {})
    log(
        f"swept: {swept.get('total')} tracked, {swept.get('open')} open "
        f"(new {stats.get('new')}, merged-closed {stats.get('closed_by_merge')}, "
        f"gone {stats.get('gone')}, reopened {stats.get('reopened')})"
    )

    # 2. Decide. Both gates are cheap and both must pass before anything is spent.
    budget = swept.get("budget") or {}
    items = args.limit if args.limit is not None else int(budget.get("items", 0))
    why = budget.get("why", "")
    if args.force and items < 1:
        items, why = 1, "forced by --force"

    if items < 1:
        log(f"standing down: {why}")
        record({"event": "stood-down", "why": why, "open": swept.get("open")})
        return 0

    picks = index_json(["next", "--limit", str(items), "--json"]) or {}
    chosen = picks.get("items", [])
    if not chosen:
        log("nothing outstanding — index is clear")
        record({"event": "nothing-to-do", "open": swept.get("open")})
        return 0

    log(f"budget {items} ({why}); picked: " + ", ".join(f"{c['id']}[{c.get('priority')}]" for c in chosen))

    if args.dry_run:
        log("dry run — not launching")
        return 0

    if not shutil.which("claude"):
        log("claude CLI not on PATH; cannot launch")
        record({"event": "launch-failed", "why": "claude not on PATH"})
        return 1

    # 3. Isolate, then spend.
    slug = f"findings-sweep-{datetime.now(UTC):%Y%m%d}"
    cut = cut_worktree(slug)
    if cut is None:
        record({"event": "worktree-failed", "slug": slug})
        return 1
    path, branch = cut

    prompt = PROMPT.format(branch=branch, items=items, why=why)
    log(f"launching findings-sweep in {path} on {branch}")
    record({"event": "launched", "branch": branch, "items": items, "ids": [c["id"] for c in chosen]})

    code, out, err = run(
        [
            "claude",
            "-p",
            prompt,
            "--model",
            "sonnet",
            "--effort",
            "xhigh",
            # The brief comes from this repo's own committed reports, not from untrusted
            # chat input, and the skill needs git/pytest/glab to reach an MR at all.
            "--permission-mode",
            "acceptEdits",
        ],
        timeout=AGENT_TIMEOUT_SEC,
        cwd=path,
    )
    if out:
        log(out[-4000:])
    if code != 0:
        log(f"agent exited {code}: {err[-2000:]}")
        record({"event": "agent-failed", "code": code, "branch": branch})
        cleanup(path, branch)
        return 1

    record({"event": "completed", "branch": branch, "ids": [c["id"] for c in chosen]})
    cleanup(path, branch)
    return 0


if __name__ == "__main__":
    sys.exit(main())
