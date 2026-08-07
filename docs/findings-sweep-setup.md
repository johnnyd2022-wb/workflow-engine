# Findings sweep — setup

Daily loop that pays down the repo's own documented debt. Two halves, deliberately split
by cost:

| Half | What | Cost |
|---|---|---|
| `scripts/findings_index.py` | Sweeps every findings/follow-up/known-issue section in `.agents/` and `docs/`, TODO/FIXME markers in `app/`/`tests/`/`scripts/`, and open GitLab MR descriptions. Builds and self-heals the index. | **Free** — ripgrep + a markdown parser, no model |
| `.claude/skills/findings-sweep` | Reads the index, fixes the top items by impact, ships one MR. | Real quota |

`scripts/findings_sweep_run.py` is the timer entrypoint that joins them: it always runs
the free sweep, then only starts the expensive half if there is **both** budget and work.

## Files

| Path | Tracked | What |
|---|---|---|
| `.agents/findings-index-config.json` | yes | Budget ladder, lookback window, caps |
| `.agents/findings-index.md` | no (generated) | Human-readable worklist |
| `.agents/findings-index.json` | no (generated) | Item state, statuses, history |
| `.agents/reports/findings-sweep/` | no | Run reports and `run-log.jsonl` |

The generated files are gitignored on purpose: the sweep rewrites them wholesale every
day, so committing them would drop a churning artifact into the path of every parallel
MR — the same conflict class `mr-conflict-resolver` already special-cases for
`.agents/feature-index.md`. Rebuild them any time with `sweep`; nothing is lost.

## Install

`~/.config/systemd/user/findings-sweep.service`:

```ini
[Unit]
Description=Daily findings sweep — index the repo's documented debt, work off the top items
Documentation=file:///home/johnny/workflow-engine/docs/findings-sweep-setup.md

[Service]
Type=oneshot
WorkingDirectory=/home/johnny/workflow-engine

# systemd's user PATH excludes ~/.local/bin (claude, uv, python3) and /snap/bin (glab).
# Without this the run dies with a bare ENOENT — the same gap already fixed for
# slack-watch.service and mr-conflict-watch.service.
Environment=PATH=/home/johnny/.local/bin:/usr/local/bin:/usr/bin:/bin:/snap/bin

# NOT /usr/bin/python3 — that is 3.10 on this box; these scripts use 3.11+ syntax and
# pyproject requires >=3.14.
ExecStart=/home/johnny/.local/bin/python3 scripts/findings_sweep_run.py

# The agent's own cap is 5400s (AGENT_TIMEOUT_SEC); this stays above it so systemd never
# kills a healthy run mid-MR. A stood-down run exits in under a second regardless.
TimeoutStartSec=6000
```

`~/.config/systemd/user/findings-sweep.timer`:

```ini
[Unit]
Description=Run the findings sweep daily

[Timer]
OnCalendar=*-*-* 09:15:00
# Spread the start so a machine that wakes with several timers pending doesn't fire this
# at the same instant as the others.
RandomizedDelaySec=30min
# Catch up after the laptop sleeps or WSL restarts rather than skipping the day entirely.
# Only ONE run is triggered on resume, not one per missed day.
Persistent=true

[Install]
WantedBy=timers.target
```

```bash
systemctl --user daemon-reload
systemctl --user enable --now findings-sweep.timer
systemctl --user list-timers findings-sweep.timer
journalctl --user -u findings-sweep.service -f
```

## Running it by hand

```bash
python3 scripts/findings_index.py sweep          # refresh the index (free, safe anytime)
python3 scripts/findings_index.py next           # what it would pick up today
python3 scripts/findings_index.py budget         # how many items the quota affords
python3 scripts/findings_sweep_run.py --dry-run  # full decision, launches nothing
python3 scripts/findings_sweep_run.py --force    # run even if the budget says stand down
```

## The budget ladder

