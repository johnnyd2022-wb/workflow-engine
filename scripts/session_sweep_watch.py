#!/usr/bin/env python3
"""Weekly driver for the session-sweep skill: digest first, model only if warranted.

The shape, and the reason for it:

    systemd timer (daily)
      └─ scripts/session_sweep_watch.py        ← builds the digest. Zero tokens.
           ├─ already swept this ISO week?  exit 0                ← the common case
           ├─ digest has < min_signals actionable rows?
           │     └─ record `no-findings` for the week, spawn nothing, exit 0
           └─ otherwise:
                ├─ PHASE author  → codex gpt-5.6-sol, high effort, approvals never
                │    ├─ own worktree off origin/main (created HERE, passed as --cd)
                │    ├─ edits skills, writes findings-index.json, opens the MR
                │    └─ session_sweep_watch.py record --lease-id … --status authored
                └─ PHASE review  → claude opus, reads ONLY the findings index
                     └─ record --lease-id … --status reviewed

The timer is DAILY but the state is keyed on ISO week, so a week that was quota-held or
crashed retries tomorrow instead of waiting seven days for its next chance. A week that
succeeded is inert until the calendar rolls.

**The script decides; the skill writes — through one deterministic CLI.** The skill's only
way to record an outcome is `record --lease-id <id> --status …`. `--lease-id`, not the
week or the status, is the authority: a stale run's late write must never overwrite a
newer reservation. Same reasoning, same shape, as scripts/mr_conflict_watch.py.

Stdlib only, no app imports.

Usage:
    python3 scripts/session_sweep_watch.py                 # one tick
    python3 scripts/session_sweep_watch.py --dry-run       # decide + digest, spawn nothing
    python3 scripts/session_sweep_watch.py record --lease-id L --status authored --mr '!123'
"""

from __future__ import annotations

import argparse
import contextlib
import fcntl
import json
import shlex
import subprocess
import sys
import time
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

CONFIG_PATH = REPO / ".agents" / "session-sweep.json"
STATE_PATH = REPO / ".agents" / "session-sweep-state.json"
LOCK_PATH = REPO / ".agents" / "session-sweep-state.lock"
LOG_DIR = REPO / ".agents" / "reports" / "session-sweep"
SKILL_PATH = ".claude/skills/session-sweep/SKILL.md"

PHASE_AUTHOR = "author"
PHASE_REVIEW = "review"
TERMINAL = {"reviewed", "no-findings", "stalled"}

# Transient units get a fresh environment; ~/.local/bin (claude, python3) and /snap/bin
# (glab) are not on systemd's default user PATH. Verified for slack-watch.service and
# mr-conflict-watch.service; the same gap applies to anything spawned here. `codex` lives
# under nvm, so its directory is resolved at spawn time rather than hardcoded.
BASE_PATH = "/home/johnny/.local/bin:/usr/local/bin:/usr/bin:/bin:/snap/bin"


def log(msg: str) -> None:
    print(f"[session-sweep-watch] {msg}", flush=True)


def die(msg: str) -> None:
    log(f"FATAL: {msg}")
    raise SystemExit(1)


# ---------------------------------------------------------------------------
# Config and lease-fenced state
# ---------------------------------------------------------------------------


def load_config() -> dict[str, Any]:
    try:
        return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except FileNotFoundError:
        die(f"missing config: {CONFIG_PATH}")
    except ValueError as exc:
        die(f"malformed config {CONFIG_PATH}: {exc}")
    return {}


def load_state() -> dict[str, Any]:
    try:
        state = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return {"weeks": {}}
    if not isinstance(state, dict) or not isinstance(state.get("weeks"), dict):
        return {"weeks": {}}
    return state


