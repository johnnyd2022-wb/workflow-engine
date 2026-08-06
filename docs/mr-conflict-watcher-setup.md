# MR conflict watcher setup

Polls GitLab every 2 minutes for open MRs it reports as conflicted, and hands each one to
the `mr-conflict-resolver` skill: resolve what's mechanical (shared tracking/index files
every autonomous skill writes), push a new commit, and escalate anything that changes
logic in a conflicting way instead of guessing.

## Why this exists

This repo runs a lot of unattended skills off `main` in parallel worktrees
(`perf-guardrails`, `review-feature`, `dependency-update`, ...), and several of them write
to the same handful of shared files — `.agents/feature-index.md`, `.agents/reports/perf/last-run.json`,
`uv.lock`, the metrics/history ledgers. Two branches independently touching one of those is
not a real disagreement, but GitLab still reports it as a conflict and it sits there until
someone notices and rebases by hand. This closes that loop the same way `slack_watch.py`
closes the Slack-mention gap.

## How it is put together

```
systemd timer (every 2 min)
  └─ scripts/mr_conflict_watch.py    ← plain `glab mr list`/`mr view --output json`. Zero tokens.
       ├─ nothing conflicted?  exit 0        ← the common case, costs nothing
       └─ MR has_conflicts=true, not yet handled for this GENERATION (source_sha, target_sha)
          (or eligible again -- see "needs-human retry" below):
            └─ mint lease_id + worktree_slug, reserve `handed_off` on disk (locked,
               BEFORE spawning — see State below)
            └─ detached systemd-run unit
                 └─ claude -p /mr-conflict-resolver --model claude-sonnet-5 --permission-mode auto
                      ├─ isolated worktree (lease-qualified path), merge target branch
                      ├─ scripts/mr_conflict_plan.py classifies deterministically (not the model)
                      ├─ mechanical-only plan → apply, push, recheck GitLab
                      │    └─ mr_conflict_watch.py record --lease-id "$LEASE_ID" --status resolved
                      └─ any semantic file at all → whole merge aborted, MR comment + needs-human label
                           └─ mr_conflict_watch.py record --lease-id "$LEASE_ID" --status needs_human --blocker "..."
                 └─ ExecStopPost=scripts/mr_conflict_watchdog.py (same lease_id)
                      ├─ clean exit, outcome recorded under this lease → nothing to do
                      ├─ clean exit, lease still `handed_off` → record --status stalled (run didn't finish its job)
                      └─ non-zero exit → quota signature? hold + let the next poll tick retry
                                          otherwise → record --status stalled for a human to re-drive
```

**The script reads; the skill writes — through one deterministic CLI, not by hand-editing
JSON.** `glab mr list`/`mr view` need no extra credential beyond `glab`'s own stored auth
(`glab auth login`) — there is no bot token to manage here, unlike the Slack watcher. The
skill's only way to record an outcome is `python3 scripts/mr_conflict_watch.py record
--mr-iid N --lease-id <id> --status resolved|needs_human|stalled [--blocker "..."]` —
`--lease-id`, not sha or status, is the actual authority; see State below for why.

## Design choices worth knowing

**Merge, not rebase.** The skill merges the MR's actual target branch into the MR's own
branch and pushes a plain commit on top — never a rebase, never a force-push. A merge only
ever *adds* a commit, so the founder opens the MR and sees exactly what changed to make the
branches converge, reviewable on its own, with nothing rewritten underneath it. See
`.claude/skills/mr-conflict-resolver/SKILL.md` Step 1 for the full reasoning.

**Mechanical vs semantic is a deterministic classifier, not the model's judgment.**
`scripts/mr_conflict_plan.py` implements the exact same four-row allow-list as executable
Python (append-only ledgers via `.gitattributes` `merge=union`, the feature-index
`reviewed:` field via its own sweep script, the perf baseline via newest-timestamp-wins,
`uv.lock` via regeneration), tested against real synthetic git fixtures in
`tests/test_mr_conflict_plan.py` — the skill executes the resulting plan, it does not
classify by reading a table and using judgment. Everything else, by default, comes back
semantic: an MR comment naming the exact blocker, plus a `needs-human` label so the
watcher leaves it alone until a human removes the label.

**No Slack posts from this loop, deliberately.** `.agents/notifications.json`'s
`#code-changes` channel is reserved for "MR open AND pipeline green" — a mid-run failure or
an escalation posted there would break that discipline (a channel that means two things stops
meaning anything). Escalations surface on the MR itself (comment + label) and through
`scripts/skill_metrics.py digest`, which `preflight` already prints at the top of every code
session.

