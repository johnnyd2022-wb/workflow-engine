---
name: prod-sentinel
description: "Scheduled watcher that closes the loop between the observability stack and fix-bug: scans error logs for NEW error signatures (deduped against a known-issues registry via scripts/error_scan.py), triages the top one with real evidence, and hands it to fix-bug to produce an MR automatically. Read-only on production telemetry; never connects to a production database. Use this skill on a schedule ('watch prod', daily/hourly error sweep), when the user asks 'anything broken in prod', or after a deploy to catch new errors early. Autonomous: opens at most one fix MR per run; the MR is the human gate."
---

# Prod Sentinel

The gap this closes: the repo has a full observability stack and a `fix-bug` front door
that consumes request_ids, and nothing connects them. An error in production waits for a
human to notice it. This skill is the wire between the two — it notices, triages, and
hands `fix-bug` a diagnosis with evidence attached.

Read `.agents/autonomy.md` first. Two constraints from it dominate this skill:

1. **Telemetry only, never the production database.** Logs, traces, and metrics are
   read-only signals. `ENVIRONMENT=production` is not a mode this skill runs in, and no
   query it issues touches customer data. If triage seems to need prod data, that is the
   moment to stop and report, not to reach further.
2. **One fix MR per run, maximum.** An unattended skill that can open unbounded MRs on a
   cron will eventually open a hundred bad ones. Second and subsequent new signatures get
   logged to the registry for the next run.

## Current signal availability — read this before claiming a clean sweep

**Production is not exporting telemetry today.** `app/config/prod.ini` sets
`grafana_data_enabled = false`, and the exporter is gated on
`otel_enabled and grafana_data_enabled` (`app/observability/tracing.py:21-24`), so no
spans or metrics leave prod. Its `otel_exporter_endpoint` is still the placeholder
`http://localhost:4317`; setting real production collector URLs is a known open item
(`docs/observability-branch-review-2026-07-10.md:201`).

So the honest state of this skill's sources:

| Source | Available | Notes |
|---|---|---|
| Local Loki (`http://localhost:3100`) | when `uv run workflow observability start` is running | real, queryable; use it to exercise this skill and to triage local errors |
| Production logs → Loki | **no** | needs `grafana_data_enabled = true` + a real collector endpoint in `prod.ini` |
| Production JSON log files | only if you point `--path` at them | `prod.ini` has `log_format = json`, so the lines are structured and parseable wherever they land |

**A run with no reachable source reports `verdict: no-signal` and names what to enable.**
It never reports "no errors found" — those are different claims, and conflating them is
how a silent monitor gets trusted. This skill becomes genuinely useful the moment prod
telemetry is switched on; until then it is a working loop pointed at a source that isn't
emitting.

## Step 1: Preflight and pick a source

```bash
python3 scripts/preflight.py --json     # capabilities.observability_stack
```

Source precedence: an explicit `--path`/`--url` the caller gave you → the local stack
(`http://localhost:3100`) if `observability_stack` is up → nothing. If the stack is down
but the run needs it, `uv run workflow observability start` is an authorised local
repair (`.agents/autonomy.md`).

## Step 2: Scan for new signatures (deterministic, not by reading logs)

```bash
python3 scripts/error_scan.py --source loki --url http://localhost:3100 --since 24h \
  --known .agents/reports/prod-sentinel/known-issues.md --json

# or, against a JSON log file:
python3 scripts/error_scan.py --source file --path <logs.jsonl> --since 24h \
  --known .agents/reports/prod-sentinel/known-issues.md --json
```

Never pull raw log lines into context to eyeball them. The script normalises volatile
parts (UUIDs, timestamps, addresses, numbers), groups by `exception type + normalized
message + route`, and returns each distinct signature with a stable 12-char
`fingerprint`, a count, sample `request_id`s, affected routes, and an org count. Forty
occurrences of one bug arrive as one line, not forty.

