#!/usr/bin/env python3
"""Reacts to a resolver run stopping. Invoked as ExecStopPost on the transient systemd
unit scripts/mr_conflict_watch.py launches — same contract as scripts/chain_watchdog.py,
which this deliberately mirrors: systemd guarantees this fires exactly once, whatever the
outcome, and hands it $EXIT_STATUS / $SERVICE_RESULT.

On success: the resolver skill's own last step already called `mr_conflict_watch.py
record --lease-id <id>` to leave `resolved`/`needs_human` on disk (and, if the MR turned
out mechanical, a fresh commit + a clean GitLab recheck). Nothing for this script to
announce; it only checks that the run actually left a recorded outcome behind under ITS
lease, since a clean exit code proves the process didn't crash, not that it did its job.

On failure: same two-way split as chain_watchdog — a recognized quota signature in the
log schedules a resume (the next 2-minute poll tick reconciles it; no separate fast-path
timer needed at this cadence), anything else is recorded `stalled` for a human to
re-drive by hand. Deliberately no Slack post either way: `.agents/notifications.json`'s
`#code-changes` channel is reserved for "MR open AND pipeline green", and posting a
mid-run failure there would break that discipline. A stalled/needs_human MR surfaces
through the MR itself (comment + label), through Mission Control's NEEDS YOU bucket if
reporting is enabled, and through `skill_metrics.py digest`, which `preflight` already
prints at the top of every code session.

Every write here is gated on `--lease-id` matching the currently active lease
(`mr_conflict_watch.finalize_if_owned` / the inline `_hold` check below) — this script is
itself one more concurrent writer alongside the poller, the skill's own `record` call,
and any other in-flight watchdog, and a late invocation from a superseded attempt must
never overwrite a newer reservation's outcome. See mr_conflict_watch.py's module
docstring for the lost-update and stale-write races this closes.

Usage (only ever invoked by systemd's ExecStopPost, or by hand to test):
    python3 scripts/mr_conflict_watchdog.py --mr-iid 143 --sha <sha> --lease-id <id> \\
        --log <path> --attempt 0
"""

from __future__ import annotations

import argparse
import os
import sys
import time
import uuid
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

import mr_conflict_watch as mcw  # noqa: E402
import slack_watch as sw  # noqa: E402 - quota-cache reasoning only, no Slack call is made
from chain_watchdog import QUOTA_SIGNATURES  # noqa: E402 - same best-guess signature list


def log(msg: str) -> None:
    print(f"[mr_conflict_watchdog] {msg}", flush=True)


def looks_like_quota_failure(log_path: Path) -> bool:
    if not log_path.exists():
        return False
    try:
        text = log_path.read_text(errors="replace").lower()
    except OSError:
        return False
    return any(sig in text for sig in QUOTA_SIGNATURES)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mr-iid", required=True, type=int)
    ap.add_argument("--sha", required=True, help="logging only -- lease_id is the actual authority")
    ap.add_argument("--lease-id", required=True)
    ap.add_argument("--log", required=True, type=Path)
    ap.add_argument("--attempt", required=True, type=int)
    args = ap.parse_args()

    result = os.environ.get("SERVICE_RESULT", "unknown")
    exit_status = os.environ.get("EXIT_STATUS", "?")
    log(
        f"mr=!{args.mr_iid} sha={args.sha[:8]} lease={args.lease_id[:8]} "
        f"attempt={args.attempt} result={result} exit_status={exit_status}"
    )

    key = str(args.mr_iid)

    if result == "success":
        # If the skill already called `record` under this exact lease, that write
        # already happened and finalize_if_owned's own lease check makes this a no-op
        # (logged as a stale/already-finalized lease, which is the correct, boring
        # outcome here). If it never recorded anything, this is what actually marks it
        # stalled -- and the SAME lease check protects this from firing after a newer
        # reservation has already replaced this one.
        applied = mcw.finalize_if_owned(
            args.mr_iid, args.lease_id, "stalled", "resolver exited 0 without recording an outcome"
        )
        if applied:
            log("clean exit but this lease never recorded an outcome -- marked stalled")
        else:
            log("clean exit, outcome already recorded (or this lease was superseded) -- nothing to do")
        return 0

    if looks_like_quota_failure(args.log):
        when = sw.estimate_reset_at(mcw.load_config())
        mins = max(1, int((when - time.time()) / 60))
        log(f"looks quota-related; next poll tick reconciles in ~{mins}m")

        captured: dict = {}

        def _hold(meta: dict, _state: dict) -> None:
            if meta.get("lease_id") != args.lease_id or meta.get("status") != "handed_off":
                log("stale lease -- not holding, a newer reservation or outcome already exists")
                return
            captured["run_id"] = meta.get("mission_run_id")
            meta.update(
                status="held_for_capacity",
                held_reason=f"resolver stopped mid-run (result={result}, exit_status={exit_status})",
                attempts=args.attempt + 1,
                scheduled_resume_at=when,
                # Fresh per hold, same reasoning as launch()'s quota-hold branch: a proxy
                # built from other fields can alias two different holds if they happen
                # to share status/sha/target_sha/scheduled_resume_at.
                hold_id=uuid.uuid4().hex,
            )
            # The lease is consumed either way -- a resume goes back through launch(),
            # which mints a fresh one. Leaving the old one around would let a second,
            # even-later straggler from this same attempt still pass the lease check.
            meta.pop("lease_id", None)
            # mission_run_id is cleared here too: the eventual resume mints its own fresh
            # one (see launch()'s reservation step), and leaving this one attached to an
            # entry that's about to be held would let it get silently overwritten instead
            # of settled -- see the _call_mission_finish call below for why it must
            # settle now, before that happens.
            meta.pop("mission_run_id", None)

        mcw.update_mr_state(key, _hold)
        if captured.get("run_id"):
            # A quota retry mints a brand-new lease AND run_id on its next launch (see
            # launch()'s reservation step) -- this run_id's story ends here, at "held for
            # capacity," or it would never get a `report finish` at all and Mission
            # Control would show it permanently `running` forever.
            mcw._call_mission_finish(
                captured["run_id"], args.mr_iid, "stalled", "held for capacity — quota exhausted mid-run"
            )
    else:
        log("failure does not match a known quota signature -- reporting as unclear, not auto-resuming")
        mcw.finalize_if_owned(
            args.mr_iid,
            args.lease_id,
            "stalled",
            f"resolver stopped (result={result}, exit_status={exit_status}), reason unclear",
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())