**Quota handling is reused, not reinvented.** `scripts/mr_conflict_watch.py` imports
`scripts/slack_watch.py` directly for its quota-cache gate (`quota_ok_to_launch`,
`estimate_reset_at`) — same statusline-cache-based best-effort check, same reasoning. There
is no separate fast-path resume timer: at a 2-minute poll cadence the durable per-tick
reconciliation (`reconcile_held`) is fast enough on its own.

**Any semantic conflict aborts the whole merge, never a partial one.** `git merge --abort`
discards everything, including mechanical resolutions already made earlier in the same
attempt — so the skill doesn't try to land the mechanical files and flag only the rest.
One semantic file anywhere means the whole thing escalates; the mechanical files pick up
automatically on the next run, once a human clears the escalation.

**A conflict's identity is `(source_sha, target_sha)`, not source sha alone.** GitLab
computes `has_conflicts` against the *current* target branch tip, not a fixed one —
verified live: MR `!144`'s `diff_refs.start_sha` (only available from `glab mr view`, not
`mr list`) equaled the actual current tip of `main`. The target branch moving forward can
therefore reopen an already-`resolved` MR on the exact same source sha. Every reservation
records both; `eligible_work` and `launch()` compare the pair, never sha alone.

**An unknown `target_sha` is never treated as a new generation.** `diff_refs` is computed
asynchronously by GitLab and a `glab mr view` call can fail transiently — either leaves
`target_sha` as `None` for that tick. Comparing `None` against a real, known value looks
identical to the target branch actually moving, which would reopen an MR a live lease is
already handling and let a second resolver launch over the first. `_generation_known()` is
the one gate every caller (`eligible_work`, `reconcile_held`'s fallback, `launch()` itself)
checks first: unknown means "make no decision this tick," never "treat as changed."

**`reconcile_held`'s clear is fenced against the exact hold it actually inspected.** The
direct `glab mr view` verification call takes real wall-clock time; by the time its result
comes back and the clear is ready to write, a completely different hold (or an active
lease from a fresh reservation) could have replaced the held entry entirely — including
one that happens to share status, sha, target_sha, and cached `scheduled_resume_at`, which
is exactly the case a four-field comparison couldn't tell apart (see `hold_id` below). The
write only applies if the on-disk entry — checked fresh, under the same lock — still
carries the exact `hold_id` that was inspected before the network call; otherwise it's
logged as superseded and left alone.

**Needs-human retry is label-driven, not generation-driven.** Every other terminal outcome
(`resolved`, `stalled`) stays untouched until the generation changes (either sha). A human
removing the `needs-human` label is different: `eligible_subset` already excludes anything
still carrying that label, so the only way a `needs_human` MR can reach `eligible_work`
again at all is that the label was just lifted — and that removal *is* the retry signal,
checked ahead of the generation comparison, regardless of whether a new commit also
landed.

**Every state write is locked AND lease-fenced.** `update_mr_state()` does a flock-guarded
read-modify-write of exactly one MR's entry — the poller, the detached watchdog, and the
`record` CLI the skill calls all go through it, never a bare load/mutate/save. Locking
alone stops two writers tearing the same bytes, but not a *stale* one: an old resolver's
watchdog finishing late, after a newer reservation has already replaced it, can still
validly re-acquire the lock and overwrite a newer outcome with an older one. That's what
`lease_id` closes — every reservation mints a fresh one, and `record`/`hold`/finalize all
require it to match the currently active lease before writing anything; a mismatch is
logged and ignored, never applied. The reservation (lease, sha, target_sha, worktree_slug)
is written to disk *before* the resolver is spawned, not after, so a watchdog's later
write is always checked against the real, already-persisted lease regardless of how fast
the run is. `worktree_slug` is derived from `lease_id`, not from the attempt counter — a
label-driven `needs_human` retry resets the attempt counter to 0 but always gets a fresh
lease, so it can never collide with the worktree/branch a prior escalated attempt left
behind.

**Mission Control reporting is opt-in and best-effort**, same gate as
`scripts/agent_launch.py`: set `MISSION_CONTROL_REPORT=1` and have the `mission-control`
binary on PATH, and the watcher reports `start` at launch while `record` reports `finish`
with `--mr-ref "!<iid>"` and the right `--state` (`completed` / `blocked` / `failed`) once
the outcome is known. Missing, disabled, or failing silently changes nothing about whether
a resolver run launches, waits, or completes — see
`.agents/plans/herdr-mission-control-plan.md` gate 3. The gate is explicitly propagated
into the transient resolver unit (`--setenv=MISSION_CONTROL_REPORT=1`) when enabled —
a transient `systemd-run` unit gets a fresh environment, not the parent service's, so
without this the resolver and its watchdog would never see the gate the poller itself
saw, and `report start` would fire with no `report finish` ever able to follow it. Every
path that can end a lease's ownership of a run — resolved, needs_human, stalled, a spawn
failure, and a quota hold — settles that run; a quota hold in particular hands off to a
fresh run_id on its next launch, so the one it's abandoning has to be finished first or
it's stuck `running` forever.

**Process supervision actually bounds the resolver's lifetime, not just the watcher's
patience.** `eligible_work`'s staleness check (a `handed_off` older than
`agent_timeout_sec + crash_grace_sec`) is a heuristic about what the WATCHER believes,
not proof the resolver process is dead — treating it as proof would let a second
resolver launch while a first, merely slow one is still alive and fully capable of
`git push`. The transient unit sets `RuntimeMaxSec=agent_timeout_sec` (strictly under the
watcher's own staleness threshold) so systemd initiates a stop before a retry could ever
be minted, `KillMode=control-group` (not `process`) so that stop kills every process the
unit ever forked — `KillMode=process` only signals the one tracked PID, and
`bash -c "claude ..."` makes `claude` a child of that PID, not the PID itself — and an
explicit `TimeoutStopSec` (derived from `crash_grace_sec`, strictly below it, config
validated to be at least 2s) bounds systemd's own SIGTERM-to-SIGKILL window. That last
property matters on its own: `RuntimeMaxSec` only *starts* a stop, and without a
per-unit `TimeoutStopSec`, the final kill waits on the machine-wide
`DefaultTimeoutStopSec` (~90s, and genuinely configurable per manager) — a value this
code has no way to see or guarantee fits inside `crash_grace_sec`. Setting it explicitly
makes "dead before the watcher retries" a property of the unit's own definition, not an
assumption about whatever the local systemd happens to default to. The command also
leads with `exec` so there's normally only one process to begin with.

**Every hold has its own unique `hold_id`, checked instead of a field proxy.** A
`held_for_capacity` entry can be superseded by a *different* hold that happens to share
the same status, sha, target_sha, and cached `scheduled_resume_at` — a retry landing
back in the same held state for the same generation looks identical to the original
hold under a four-field comparison, but is not the same logical hold. Every path that
enters `held_for_capacity` (`launch()`'s quota branch, the watchdog's quota-mid-run
branch) mints a fresh `hold_id`; `reconcile_held`'s eventual clear only applies if the
on-disk entry, checked fresh under the lock, still carries the exact `hold_id` that was
inspected before the (real, wall-clock-taking) `glab mr view` verification call — a
missing `hold_id` (shouldn't happen once every hold-creating path mints one) is treated
as "can't prove this safely" and leaves the hold in place rather than clearing on a
guess.

**`lease_id` and `hold_id` are separate authorities for separate states, and each is
consumed — along with everything that only described that state — the instant it's
exited.** `handed_off` carries `lease_id`, never `hold_id`, `scheduled_resume_at`, or
`held_reason`; `held_for_capacity` carries `hold_id` and those two scheduling fields,
never `lease_id`. Every transition — a hold resuming into a fresh launch, a
stale/exhausted attempt going `stalled`, a reservation resolving — pops everything that
belonged to the state being left, so an entry never carries two tokens from two
different domains, or scheduling metadata describing a hold it's no longer in. The
scheduling fields don't grant any authority themselves, but leaving them behind
misdescribes the entry's actual state to anything reading it later (a human inspecting
the state file, a Mission Control diagnostic) — the kind of unclean invariant that's
cheap to keep exact and easy to regret leaving loose.

**Feature-index classification diffs git's own ours/theirs objects, never the merged
file's embedded conflict markers.** `_classify_feature_index` reads `git show :2:<path>`
and `:3:<path>` directly and diffs the two line lists — it does not scan the merged
working-tree file for `<<<<<<<`/`=======`/`>>>>>>>` at all. A hand-rolled marker parser
is exploitable: if either branch's actual CONTENT contains a line that merely looks like
a marker (e.g. prose reading `>>>>>>> some-branch-name`), the parser mistakes it for
git's real closing marker and silently drops every genuine line after it — a real
semantic conflict then gets classified mechanical. Diffing the two sides git already
knows about sidesteps the ambiguity entirely: there's no marker syntax to parse, only
line lists to compare, and no string can impersonate a diff opcode.

## One-time setup

### 1. `glab` auth

```bash
glab auth status   # should already show "Logged in to gitlab.com as ..."
```

If not: `glab auth login`. No KeePassXC entry needed — this watcher never touches a
separate credential, it rides on the same `glab` auth every other skill in this repo uses.

### 2. Test before automating

```bash
python3 scripts/mr_conflict_watch.py --dry-run    # lists conflicted MRs, launches nothing
```

`--dry-run` is read-only: it lists what's conflicted and what it *would* launch, and never
calls `systemd-run` or `claude`.

### 3. Run it on a timer

`~/.config/systemd/user/mr-conflict-watch.service`:

```ini
[Unit]
Description=GitLab MR conflict watcher

[Service]
Type=oneshot
WorkingDirectory=/home/johnny/workflow-engine

# systemd's user PATH excludes ~/.local/bin and /snap/bin, where `claude` and `glab` live.
# Without this every tick dies with a bare ENOENT — same gap already fixed for slack-watch.service.
Environment=PATH=/home/johnny/.local/bin:/usr/local/bin:/usr/bin:/bin:/snap/bin

# Opt-in to Mission Control's best-effort start/finish reporting for each resolver run.
# Omit this line entirely to leave reporting off -- nothing else in the pipeline requires
# it (see docs above: a missing/disabled report never affects launch, wait, or completion).
Environment=MISSION_CONTROL_REPORT=1

# NOT /usr/bin/python3 — that is 3.10 on this box; pyproject requires >=3.14.
ExecStart=/home/johnny/.local/bin/python3 scripts/mr_conflict_watch.py
TimeoutStartSec=60
```

`~/.config/systemd/user/mr-conflict-watch.timer`:

```ini
[Unit]
Description=Poll GitLab for conflicted MRs every 2 minutes

[Timer]
OnBootSec=2min
OnUnitActiveSec=2min
Persistent=true

[Install]
WantedBy=timers.target
```

```bash
systemctl --user daemon-reload
systemctl --user enable --now mr-conflict-watch.timer
systemctl --user list-timers mr-conflict-watch.timer
journalctl --user -u mr-conflict-watch.service -f
```

`loginctl enable-linger johnny` (if not already done for `slack-watch.timer`) so this
survives closing the WSL terminal.

### 4. Watch a real resolver run

Once the timer is enabled, a launched run logs to
`.agents/reports/mr-conflict-watch/<timestamp>-mr<iid>-a<attempt>.log` (gitignored,
machine-local). `journalctl --user -u mr-conflict-watch.service -f` shows each poll tick;
`systemctl --user list-units 'mr-conflict-*'` shows a launched run while it's active.

## State

`.agents/mr-conflict-watch-state.json` (gitignored) tracks one entry per MR: `sha` and
`target_sha` (the generation last handled), `status` (`handed_off` / `resolved` /
`needs_human` / `stalled` / `held_for_capacity`), `lease_id` (the active reservation's
token, present only while `status == "handed_off"`), `hold_id` (the active hold's token,
present only while `status == "held_for_capacity"` — a fresh one every time, never
reused), `worktree_slug`, `mission_run_id` (if Mission Control reporting is enabled),
and attempt count. Keyed on the generation
`(sha, target_sha)` for `resolved`/`stalled` — a new push OR the target branch moving
forward both look like fresh work. `needs_human` is keyed on the label instead (see
above). A companion `.agents/mr-conflict-watch-state.lock` (also gitignored) backs the
flock every writer takes; it's created on first use and never needs manual attention.
Delete the state file to reset everything; the cost is a few MRs getting re-attempted
that were already resolved (harmless — `needs-human` MRs stay off-limits via their live
GitLab label regardless of what the state file says, since that label is what
`eligible_subset` itself filters on, not the state file).

## What it will not do

- **Never force-push.** A rejected push (the branch moved after fetch) triggers a
  refetch-and-remerge retry, not `--force` or `--force-with-lease`.
- **Never merge, approve, or deploy anything** — `.agents/autonomy.md` bars all three
  regardless of what this skill finds.
- **Never guess at a logic conflict.** The mechanical allow-list, implemented in
  `scripts/mr_conflict_plan.py`, is deliberately narrow; a new kind of recurring conflict
  doesn't get auto-resolved just because it looks structured — it needs a new row (and a
  synthetic fixture proving it) added to that script first, by a human who's looked at it.