@contextlib.contextmanager
def _state_lock():
    LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LOCK_PATH.open("a+") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def update_week(week: str, mutator: Callable[[dict[str, Any]], None]) -> dict[str, Any]:
    """Flock-guarded read-modify-write of exactly one week's entry.

    Every writer — the tick, the watchdog, the `record` CLI — goes through this. A bare
    load/mutate/save would let two writers tear the file; the lock stops that. It does
    NOT stop a *stale* writer clobbering a newer reservation, which is what `lease_id`
    (checked by the callers below) is for. Both are needed; neither substitutes.
    """
    with _state_lock():
        state = load_state()
        entry = state["weeks"].setdefault(week, {})
        mutator(entry)
        entry["updated"] = datetime.now(UTC).isoformat()
        STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = STATE_PATH.with_suffix(".tmp")
        tmp.write_text(json.dumps(state, indent=2), encoding="utf-8")
        tmp.replace(STATE_PATH)
        return dict(entry)


def iso_week(now: datetime | None = None) -> str:
    now = now or datetime.now(UTC)
    year, week, _ = now.isocalendar()
    return f"{year}-W{week:02d}"


# ---------------------------------------------------------------------------
# Digest
# ---------------------------------------------------------------------------

# Which digest signals count as "worth spending a model run on". Deliberately excludes
# `skill_usage` and the session table: those are always populated (every week has a
# heaviest session, every week has unused skills) and would make min_signals_to_launch
# unreachable, which would silently turn the free-quiet-week saving off.
ACTIONABLE_SIGNALS = (
    "house_rule_violations",
    "error_clusters",
    "repeated_commands",
    "oversized_results",
)


def count_signals(digest: dict[str, Any]) -> int:
    signals = digest.get("signals") or {}
    total = sum(len(signals.get(name) or []) for name in ACTIONABLE_SIGNALS)
    interventions = signals.get("interventions") or {}
    total += int(interventions.get("correction_count") or 0)
    total += int(interventions.get("interruptions") or 0)
    return total


def build_digest(cfg: dict[str, Any], week: str) -> tuple[Path, dict[str, Any]]:
    """Run scripts/session_sweep.py for this week's window. Deterministic and free."""
    out_dir = LOG_DIR / week
    argv = [
        sys.executable,
        str(REPO / "scripts" / "session_sweep.py"),
        "digest",
        "--days",
        str(cfg.get("window_days", 7)),
        "--out",
        str(out_dir),
    ]
    proc = subprocess.run(argv, capture_output=True, text=True, timeout=600, check=False)
    if proc.returncode != 0:
        die(f"digest failed: {proc.stderr.strip() or proc.stdout.strip()}")
    digest = json.loads((out_dir / "digest.json").read_text(encoding="utf-8"))
    return out_dir, digest


# ---------------------------------------------------------------------------
# Worktree
# ---------------------------------------------------------------------------


def ensure_worktree(cfg: dict[str, Any], slug: str) -> Path:
    """Create an isolated worktree off origin/main for this run.

    Created HERE, by the script, rather than by the agent — two reasons, and the second
    is the important one. First, it is deterministic setup with no judgment in it. Second,
    the path becomes codex's `--cd`, and `--sandbox workspace-write` makes the cwd the
    writable root: the author run is then *structurally* unable to write into main or into
    another skill's checkout, instead of merely being told not to.
    """
    worktrees = REPO / cfg.get("worktrees_dir", ".claude/worktrees")
    path = worktrees / slug
    if path.exists():
        return path
    subprocess.run(["git", "fetch", "origin", "main"], cwd=REPO, check=True, capture_output=True, timeout=120)
    worktrees.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["git", "worktree", "add", "-b", f"sweep/{slug}", str(path), "origin/main"],
        cwd=REPO,
        check=True,
        capture_output=True,
        text=True,
        timeout=120,
    )
    return path


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------