The founder's rule — *two a day, more when we can afford it* — expressed as data in
`.agents/findings-index-config.json`, so tuning it never means editing code:

| 5h window | 7d window | Items |
|---|---|---|
| < 35% | < 45% | 4 |
| < 55% | < 65% | 3 |
| < 75% | < 80% | 2 ← stated baseline |
| < 88% | < 92% | 1 |
| ≥ 88% (either) | | 0 — stand down |

Both windows are tested because a Pro plan can sit comfortably under the 5h ceiling every
single day and still exhaust the week by Thursday; only the weekly number sees that
coming.

The reading comes from `~/.claude/rate-limits-cache.json`, which refreshes **only when an
interactive session renders**. So on an unattended box a missing or stale reading is
normal, not exceptional — it falls back to the baseline of 2 rather than standing down,
because treating absence as a stop signal would mean the timer never does anything. (This
is the opposite call to `slack_watch.py`, which uses the same cache to *block* a launch
and so treats staleness as untrustworthy. Different consequence, different default.)

Step 5 of the skill records observed cost per run and proposes ladder changes from a
trend across three or more runs — never from a single one.

## How the loop closes

```
sweep ─► index ─► skill picks top N ─► fixes ─► codex grades ─► MR
  ▲                                                              │
  └──────── `Findings-Index: <id>` trailer read back ◄───────────┘
```

The trailer in the MR description is the entire feedback path. The next sweep reads it
out of the merged MR and closes those items. **No trailer means the work merges and the
index never learns** — the items sit `mr-open` forever and get picked up again. The
script deliberately refuses to infer closure from title similarity, because a wrong
auto-close silently drops real work off the list.

Other self-healing paths, all exercised by `tests/test_findings_index.py`:

- Source text gone, no MR from this loop → `gone` (someone removed it by hand).
- Source text gone, MR was open → `done` (this loop shipped it).
- A closed finding reappears → reopened and flagged `regressed`.
- A human records false-positive/accepted-risk in `finding_history.py` → `suppressed`,
  permanently. The script only ever *reads* that store; granting suppression is a human's
  call per `.agents/autonomy.md`.

**Absence only counts as resolution for sources actually scanned.** If glab is missing,
unauthed, or GitLab is down — or `--no-remote` was passed, or ripgrep is absent — the
affected items are left untouched and the run prints `DEGRADED: <source> not scanned`.
Without that distinction a single glab outage would close every MR-sourced item as
resolved in one tick, silently. Check `sources_scanned` in the JSON output, or the
`DEGRADED` line, before trusting a sweep that closed a lot of items.

## Model routing

Declared in `.agents/model-routing.json`, not inline:

| Stage | Engine | Model | Effort | Access |
|---|---|---|---|---|
| `findings-sweep` | claude | sonnet | xhigh | write |
| `findings-review` | codex | gpt-5.6-sol | high | **read** |

The grader is read-only and on a separate quota pool — a grader that can edit the fix it
grades is not a grader, and a Codex exhaustion must not stall an unattended run (hence
advisory, not blocking). Outside Herdr the skill falls back to a subagent grader and must
say so in its report.

## Troubleshooting

| Symptom | Cause |
|---|---|
| Every run dies with ENOENT | systemd's PATH excludes `~/.local/bin`; see `Environment=PATH` above |
| `budget: 0` every day | 5h or 7d window at/above 88%. Check `python3 scripts/findings_index.py budget` |
| Index looks empty after a pull | Generated files are gitignored — run `sweep` to rebuild |
| Items stuck at `mr-open` | The MR merged without a `Findings-Index:` trailer |
| Same item picked every day | It is failing; at 3 attempts the skill escalates instead of retrying |
| `DEGRADED: gitlab not scanned` | glab missing/unauthed/down. Items are preserved, not closed — fix glab and re-sweep |
| `worktree already exists — standing down` | A previous run's worktree is still there; inspect or remove it |
