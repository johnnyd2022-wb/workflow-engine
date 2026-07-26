#!/usr/bin/env python3
"""Reacts to a chain run stopping. Invoked as ExecStopPost on the transient
systemd unit that runs the chain -- systemd guarantees this fires exactly
once, whatever the outcome (success, failure, killed), and hands it
$EXIT_STATUS / $SERVICE_RESULT as environment variables. Verified live before
this was ever relied on (see docs/slack-watcher-setup.md).

This is the reactive half of quota handling. There is no live signal to watch
during an unattended run -- verified: `claude -p --output-format json` carries
no rate-limit field, only per-call token usage, and the interactive statusline
cache that DOES carry it only refreshes on an attended render, so nothing
updates it while a headless chain runs. The only signal that actually exists
is the chain stopping and this script finding out why, after the fact.

On success: nothing to do. The chain's own merge-request step already
announces a green MR in #code-changes; this script would just be noise.

On failure: read the log tail and look for a quota/rate-limit signature. This
pattern list is a best guess, not a verified one -- there has been no real
hard rate-limit stop observed in this repo's history to confirm the exact
wording against. Treat that as this script's known gap, not a hidden one:

  - Matched  -> treat as quota exhaustion. Schedule a resume (fast-path timer
    + persisted state for the durable poller fallback) and notify Slack.
  - Unmatched -> treat as a genuine, unexplained failure. Notify Slack that
    something needs a look, and do NOT auto-schedule a resume -- retrying a
    real bug under the "quota" label forever would look like progress while
    being none, which is worse than just surfacing it.

Usage (only ever invoked by systemd's ExecStopPost, or by hand to test):
    python3 scripts/chain_watchdog.py --thread-ts <ts> --channel <id> \\
        --kind bug|feature --chain-session-id <uuid> --log <path> --attempt <n>
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

import slack_watch as sw  # noqa: E402

# Best-effort signature list -- see module docstring. Deliberately short and
# conservative: a false negative (missed quota signal) just means the failure
# gets reported as "unclear" instead of auto-resumed, which is a safe failure
# mode. A false positive (real bug mistaken for quota) would silently retry
# broken work, which is not -- so this list stays narrow rather than greedy.
QUOTA_SIGNATURES = (
    "rate_limit_error",
    "usage limit",
    "usage_limit",
    "quota exceeded",
    "you've reached your",
    "5-hour limit",
    "5 hour limit",
)


def log(msg: str) -> None:
    print(f"[chain_watchdog] {msg}", flush=True)


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
    ap.add_argument("--thread-ts", required=True)
    ap.add_argument("--channel", required=True)
    ap.add_argument("--kind", required=True)
    ap.add_argument("--chain-session-id", required=True)
    ap.add_argument("--log", required=True, type=Path)
    ap.add_argument("--attempt", required=True, type=int)
    args = ap.parse_args()

    result = os.environ.get("SERVICE_RESULT", "unknown")
    exit_status = os.environ.get("EXIT_STATUS", "?")
    log(f"thread={args.thread_ts} attempt={args.attempt} result={result} exit_status={exit_status}")

    if result == "success":
        # The chain's own merge-request step handles announcing a green MR.
        log("clean exit -- nothing for the watchdog to do")
        return 0

    cfg = sw.load_config()
    state = sw.load_state()
    meta = state["threads"].setdefault(
        args.thread_ts,
        {"channel": args.channel, "kind": args.kind, "chain_session_id": args.chain_session_id},
    )
    meta["chain_session_id"] = args.chain_session_id
    meta["kind"] = args.kind

    if looks_like_quota_failure(args.log):
        when = sw.estimate_reset_at(cfg)
        mins = max(1, int((when - time.time()) / 60))
        log(f"looks quota-related; scheduling resume in ~{mins}m")
        meta["status"] = "held_for_capacity"
        meta["held_reason"] = f"chain stopped mid-run (result={result}, exit_status={exit_status})"
        meta["resume_attempts"] = args.attempt
        meta["scheduled_resume_at"] = when
        sw.schedule_resume_timer(args.thread_ts, when)
        sw.post_via_mcp(
            cfg,
            args.channel,
            args.thread_ts,
            f"Hit usage limits partway through this one. I'll pick it back up in about {mins} min, "
            "once the window resets — no need to do anything.",
        )
    else:
        log("failure does not match a known quota signature -- reporting as unclear, not auto-resuming")
        meta["status"] = "stalled"
        meta["last_error"] = f"chain stopped (result={result}, exit_status={exit_status}), reason unclear"
        sw.post_via_mcp(
            cfg,
            args.channel,
            args.thread_ts,
            "This one stopped partway through for a reason I can't identify as a usage-limit issue "
            f"(result={result}). Not auto-retrying — worth a look at `{args.log}`.",
        )

    sw.save_state(state)
    return 0


if __name__ == "__main__":
    sys.exit(main())
