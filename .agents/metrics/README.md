# Skill metrics — the evaluation layer

This is the ledger that lets us answer *"is a skill worth its tokens?"* — the AER
evaluation-layer discipline, implemented as two append-only database tables and a
deterministic scorecard. No ML; just written-down truth about what each skill did and
whether it stuck.

Owned by `scripts/skill_metrics.py` (CLI, scorecard) on top of `scripts/metrics_db.py`
(connection, storage). Do not write to the tables by hand — go through the tool so the
schema and enums stay honest.

## Where it lives

Database **`bize_dev`**, schema **`metrics`**, on the Terraform state-db container
(`terraform/compose.yml`, port 8402). DDL: `metrics_db/schema.sql`. It used to be
`runs.jsonl` / `outcomes.jsonl` in this directory; every MR rewrote them, so they
conflicted constantly. A database row per run cannot conflict, and it is shared by every
worktree (the old files were per-checkout).

| Table | One row per… | Written by |
|---|---|---|
| `skill_runs` | skill run | the skill, when it finishes |
| `skill_outcomes` | resolved run/MR | whoever later sees the MR merged/closed/escaped |
| `perf_runs` / `perf_results` | perf test run / route+metric | `tests/e2e/test_perf_budgets.py` |
| `market_indicators` | dated, sourced market observation or estimate | `market-research` via `scripts/market_research_metrics.py` |

A run and its outcome join on **`ref`** — the MR ref (`!123`) or the branch name. They are
written at different times by different agents, which is why the store is append-only: no
run ever rewrites another's row. The agent role (`bize_dev_rw`) has `INSERT` and `SELECT`
only — it cannot update or delete history.

Each run row also records `commit_sha`, `mr_iid` and `pipeline_id` (from `CI_*` variables
or git) so a result can be tied to the change that produced it.

## Access

| Who | How |
|---|---|
| Agents / skills on this machine | automatic: `$BIZE_METRICS_PASSWORD`, or KeePassXC entry `workflow-engine/bize-dev-db-rw` when `$KEEPASS_PASSWORD` is set. Never prompts. |
| CI | project CI/CD variables `BIZE_METRICS_HOST/PORT/DB/USER/PASSWORD` |
| Schema changes | `python3 scripts/metrics_db.py migrate` (local; uses the `bize_dev_admin` role via `docker exec`) |

**If the database is unreachable nothing breaks.** Writes are spooled to
`~/.local/state/bize-metrics/spool.jsonl` and flushed by the next successful call; reads
(`digest`, `sweep`) say so and exit 0; the CI `data_stores` check reports SKIPPED. Check
state with `python3 scripts/metrics_db.py status`.

For the skill-run ledger, setting `$METRICS_DIR` switches to JSONL files in that directory (the unit-test hook and a
fully offline mode) — the schema below is that file shape, and the column names match.

## Market research indicators

`market_indicators` is an append-only time series for sourced market measurements, separate
from the skill-run ledger. `scope_key` is the stable product/category and geography slug;
`metric_key` identifies one comparable series within it. Each row records the measurement
date, optional measured period, point value or estimate range, unit, geography, segment,
source reference, source publication date, confidence, method, report path, cadence, and optional
above/below threshold. The pair `(report_path, metric_key)` prevents duplicate imports of
the same report. A revised estimate belongs in a new dated report, preserving history.

The skill records through `python3 scripts/market_research_metrics.py record --file <path>`
and reads a scope through `python3 scripts/market_research_metrics.py history --scope <slug>`.
The recording command validates the whole batch before writing; if the DB is unavailable,
rows use the same local spool as skill runs. Apply `python3 scripts/metrics_db.py migrate`
once to create the table and grant the existing read/append role access.

## `skill_runs` columns

```
ts          timestamptz   set by the tool
skill       text          required
run_type    text          chained | scheduled | interactive
scope       text          feature slug or area, or null
findings    integer       count opened this run (>= 0)
verdict     text          clean | patched | findings-open | could-not-reproduce | error | skipped
ref         text          MR ref or branch — the join key, or null
duration_s  double        wall time if known, else null
notes       text
commit_sha, mr_iid, pipeline_id   provenance, filled automatically
```

## `skill_outcomes` columns

```
ts, ref (required — matches a run's ref), outcome, skill (optional), notes
outcome: merged | closed | amended | escaped | superseded
```

- **merged** — the fix/feature shipped. The finding earned its keep.
- **closed** — the MR was rejected without merging. False positive / not worth it.
- **amended** — merged, but a human reworked the diff. Counts as accepted, tracked apart.
- **escaped** — a defect this skill *should* have caught reached prod (attributed later).
- **superseded** — replaced by a newer run before it resolved. Neither credit nor blame.

The **last-written** outcome per `ref` wins, so an MR closed then reopened-and-merged
scores as merged.

## How skills append (one line, no ceremony)

```bash
# on finishing a run
python scripts/skill_metrics.py record --skill security-audit --run-type chained \
    --scope inventory --findings 3 --verdict patched --ref feat/inventory --duration 42

# when the MR's fate is known
python scripts/skill_metrics.py outcome --ref '!123' --outcome merged
```

## Closing the loop automatically (`sweep`)

`outcome` above assumes a human remembers to record the MR's fate — and mostly nobody does.
`sweep` closes that gap: it asks **glab** what became of every ref that has a run but no
outcome, and writes `merged`/`closed` for the ones glab can prove.

```bash
python scripts/skill_metrics.py sweep             # write outcomes for resolved refs
python scripts/skill_metrics.py sweep --dry-run   # show what it would write, write nothing
```

It only writes what glab can prove (merged/closed). `amended` and `escaped` are human
judgments — the sweep never manufactures them. A ref that was never an MR (a scheduled scope
like `security-audit/2026-07-17`) stays open, correctly. Runs unattended-safe — no glab, or
an unauthed/rate-limited one, means "resolve nothing", never a crash.

## Reading it

```bash
python scripts/skill_metrics.py scorecard          # full human table
python scripts/skill_metrics.py scorecard --json    # machine-readable
python scripts/skill_metrics.py digest             # the few learnings worth reading each session
python scripts/skill_metrics.py --check             # CI: DB reachable and schema complete (or SKIPPED)
```

`acceptance_rate = (merged + amended) / (merged + amended + closed)` — escaped and
superseded never enter the denominator. A skill with a low acceptance rate is crying wolf;
a skill with escaped defects missed something it owns. Both are signals for `skill-smith`
to improve or retire it.

The **digest** is the scorecard boiled down to only what a session should change behaviour
over — crying-wolf skills, escaped defects, and refs still awaiting an outcome. `preflight`
surfaces it at the top of every code workflow.

## Perf baselines

`perf_baseline` (a view) is the median of the last 20 main-branch runs per route + metric.
Only main-branch CI runs feed it, so an MR cannot move its own goalposts. Gating policy and
the CI jobs (`perf_baseline`, `mr_perf`) are described in `.claude/skills/perf-guardrails`.
