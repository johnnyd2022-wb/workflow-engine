# Session sweep setup

Reduces a week of this system's own Claude Code sessions to a small digest, and — only if
that digest shows something worth acting on — hands it to the `session-sweep` skill:
Codex authors instruction fixes and an MR, Opus reviews them through a findings index.

## Why this exists

Every other skill in this repo improves the *application*. Nothing improves the *system
that improves the application*. The only honest record of how that system behaves — which
skills fire, which commands get retried three times, where a run burned a million tokens
re-reading one file, where the founder had to interrupt — is `~/.claude/projects/**/*.jsonl`,
and nobody reads it, because it is ~127MB of JSONL and reading it is exactly the kind of
waste it records.

## How it is put together

```
systemd timer (daily)
  └─ scripts/session_sweep_watch.py       ← builds the digest itself. Zero tokens.
       ├─ already swept this ISO week?  exit 0             ← the common case
       ├─ digest shows < min_signals actionable rows?
       │     └─ record `no-findings`, spawn nothing, exit 0 ← a quiet week costs nothing
       └─ otherwise, mint lease_id, create the worktree, reserve on disk BEFORE spawning:
            ├─ PHASE author → detached systemd-run unit
            │    └─ codex exec -m gpt-5.6-sol --sandbox workspace-write
            │         -c model_reasoning_effort=high -c approval_policy=never --cd <worktree>
            │         ├─ reads digest.json (never a transcript)
            │         ├─ resolves ≤3 evidence pointers per finding via `session_sweep.py show`
            │         ├─ edits the SKILL.md files whose instructions allowed the waste
            │         ├─ writes findings-index.json
            │         └─ /git-commit-chain → MR
            │              └─ session_sweep_watch.py record --lease-id … --status authored
            └─ PHASE review (next tick) → claude -p --model opus --effort high
                 ├─ reads ONLY findings-index.json + the cited diff hunks
                 └─ record --lease-id … --status reviewed
       └─ ExecStopPost=scripts/session_sweep_watchdog.py (same lease_id) on both phases
            ├─ clean exit, outcome recorded → nothing to do
            ├─ clean exit, lease still held → record `stalled` (the run didn't do its job)
            └─ non-zero → quota signature? hold for the next tick; else `stalled`
```

**The script decides; the skill writes — through one deterministic CLI.** The skill's only
way to record an outcome is `python3 scripts/session_sweep_watch.py record --lease-id <id>
--status authored|reviewed|no-findings|stalled`. `--lease-id`, not the week or the status,
is the authority.

## Design choices worth knowing

**The models never read a transcript.** `scripts/session_sweep.py` streams them and applies
a fixed detector suite; a real week reduced 127MB across 39 transcripts to a **42KB digest
in 0.3s**. Every signal is computed by tested code, not by a model's impression, which is
what makes a finding re-derivable and the reviewer's spot-check cheap.

**A quiet week costs zero tokens, and that is the largest saving in the pipeline.** The
digest is free; the model is not. `min_signals_to_launch` gates every model run behind
deterministic evidence that there is something to fix. `count_signals` deliberately
excludes `skill_usage` and the session table — those are populated every single week
(there is always a heaviest session, always an unused skill), so counting them would make
the threshold unreachable and silently disable the saving. There is a test for exactly
that.

**Two engines, two pools, two jobs.** The author phase is Codex `gpt-5.6-sol`, which draws
on a *separate quota pool* from the Claude subscription every interactive session spends —
so the expensive half of the sweep costs nothing the founder was going to use. The effort
is set explicitly to `high` because **`gpt-5.6-sol` defaults to `low`**, and an unset
effort ships a shallow review that still looks like a review (`.agents/autonomy.md`, Token
discipline). Verified live: codex reports `approval: never`, `sandbox: workspace-write
(network access enabled)`, `reasoning effort: high`.

**The findings index is what makes the weekly Opus review affordable.** Without it, review
means re-reading the digest and re-deriving the author's reasoning — paying Opus rates for
a second opinion nobody asked for. Each finding carries its claim, its evidence pointers,
the exact `file` + `lines` it changed, and a `review_hint`: *the single check that would
falsify it*. Opus reads one hunk and answers one question per finding. The index is
committed (unlike the digest), so next week's sweep inherits this week's reasoning instead
of rediscovering it.