def build_prompt(
    phase: str, *, week: str, lease_id: str, digest_dir: Path, worktree: Path, entry: dict[str, Any]
) -> str:
    """The whole instruction is a pointer to the skill plus this run's parameters.

    Deliberately short. The skill file is the instructions; restating them here would
    create a second copy to drift out of sync, and would spend tokens re-sending prose
    that is already on disk in the worktree the agent is about to open.
    """
    common = (
        f"Read and follow the skill at: {SKILL_PATH}\n"
        f"Run parameters (use verbatim, do not invent your own):\n"
        f"  phase: {phase}\n"
        f"  week: {week}\n"
        f"  lease_id: {lease_id}\n"
        f"  worktree: {worktree}\n"
        f"  digest_dir: {digest_dir}\n"
    )
    if phase == PHASE_AUTHOR:
        return common + (
            f"  digest: {digest_dir}/digest.json\n"
            "You are the AUTHOR. Work only inside the worktree above. Read the digest, not\n"
            "the raw transcripts. Record your outcome with:\n"
            f"  python3 scripts/session_sweep_watch.py record --lease-id {lease_id} "
            "--status authored|no-findings|stalled --mr '<!iid>' --findings <n>\n"
        )
    return common + (
        f"  findings_index: {worktree}/.agents/reports/session-sweep/{week}/findings-index.json\n"
        f"  mr: {entry.get('mr_ref', '')}\n"
        "You are the REVIEWER. Review via the findings index only — do not re-derive the\n"
        "digest and do not read raw transcripts. Record your outcome with:\n"
        f"  python3 scripts/session_sweep_watch.py record --lease-id {lease_id} "
        "--status reviewed|stalled\n"
    )


# ---------------------------------------------------------------------------
# Spawning
# ---------------------------------------------------------------------------


def _agent_command(cfg: dict[str, Any], phase: str, worktree: Path) -> str:
    """The shell command the transient unit runs.

    Leading `exec` so the unit tracks the agent process itself rather than a bash wrapper
    around it — belt-and-braces alongside KillMode=control-group, which already kills the
    whole cgroup.
    """
    if phase == PHASE_AUTHOR:
        # --sandbox workspace-write + approval_policy=never is the "runs with nobody
        # around" combination, verified live: codex reports `approval: never` and
        # `sandbox: workspace-write (network access enabled)`. Network access is required
        # and not optional — the author phase pushes a branch and opens an MR through glab.
        parts = [
            "codex",
            "--strict-config",
            "-c",
            f'model_reasoning_effort="{cfg.get("author_effort", "high")}"',
            "-c",
            'approval_policy="never"',
            "-c",
            "sandbox_workspace_write.network_access=true",
            "exec",
            "--sandbox",
            "workspace-write",
            "-m",
            cfg.get("author_model", "gpt-5.6-sol"),
            "--cd",
            str(worktree),
        ]
        return "exec " + " ".join(shlex.quote(p) for p in parts) + ' "$SWEEP_PROMPT"'

    parts = [
        "claude",
        "-p",
        "--model",
        cfg.get("reviewer_model", "opus"),
        "--effort",
        cfg.get("reviewer_effort", "high"),
        # The reviewer comments on an MR and records a verdict; it does not rewrite the
        # author's diff. `auto` (classifier-gated), never `acceptEdits`.
        "--permission-mode",
        "auto",
    ]
    return f"cd {shlex.quote(str(worktree))} && exec " + " ".join(shlex.quote(p) for p in parts) + ' "$SWEEP_PROMPT"'


