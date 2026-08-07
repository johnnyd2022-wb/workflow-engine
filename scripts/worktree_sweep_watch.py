#!/usr/bin/env python3
"""Daily systemd-timer wrapper around `worktree_sweep.py`: detect, don't act.

Reuses the `systemd-run` + headless `claude -p` pattern already established by
`slack_watch.py` and `session_sweep_watch.py` -- not invented fresh -- but this one is much
simpler than either: there's no model-authored diff to review, no lease-fenced multi-phase
state machine, because there's nothing here for a model to *build*. `worktree_sweep.py`'s
classification is fully deterministic; the only thing this wrapper adds on top is "tell a
human when there's something new to look at."

    systemd timer (daily)
      └─ worktree_sweep_watch.py
           ├─ worktree_sweep.gather() in-process -- zero tokens, always
           ├─ writes .agents/reports/worktree-sweep/latest.json
           ├─ new remove_candidates since last notify? no -> exit 0, spent nothing
           └─ yes -> systemd-run a minimal `claude -p` whose only job is to read that report
                and call PushNotification. It is never given a reason or a way to delete
                anything -- the prompt says so, and the script never passes `--apply`.

**The unattended path can only ever detect and notify, never remove.** That is the
substitute for "ask a human before deleting" in unattended mode
(`.agents/autonomy.md`): there is no MR-diff equivalent to review *after* a worktree is
gone, so the human turn has to happen *before* anything happens at all -- which is what the
`worktree-sweep` skill (interactive, confirm-then-apply) is for. This wrapper's notification
is the nudge to go run it; it is not, itself, permitted to act.

Usage:
    python3 scripts/worktree_sweep_watch.py             # real run: report, maybe notify
    python3 scripts/worktree_sweep_watch.py --dry-run   # compute + print, spawn nothing
"""

from __future__ import annotations

import argparse
import fcntl
import json
import subprocess
import sys
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

import worktree_sweep  # noqa: E402

STATE_PATH = REPO / ".agents" / "worktree-sweep-state.json"
LOCK_PATH = REPO / ".agents" / "worktree-sweep-state.lock"
REPORT_DIR = REPO / ".agents" / "reports" / "worktree-sweep"
REPORT_PATH = REPORT_DIR / "latest.json"

# systemd's user PATH excludes ~/.local/bin and /snap/bin, where `claude` lives -- the same
# gap already fixed for slack-watch.service and session-sweep.service.
BASE_PATH = "/home/johnny/.local/bin:/usr/local/bin:/usr/bin:/bin:/snap/bin"


@contextmanager
def _locked_state():
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LOCK_PATH.open("a+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            state: dict[str, Any] = json.loads(STATE_PATH.read_text()) if STATE_PATH.exists() else {}
            state.setdefault("notified_branches", [])
            yield state
            STATE_PATH.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n")
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def _prompt(new_candidates: list[dict[str, Any]]) -> str:
    lines = "\n".join(f"- {c['branch']} ({c['path']})" for c in new_candidates)
    report_rel = REPORT_PATH.relative_to(REPO)
    return (
        f"Read {report_rel} in the workflow-engine repo. Its remove_candidates list includes "
        f"these worktree(s), newly eligible since the last check:\n{lines}\n\n"
        "Call PushNotification summarizing them (branch names and count) and tell the user to "
        "run the worktree-sweep skill to review and act on them. Do not delete anything, do "
        "not run worktree_sweep.py with --apply, do not edit any files, do not run any other "
        "tool. That is the entire task."
    )


def spawn_notifier(prompt: str) -> None:
    unit = f"worktree-sweep-notify-{uuid.uuid4().hex[:8]}"
    cmd = [
        "systemd-run",
        "--user",
        "--collect",
        f"--unit={unit}",
        "--property=KillMode=control-group",
        "--property=RuntimeMaxSec=180",
        f"--working-directory={REPO}",
        f"--setenv=PATH={BASE_PATH}",
        "--",
        "claude",
        "-p",
        prompt,
        "--permission-mode",
        "auto",
    ]
    subprocess.run(cmd, cwd=str(REPO), check=True, capture_output=True, text=True, timeout=30)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true", help="compute and print, spawn nothing")
    args = ap.parse_args(argv)

    report = worktree_sweep.report_to_dict(worktree_sweep.gather(worktree_sweep.REPO_ROOT))
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, indent=2) + "\n")

    with _locked_state() as state:
        already_notified = set(state["notified_branches"])
        current_branches = {c["branch"] for c in report["remove_candidates"]}
        new = [c for c in report["remove_candidates"] if c["branch"] not in already_notified]

        if args.dry_run:
            print(f"worktree-sweep-watch: would notify about {len(new)} candidate(s):")
            for c in new:
                print(f"  {c['branch']} ({c['path']})")
            return 0

        # Only a real notification run advances the deduplication state. A dry-run that
        # consumed these branches would make the next timer tick silently suppress the
        # notification it was meant to preview.
        #
        # Forget anything no longer a candidate (removed, or since disqualified) so a
        # branch name that reappears later -- a fresh branch reusing an old name -- gets
        # renotified rather than staying permanently suppressed by a stale entry.
        state["notified_branches"] = sorted(current_branches)

        if not new:
            print("worktree-sweep-watch: nothing new to notify -- zero tokens spent")
            return 0

        spawn_notifier(_prompt(new))

    print(f"worktree-sweep-watch: notified about {len(new)} candidate(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