**The worktree is created by the script, not the agent — and that is a security property.**
`ensure_worktree()` cuts it off a fresh `origin/main` and passes it as codex's `--cd`.
Under `--sandbox workspace-write` the cwd *is* the writable root, so an author run is
structurally unable to write into `main` or another skill's checkout. That is a syscall
sandbox, not an instruction the model is asked to follow.

**The timer is daily; the state is weekly.** A week that was quota-held or crashed retries
tomorrow rather than waiting seven days for its next chance. A week that succeeded is inert
until the calendar rolls.

**Only the reviewer is quota-gated.** `quota_ok_to_launch` (imported from
`scripts/slack_watch.py`, reused rather than reinvented) reads a cache of the *Claude* 5h
window. Gating the Codex author phase on it would hold a run for a constraint it is not
under.

**Every state write is locked AND lease-fenced.** `update_week()` does a flock-guarded
read-modify-write; the poller, the detached watchdog, and the `record` CLI all go through
it. Locking alone stops two writers tearing the file, but not a *stale* one — an old run's
watchdog finishing late, after a newer reservation replaced it, can validly re-acquire the
lock and overwrite a newer outcome with an older one. `lease_id` closes that: every
reservation mints a fresh one, and the reservation is persisted **before** the agent is
spawned, so a fast run's `record` call is always checked against a lease already on disk.

**Redaction is best-effort, so the raw digest stays out of git.** `redact()` runs on every
string entering the digest, but it cannot recognise a secret that looks like prose. The
digest is therefore gitignored and only `findings-index.json` — curated and reviewed — is
committed.

**No Slack posts from this loop, deliberately.** `.agents/notifications.json`'s
`#code-changes` channel means "MR open AND pipeline green"; a channel that also means "a
sweep found something" stops meaning anything. Outcomes surface on the MR and in the state
file.

## One-time setup

### 1. Check the tools

```bash
codex --version      # 0.146.0 verified
glab auth status     # git-commit-chain pushes and opens the MR through glab
```

No new credential: `codex` and `glab` each hold their own auth.

### 2. Test before automating

```bash
# The digest alone — no model, no state written, safe to run any time
python3 scripts/session_sweep.py digest --days 7 --out /tmp/sweep
cat /tmp/sweep/digest.md

# The detector self-check (also what the timer should prove before spending a run)
python3 scripts/session_sweep.py --check

# The full decision, spawning nothing
python3 scripts/session_sweep_watch.py --dry-run
```

`--dry-run` builds the digest and reports what it *would* launch; it never calls
`systemd-run`, `codex`, or `claude`.

### 3. Run it on a timer

`~/.config/systemd/user/session-sweep.service`:

```ini
[Unit]
Description=Weekly Claude session sweep

[Service]
Type=oneshot
WorkingDirectory=/home/johnny/workflow-engine

# systemd's user PATH excludes ~/.local/bin and /snap/bin, where `claude` and `glab` live.
# Without this every tick dies with a bare ENOENT — the same gap already fixed for
# slack-watch.service. `codex` lives under nvm and is resolved at spawn time by the script.
Environment=PATH=/home/johnny/.local/bin:/usr/local/bin:/usr/bin:/bin:/snap/bin

# NOT /usr/bin/python3 — that is 3.10 on this box; pyproject requires >=3.14.
ExecStart=/home/johnny/.local/bin/python3 scripts/session_sweep_watch.py
TimeoutStartSec=900
```

`~/.config/systemd/user/session-sweep.timer`:

```ini
[Unit]
Description=Check daily whether this ISO week still needs its session sweep

[Timer]
# Daily, mid-morning — the state is keyed on ISO week, so this sweeps once per week and
# simply retries on the following days if a run was quota-held or died.
OnCalendar=*-*-* 09:30:00
Persistent=true
RandomizedDelaySec=600

[Install]
WantedBy=timers.target
```

```bash
systemctl --user daemon-reload
systemctl --user enable --now session-sweep.timer
systemctl --user list-timers session-sweep.timer
journalctl --user -u session-sweep.service -f
```