Read `new_signatures` (already deduped against the registry). Empty means nothing new —
report it plainly and stop. "Nothing new" is the expected outcome most runs, and
manufacturing a finding to look busy is its own failure.

## Step 3: Triage exactly one

Rank `new_signatures` and take the top one by blast radius, not raw count:

1. `affected_orgs > 1` — a multi-tenant bug outranks a loud single-org one.
2. Auth/tenant-isolation shaped (`access_denied` spikes, 403/404 on another org's ids) →
   **stop and escalate to `security-audit` instead of fix-bug**, per `fix-bug`'s own rule.
   A leak is not a bug ticket.
3. Then by count, then by recency.

Then run the **observability** skill's Triage mode with the signature's sample
`request_id`s: pull the log thread per request_id, get the traceback, localize to
file:line, correlate with recent deploys (`git log --since`) and migrations
(`alembic history`). You are producing the evidence chain `fix-bug` expects — not a
guess with a stack trace stapled to it.

## Step 4: Hand to fix-bug

Invoke **fix-bug** with the triage output as its symptom input:

```
symptom: <signature key>, <count> occurrences since <window>, <n> orgs affected
request_ids: <samples>
root_cause_hypothesis: <file:line + why, from triage>
evidence: .agents/reports/prod-sentinel/<date>-<fingerprint>.md
```

`fix-bug` owns everything after this: red repro test first, minimal fix, chain subset,
`merge-request`. Do not write the fix yourself — the skill that diagnoses should not be
the skill that decides it's fixed.

Inside Herdr with a Codex partner, `fix-bug` routes its verification through
`herdr-multi-agent-collab` on its own (Architect fixes, Breaker attacks). Pass
`verification_mode` down from preflight; don't re-derive it.

## Step 5: Registry and report

Add every new signature to `.agents/reports/prod-sentinel/known-issues.md` — including
the ones you did not action, or the next run will re-triage them from scratch:

```markdown
| fingerprint | first seen | count | signature | status | issue |
|---|---|---|---|---|---|
| `6556d62a3d75` | 2026-07-17 | 40 | AttributeError: 'NoneType' ... /api/core/executions | fix in flight | !123 |
```

`error_scan.py --known` parses the backticked fingerprint out of this table, so the
format matters. Statuses: `fix in flight` (MR open), `fixed` (merged), `accepted` (known
and tolerated, with a reason), `deferred` (logged, not actioned this run).

Run report → `.agents/reports/prod-sentinel/<date>.md`:

```markdown
# PROD SENTINEL — <date>
source: loki(<url>) | file(<path>) | none
window: <since>
scanned: <n> records, <n> errors, <n> distinct signatures
new: <n> (<fingerprints>)
actioned: <fingerprint> -> fix-bug -> !<MR> | none (why)
deferred: <fingerprints logged for next run>
verdict: clean | new-issues-found | no-signal
```

## Rules

- **`no-signal` ≠ `clean`.** If the source was unreachable or prod isn't exporting, say
  `no-signal` and name the fix (`grafana_data_enabled = true` + a real collector endpoint
  in `prod.ini`). A monitor that reports "clean" when it is blind is worse than no monitor.
- One fix MR per run. Log the rest.
- Never connect to a production database, never run a migration against one, never read
  customer data. Telemetry is the only surface.
- Never suppress a signature to keep a run quiet. `accepted` is a status with a reason,
  written down — not a silent filter.
- Tenant-isolation or auth signatures go to `security-audit`, not `fix-bug`.
- Do not action a signature whose fingerprint is already `fix in flight` — check the MR's
  state instead, and note if it's stalled.

## Scheduling

Suited to a cloud routine (`/schedule`), like `sales-watches` already is. Sensible
cadence: hourly is noise for this app's traffic; **daily**, plus a run ~30 minutes after
a deploy, catches what matters. Until prod telemetry is enabled, a scheduled run will
honestly report `no-signal` every day — which is itself a useful nag, but wire the export
first or turn the schedule off.
