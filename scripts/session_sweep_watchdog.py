#!/usr/bin/env python3
"""Reacts to a session-sweep phase stopping. Invoked as ExecStopPost on the transient
systemd unit scripts/session_sweep_watch.py launches — same contract as
scripts/chain_watchdog.py and scripts/mr_conflict_watchdog.py, which this mirrors:
systemd guarantees it fires exactly once whatever the outcome, and hands it
$EXIT_STATUS / $SERVICE_RESULT.

On success: the skill's own last step already called `session_sweep_watch.py record
--lease-id <id>` to leave `authored`/`reviewed` on disk. Nothing to announce — this
script only checks that the run actually left an outcome behind *under its own lease*,
because a clean exit code proves the process didn't crash, not that it did its job. A
run that exits 0 having recorded nothing is a run that silently did nothing, which is
exactly the failure a weekly unattended loop would otherwise never notice.

On failure: a recognised quota signature in the log leaves the week held so the next
daily tick retries it; anything else is recorded `stalled` for a human. Deliberately no
Slack post either way — `.agents/notifications.json`'s `#code-changes` channel means "MR
open AND pipeline green", and a channel that also means "a sweep died" stops meaning
anything. A stalled week surfaces in the state file and in the next tick's log.

Every write is gated on `--lease-id` matching the week's currently active lease. This
script is one more concurrent writer alongside the tick and the skill's own `record`
call, and a late invocation from a superseded attempt must never overwrite a newer
reservation's outcome.

Usage (only ever invoked by systemd's ExecStopPost, or by hand to test):
    python3 scripts/session_sweep_watchdog.py --week 2026-W32 --phase author \\
        --lease-id <id> --log <path>
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

import session_sweep_watch as ssw  # noqa: E402

try:  # Same best-guess signature list the other watchdogs use.
    from chain_watchdog import QUOTA_SIGNATURES  # noqa: E402
except ImportError:  # pragma: no cover - chain_watchdog is expected to exist
    QUOTA_SIGNATURES = ("usage limit", "rate limit", "quota", "429")


def log(msg: str) -> None:
    print(f"[session_sweep_watchdog] {msg}", flush=True)


def looks_like_quota_failure(log_path: Path) -> bool:
    if not log_path.exists():
        return False
    try:
        text = log_path.read_text(errors="replace").lower()
    except OSError:
        return False
    return any(sig in text for sig in QUOTA_SIGNATURES)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--week", required=True)
    ap.add_argument("--phase", required=True, choices=[ssw.PHASE_AUTHOR, ssw.PHASE_REVIEW])
    ap.add_argument("--lease-id", required=True)
    ap.add_argument("--log", required=True, type=Path)
    args = ap.parse_args(argv)

    result = os.environ.get("SERVICE_RESULT", "unknown")
    exit_status = os.environ.get("EXIT_STATUS", "?")
    log(f"week={args.week} phase={args.phase} lease={args.lease_id[:8]} result={result} exit_status={exit_status}")

    entry = ssw.load_state()["weeks"].get(args.week, {})
    if entry.get("lease_id") != args.lease_id:
        # Either the run recorded its own outcome (which clears lease_id) or a newer
        # reservation has already replaced this one. Both mean this watchdog has nothing
        # left to own; writing anything now would be the stale overwrite lease fencing
        # exists to prevent.
        log("lease no longer active — outcome already settled or superseded; nothing to do")
        return 0

    if result == "success" and exit_status == "0":
        # Clean exit but the lease is still held: the agent finished without calling
        # `record`. Not a crash, but not a completed job either — say so honestly rather
        # than letting the week look done.
        ssw.finalize(
            args.week, args.lease_id, "stalled", blocker=f"{args.phase} exited cleanly without recording an outcome"
        )
        log("clean exit with no recorded outcome — marked stalled")
        return 0

    if looks_like_quota_failure(args.log):
        # Leave the week held rather than stalled: the next daily tick retries it, and a
        # quota wall is not a defect in the run.
        def hold(entry_: dict) -> None:
            if entry_.get("lease_id") != args.lease_id:
                return  # superseded between the check above and this locked write
            entry_["status"] = "held_for_capacity"
            entry_["held_reason"] = f"{args.phase} hit a quota wall"
            # The hold ends this lease's ownership: the next tick mints a fresh one.
            # Leaving the old lease_id behind would let this dead run's late writes still
            # look authoritative.
            entry_.pop("lease_id", None)

        ssw.update_week(args.week, hold)
        log("quota signature in log — week held for the next tick")
        return 0

    ssw.finalize(
        args.week, args.lease_id, "stalled", blocker=f"{args.phase} failed: result={result} exit_status={exit_status}"
    )
    log("marked stalled")
    return 0


if __name__ == "__main__":
    sys.exit(main())