def spawn(cfg: dict[str, Any], phase: str, week: str, lease_id: str, worktree: Path, prompt: str) -> Path:
    """Launch the agent in a detached, time-bounded transient systemd unit."""
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    logfile = LOG_DIR / f"{stamp}-{week}-{phase}.log"
    unit = f"session-sweep-{week.lower()}-{phase}-{lease_id[:8]}"

    crash_grace = int(cfg.get("crash_grace_sec", 120))
    if crash_grace < 2:
        # Too small to fit a positive stop timeout strictly inside it. The whole "dead
        # before the watcher retries" invariant depends on that fitting, so this is a
        # config error to raise loudly rather than round up and hope.
        raise ValueError(f"crash_grace_sec={crash_grace} must be >= 2 (see .agents/session-sweep.json)")
    # RuntimeMaxSec only *starts* the stop (SIGTERM); systemd then waits up to
    # TimeoutStopSec for the final SIGKILL, and that default (DefaultTimeoutStopSec, ~90s,
    # manager-configurable) is not guaranteed to fit inside crash_grace_sec on every box.
    # Setting it explicitly makes the guarantee a property of this unit's own definition.
    stop_timeout = max(1, min(30, crash_grace - 1))

    watchdog = [
        sys.executable,
        str(REPO / "scripts" / "session_sweep_watchdog.py"),
        "--week",
        week,
        "--phase",
        phase,
        "--lease-id",
        lease_id,
        "--log",
        str(logfile),
    ]

    # `codex` lives under nvm, whose path is version-specific — resolve it now rather than
    # hardcoding a node version that a future `nvm install` will invalidate silently.
    path_env = BASE_PATH
    codex_bin = _which("codex")
    if codex_bin:
        path_env = f"{codex_bin.parent}:{path_env}"

    systemd_cmd = [
        "systemd-run",
        "--user",
        "--collect",
        f"--unit={unit}",
        # control-group, not process: the agent shells out constantly (git, pytest, glab),
        # and a process-mode kill signals only the one tracked PID, leaving those alive.
        "--property=KillMode=control-group",
        # Strictly below the tick's own staleness threshold (agent_timeout + crash_grace),
        # so the cgroup is provably dead before a replacement lease could be minted.
        f"--property=RuntimeMaxSec={int(cfg.get('agent_timeout_sec', 3600))}",
        f"--property=TimeoutStopSec={stop_timeout}",
        f"--working-directory={REPO}",
        f"--setenv=PATH={path_env}",
        f"--setenv=SWEEP_PROMPT={prompt}",
        f"--property=StandardOutput=append:{logfile}",
        f"--property=StandardError=append:{logfile}",
        f"--property=ExecStopPost={shlex.join(watchdog)}",
        "--",
        "bash",
        "-c",
        _agent_command(cfg, phase, worktree),
    ]
    subprocess.run(systemd_cmd, cwd=str(REPO), check=True, capture_output=True, text=True, timeout=30)
    return logfile


def _which(name: str) -> Path | None:
    from shutil import which

    found = which(name)
    return Path(found) if found else None


# ---------------------------------------------------------------------------
# Launch
# ---------------------------------------------------------------------------


def launch(cfg: dict[str, Any], phase: str, week: str, digest_dir: Path, dry_run: bool = False) -> None:
    """Reserve on disk, THEN spawn — never the other way round.

    A reservation written after the spawn is a race: a fast run's `record` call can land
    before the reservation exists, and its outcome is then checked against a lease that
    was not yet on disk. Persisting first makes every later write verifiable against a
    real, already-durable lease regardless of how fast the run finishes.
    """
    lease_id = uuid.uuid4().hex
    slug = f"sweep-{week.lower()}-{lease_id[:8]}"

    if phase == PHASE_REVIEW:
        ok, why = _quota_ok(cfg)
        if not ok:
            log(f"{week}: holding review phase — {why}")
            update_week(week, lambda e: e.update({"status": "held_for_capacity", "held_reason": why}))
            return

    state = load_state()
    entry = state["weeks"].get(week, {})
    # The attempt counter is PER PHASE, not per week. Carrying the author phase's count
    # into the review phase means an author that needed two attempts leaves the reviewer
    # starting at three — instantly over the cap, so the review silently never runs and
    # the week stalls with an unreviewed MR already open.
    attempt = (int(entry.get("attempt", 0)) if entry.get("phase") == phase else 0) + 1
    if attempt > int(cfg.get("max_attempts", 2)):
        log(f"{week}: {phase} exhausted {attempt - 1} attempts — marking stalled")
        update_week(week, lambda e: e.update({"status": "stalled", "blocker": f"{phase} exhausted attempts"}))
        return

    if dry_run:
        log(f"{week}: DRY RUN would launch phase={phase} attempt={attempt} slug={slug}")
        return

    # For the review phase the author's worktree already exists and holds the findings
    # index and the branch the MR was opened from — reuse it rather than cutting a second.
    if phase == PHASE_REVIEW and entry.get("worktree_slug"):
        slug = entry["worktree_slug"]
    worktree = ensure_worktree(cfg, slug)

    def reserve(e: dict[str, Any]) -> None:
        e.update(
            {
                "phase": phase,
                "status": "handed_off",
                "lease_id": lease_id,
                "worktree_slug": slug,
                "attempt": attempt,
                "digest_dir": str(digest_dir),
            }
        )
        e.pop("held_reason", None)

    reserved = update_week(week, reserve)
    prompt = build_prompt(phase, week=week, lease_id=lease_id, digest_dir=digest_dir, worktree=worktree, entry=reserved)

    try:
        logfile = spawn(cfg, phase, week, lease_id, worktree, prompt)
    except (subprocess.CalledProcessError, OSError, ValueError) as exc:
        detail = getattr(exc, "stderr", "") or str(exc)
        log(f"{week}: spawn failed — {detail}")
        # Settle the lease we just reserved. Leaving it `handed_off` would strand the week
        # until the staleness timeout, for a run that never started.
        finalize(week, lease_id, "stalled", blocker=f"spawn failed: {detail}"[:300])
        return
    log(f"{week}: launched {phase} (attempt {attempt}, lease {lease_id[:8]}) -> {logfile}")