## Verified vs. not

**Confirmed live against this repo's real GitLab project:** `glab mr list --output json`
returns `has_conflicts` and `detailed_merge_status` directly usable with no extra
computation — three real open MRs (`!142`, `!143`, `!144`) were conflicted at the time
this was built and hardened, which is what the `--dry-run` example above was checked
against, both before and after the concurrency/label-retry fixes below.

**Confirmed via deterministic tests and manual smoke tests (no live MR touched, 73 tests
across `test_mr_conflict_watch.py` and `test_mr_conflict_plan.py`):** the `record` CLI's
locked, lease-fenced read-modify-write round-trips correctly and rejects stale/mismatched
leases; two overlapping launch attempts on the same generation spawn exactly one resolver;
a resolver finishing before its own launch() call completes its bookkeeping still leaves
the correct terminal state; a spawn failure settles its Mission Control run instead of
orphaning it; `.gitattributes` `merge=union` actually auto-resolves a real git conflict on
an append-only ledger in a disposable temp repo (with a negative control proving the same
conflict WOULD occur without the attribute); `scripts/mr_conflict_plan.py` correctly
classifies each mechanical allow-list row AND a mixed mechanical+semantic merge as a whole
semantic plan, against real synthetic git fixtures; `reconcile_held` never treats a failed
discovery call, or an MR merely filtered by draft/label, as proof an MR stopped
conflicting — it verifies directly before clearing a hold; a target branch advancing
reopens an MR resolved on the same source sha; a `needs_human` MR becomes eligible again
(with a fresh lease and worktree slug) the moment its label is removed, without needing a
new commit.

**Not yet exercised end-to-end:** an actual resolver *skill* run (worktree, merge, running
`mr_conflict_plan.py` for real, push, GitLab recheck, `record` call) has not been launched
for real — that requires invoking the Claude agent itself, which building and
unit-testing the surrounding scripts does not exercise. Building this tool is not
authorization to run it unattended against a live MR without a separate, explicit
go-ahead. The first real
trigger (a genuinely conflicted MR the timer picks up, or a supervised manual invocation
against one) is the test for the SKILL.md half of this pipeline specifically.