`loginctl enable-linger johnny` (if not already done for `slack-watch.timer`) so this
survives closing the WSL terminal.

### 4. Watch a real run

A launched phase logs to `.agents/reports/session-sweep/<timestamp>-<week>-<phase>.log`
(gitignored). `systemctl --user list-units 'session-sweep-*'` shows a live run.

## State

`.agents/session-sweep-state.json` (gitignored) holds one entry per ISO week: `phase`
(`author`/`review`), `status` (`handed_off` / `authored` / `reviewed` / `no-findings` /
`stalled` / `held_for_capacity`), `lease_id` (present only while `handed_off`),
`worktree_slug`, `attempt`, `digest_dir`, `mr_ref`, and `findings`. A companion
`.agents/session-sweep-state.lock` backs the flock every writer takes; it is created on
first use and never needs manual attention.

Delete the state file to reset. The cost is one already-swept week being re-swept.

## Tuning what it looks for

`HOUSE_RULES` in `scripts/session_sweep.py` is the highest-signal detector: command shapes
this repo has *already* decided are wrong (`ENVIRONMENT=test` from a host shell, `workflow
upgrade-db`, `/usr/bin/python3`, force-push, …). A hit means either an agent ignored its
instructions or an instruction never reached it — and the second is a fixable defect in the
skills, which is the whole point.

**Adding a rule requires a test in both directions** — proving it fires on the bad shape
*and* stays quiet on the good one (`tests/test_session_sweep.py`, `BAD_COMMANDS` plus the
good-command list; a guard asserts every rule has a fixture). Same discipline as
`scripts/mr_conflict_plan.py`'s allow-list: a detector nobody proved fires is a detector
nobody should trust, and its failure mode is a sweep that reports "nothing found" and looks
exactly like a clean week.

## What it will not do

- **Never merge, approve, or deploy.** `.agents/autonomy.md` bars all three.
- **Never touch `app/`, migrations, or application tests.** Instruction files and their
  supporting scripts only. Application behaviour is `review-feature` / `fix-bug`.
- **Never delete or weaken a verification stage, gate, or test.** This is the skill most
  likely to rationalise it — it will be looking at evidence that a guard cost tokens and
  found nothing that week. Making a stage cheaper is in scope; removing it is not.
- **Never delete a skill.** One quiet week is a finding to report, not grounds for removal.
- **Never open more than one MR per week.**

## Verified vs. not

**Confirmed live on this machine:** `scripts/session_sweep.py` against the real transcript
store — 23 sessions, 2,892 tool calls, 39 transcripts → a 42KB digest in 0.3s, surfacing a
real recurring `glab` flag failure (×3), a stale-path failure (×3), a 31× re-read of one
file in a single session, and 22 house-rule hits. Codex accepted the exact flag combination
the watcher builds (`approval: never`, `sandbox: workspace-write (network access enabled)`,
`reasoning effort`) on a real `codex exec` run. `session_sweep_watch.py --dry-run` built
the digest and selected the author phase without spawning.

**Confirmed via deterministic tests (62 in `tests/test_session_sweep.py`):** every house
rule fires on its bad shape and stays quiet on eight good ones; redaction removes six
credential formats (it caught a real gap — a bare `password = '...'` with no name prefix
was being missed); the correction detector rejects headless skill dispatches, which carry
the identical `userType`/`isSidechain` pair a human prompt does; malformed transcript lines
don't abort a scan; out-of-window records are excluded; `lease_id` rejects a stale writer
while the flock serialises concurrent ones; a quiet week records `no-findings` and spawns
nothing; an authored week advances to review without rebuilding the digest; terminal weeks
are inert; the attempt cap marks `stalled` instead of spawning.

**Not yet exercised end-to-end:** an actual author run (codex editing skills, writing
findings-index.json, `/git-commit-chain` opening a real MR) and the Opus review that
follows have **not** been run for real — that requires invoking the agents themselves,
which building and unit-testing the surrounding scripts does not exercise. Building this
tool is not authorization to run it unattended without a separate, explicit go-ahead. The
first real trigger — a supervised manual invocation, or the first enabled timer tick — is
the test for the SKILL.md half of this pipeline specifically.