def _quota_ok(cfg: dict[str, Any]) -> tuple[bool, str]:
    """Reuse slack_watch's quota gate rather than reinventing it.

    Gates the reviewer only: it spends the same Claude subscription every interactive
    session does. The author phase runs on Codex's separate pool, about which this cached
    reading says nothing — gating it here would hold a run for a constraint it isn't under.
    """
    try:
        import slack_watch  # noqa: PLC0415 — optional dependency of this gate only
    except ImportError:
        return True, "quota gate unavailable (slack_watch not importable)"
    try:
        return slack_watch.quota_ok_to_launch(cfg)
    except Exception as exc:  # noqa: BLE001 — a broken gate must not block the sweep
        return True, f"quota gate errored ({exc}); proceeding"


# ---------------------------------------------------------------------------
# Outcome recording
# ---------------------------------------------------------------------------


def finalize(
    week: str,
    lease_id: str,
    status: str,
    *,
    mr_ref: str | None = None,
    findings: int | None = None,
    blocker: str | None = None,
) -> bool:
    """Write a terminal outcome, but only if `lease_id` still owns this week.

    A mismatch is logged and ignored, never applied. The case this closes: a previous
    run's watchdog finishing late, after a newer reservation has already replaced it. It
    can validly take the lock and would otherwise overwrite a newer outcome with an older
    one — the lock proves nobody is mid-write, not that the writer is still current.
    """
    applied = False

    def mutate(entry: dict[str, Any]) -> None:
        nonlocal applied
        if entry.get("lease_id") != lease_id:
            return
        entry["status"] = status
        entry.pop("lease_id", None)
        if mr_ref:
            entry["mr_ref"] = mr_ref
        if findings is not None:
            entry["findings"] = findings
        if blocker:
            entry["blocker"] = blocker[:500]
        applied = True

    update_week(week, mutate)
    if not applied:
        log(f"{week}: ignoring stale write (lease {lease_id[:8]} no longer owns this week)")
    return applied


def _week_for_lease(lease_id: str) -> str | None:
    for week, entry in load_state()["weeks"].items():
        if entry.get("lease_id") == lease_id:
            return week
    return None


# ---------------------------------------------------------------------------
# Tick
# ---------------------------------------------------------------------------


def tick(cfg: dict[str, Any], dry_run: bool = False) -> int:
    week = iso_week()
    state = load_state()
    entry = state["weeks"].get(week)

    if entry and entry.get("status") in TERMINAL:
        log(f"{week}: already {entry['status']} — nothing to do")
        return 0

    if entry and entry.get("status") == "handed_off":
        stale_after = int(cfg.get("agent_timeout_sec", 3600)) + int(cfg.get("crash_grace_sec", 120))
        updated = entry.get("updated", "")
        age = _age_seconds(updated)
        if age is not None and age < stale_after:
            log(f"{week}: {entry.get('phase')} in flight ({int(age)}s old) — leaving alone")
            return 0
        log(f"{week}: {entry.get('phase')} looks stale ({age}s) — retrying")
        digest_dir = Path(entry.get("digest_dir") or (LOG_DIR / week))
        launch(cfg, entry.get("phase", PHASE_AUTHOR), week, digest_dir, dry_run)
        return 0

    if entry and entry.get("status") == "authored":
        log(f"{week}: author phase done ({entry.get('findings', '?')} findings) — launching review")
        launch(cfg, PHASE_REVIEW, week, Path(entry.get("digest_dir") or (LOG_DIR / week)), dry_run)
        return 0

    if entry and entry.get("status") == "held_for_capacity":
        # Resume the phase that was actually held, not an assumed one. The watchdog puts a
        # week here on a mid-run quota wall, which can happen during EITHER phase —
        # hardcoding review would silently skip a held author phase and try to review an
        # MR that was never opened.
        held_phase = entry.get("phase", PHASE_AUTHOR)
        log(f"{week}: resuming held {held_phase} phase")
        launch(cfg, held_phase, week, Path(entry.get("digest_dir") or (LOG_DIR / week)), dry_run)
        return 0

    # No entry yet: this week has not been swept. Build the digest first — it is free, and
    # it is what decides whether a model run is warranted at all.
    digest_dir, digest = build_digest(cfg, week)
    signals = count_signals(digest)
    minimum = int(cfg.get("min_signals_to_launch", 1))
    log(
        f"{week}: digest built — {digest['scanned']['sessions']} sessions, "
        f"{digest['scanned']['tool_calls']} tool calls, {signals} actionable signals"
    )
    if signals < minimum:
        log(f"{week}: {signals} < {minimum} actionable signals — recording no-findings, spawning nothing")
        if not dry_run:
            update_week(
                week,
                lambda e: e.update(
                    {"status": "no-findings", "phase": PHASE_AUTHOR, "findings": 0, "digest_dir": str(digest_dir)}
                ),
            )
        return 0
    launch(cfg, PHASE_AUTHOR, week, digest_dir, dry_run)
    return 0


def _age_seconds(iso: str) -> float | None:
    if not iso:
        return None
    try:
        parsed = datetime.fromisoformat(iso)
    except ValueError:
        return None
    if not parsed.tzinfo:
        parsed = parsed.replace(tzinfo=UTC)
    return time.time() - parsed.timestamp()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true", help="build the digest and decide, but spawn nothing")
    sub = parser.add_subparsers(dest="command")

    rec = sub.add_parser("record", help="record a run outcome (lease-fenced)")
    rec.add_argument("--lease-id", required=True)
    rec.add_argument("--status", required=True, choices=["authored", "reviewed", "no-findings", "stalled"])
    rec.add_argument("--week", default=None, help="defaults to the week this lease owns")
    rec.add_argument("--mr", default=None, dest="mr_ref")
    rec.add_argument("--findings", type=int, default=None)
    rec.add_argument("--blocker", default=None)

    args = parser.parse_args(argv)
    cfg = load_config()

    if args.command == "record":
        week = args.week or _week_for_lease(args.lease_id)
        if week is None:
            log(f"no week owns lease {args.lease_id[:8]} — ignoring")
            return 0
        applied = finalize(
            week, args.lease_id, args.status, mr_ref=args.mr_ref, findings=args.findings, blocker=args.blocker
        )
        log(f"{week}: recorded {args.status}" if applied else f"{week}: write ignored (stale lease)")
        return 0

    return tick(cfg, dry_run=args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
