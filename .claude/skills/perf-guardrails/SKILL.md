---
name: perf-guardrails
description: "Keeps page and API performance inside written budgets: server-side response times and DB query counts per request, plus browser LCP as a local tripwire, measured by tests/e2e/test_perf_budgets.py against .agents/perf/budgets.json, with scripts/perf_triage.py fusing semgrep N+1 findings and the last measured run into a priority-ordered checklist. Use this skill when the user says 'the app is slow', 'this page is slow', 'performance', 'LCP', 'load time', 'response time', 'web vitals', 'N+1 queries', 'perf budget', or wants performance checked before launch; when new-feature/review-feature/fix-bug touch a page or flow (rerun the measurement, extend the measure lists); or on a scheduled perf sweep. NOT for production user-experience monitoring (that is the RUM/observability stack), NOT for one-file code review (python-review/js-review), NOT for functional E2E coverage (e2e-playwright)."
---

# Perf Guardrails

A page that works but takes eight seconds passes every functional gate this repo has —
unit tests, E2E flows, security audit — and still loses the user. Performance regressions
ship silently because nothing turns "fast enough" into a checked property. This skill
does: budgets in a file, measured deterministically, triaged by evidence, ratcheted so
known debt can only shrink.

Read `.agents/autonomy.md`. Ships via MR; a scheduled run never blocks on a question.

## What is measured, and why (the honest doctrine)

Local wall-clock numbers on a dev laptop are noisy; treating them as ground truth
produces a flaky gate, and per spec D2 (`.agents/specs/playwright-e2e.md`) a flaky gate
gets disabled within a month. So measurement is tiered by determinism:

| metric | how | determinism | may block? |
|---|---|---|---|
| `queries` per request | SQLAlchemy `before_cursor_execute` inside the in-process E2E app | deterministic | yes — tight ceilings |
| `backend_ms` | Flask `request_started→request_finished`, server-side, median of 5 | low noise (no TLS/client) | ceiling only, set generously |
| `lcp_ms` | Chromium `largest-contentful-paint`, warm cache, median of 3 | noisy | ceiling only, very generous |

Two levels per metric in `.agents/perf/budgets.json`: **budget** (advisory — warns,
feeds the checklist, never fails) and **ceiling** (blocking — only a real regression
lands there). Query counts are the sharpest tool: they are the runtime twin of
`.semgrep/rules/performance.yml`'s static N+1 rules (this skill owns that file —
security rules stay with **security-audit**), and an N+1 shows up as a query-count jump
long before it shows up as seconds.

**Production truth is the RUM stream** (Faro web-vitals, `docs/observability-local-dev.md`),
not this suite. Local LCP is a regression tripwire; never report it as user experience.

## Steps

### 0. Preflight, then the map

```bash
python3 scripts/preflight.py --json          # needs: test DB up, chromium, semgrep
uv run python scripts/perf_triage.py --write-index
```

`perf_triage.py` is the deterministic source of truth — run it before any manual perf
archaeology, exactly as `e2e_coverage.py` is run before writing E2E tests. It fuses:
static semgrep findings (weighted by severity, attributed at feature-area granularity),
the app's live route surface, the budget measure lists, and the last measured run — into
a priority-ordered checklist. `--json` for machine output; `--check` exits 1 on any
ceiling breach or an unmeasured area with WARNING-level findings. `--write-index`
regenerates `.agents/reports/perf/priority-checklist.md`; that file is a build product,
never hand-edited, so the index can't rot.

### 1. Measure

```bash
uv run pytest tests/e2e/test_perf_budgets.py -q
```

Runs with `ENVIRONMENT` unset (same rules as the E2E suite; absent dependency is a skip
with a reason, never a failure). Writes raw results to
`.agents/reports/perf/last-run.json`. Ceiling breaches fail the run; budget breaches
surface as warnings and raise the route's checklist priority on the next triage. Rerun
`perf_triage.py --write-index` after measuring so the checklist reflects reality.

### 2. When a page or flow changes (the self-updating part)

Called by a front door after its E2E stage, or run directly after editing a page:

1. Diff the touched routes against the `measure` lists in `.agents/perf/budgets.json` —
   if a changed page/API route isn't measured, add it (keep the lists lean: core pages
   and their data endpoints, not every route; `e2e_coverage.py --json` names the route
   surface).
2. Rerun step 1. A new route gets its budget calibrated (step 4); an existing route is
   simply re-measured — a query-count jump on the diff is the N+1 the semgrep rules
   exist to catch, found at runtime.
3. Rerun the triage so the checklist reorders itself from the new evidence.

### 3. Remediate, top of the checklist first

Work the checklist in order — it is already sorted by likely-worst (observed ceiling
breaches, then budget breaches, then heaviest static findings). For each item: fix the
pattern (batch the query, add `selectinload`, paginate) or justify it with a scoped
`# nosemgrep: <rule-id>` plus reason. A fix that spans more than the perf surface —
schema changes, feature rework — hands off to **fix-bug** with the checklist row as the
bug report. After a fix, re-measure: the query-count drop is the proof, and a pinned
override ratchet (see step 4) must come down with it.

### 4. Calibrate — with evidence, never to get green

Budgets came from a real run (2026-07-18 baseline: API medians 3.6–34ms, page shells
~4ms, warm LCP 56–108ms, queries 2–11). To calibrate a new route or recalibrate after a
legitimate change: run the measurement three times, set `budget ≈ 4x` the worst median,
keep ceilings where only a real regression lands. Known debt gets a pinned override at
its current observed value (`/api/core/dashboard/summary` is pinned at 38 queries) so
any new query trips the advisory — the ratchet only ever tightens. Raising a budget or
ceiling to silence a red run is the perf version of deleting a failing test
(`.agents/autonomy.md`, "weaken a gate"): it needs a written justification in the MR.

## Report contract

- `.agents/reports/perf/last-run.json` — raw measurements (generated by the test).
- `.agents/reports/perf/priority-checklist.md` — the ordered checklist (generated by
  `perf_triage.py --write-index`).
- A run summary in `.agents/reports/perf/<date>.md` when invoked as a sweep or by a
  front door: what was measured, breaches, what was fixed, what was handed off.
  Verdict vocabulary: `within-budget | advisory-breaches | regression | degraded`
  (`degraded` = semgrep or a measurement tier didn't run — say which; never report a
  clean scan a tool didn't perform).

## Handoffs

- ← **new-feature** / **review-feature**: run after the e2e-playwright stage passes —
  functional first, then fast; a perf number for a broken page is meaningless.
- ← **fix-bug**: "slow" bug reports land here for triage evidence before a fix is coded.
- ← a schedule: weekly perf sweep (measure, triage, remediate the top item, MR).
- ← the user: "why is X slow", "check performance before launch".
- → **fix-bug**: checklist items too wide to fix inside this skill's scope.
- → **suite-warden**: if the perf test itself flakes — a flaky perf gate is suite-warden's
  jurisdiction, and the fix is never "raise the ceiling until it passes".
- → **ci-gate**: to make `test_perf_budgets.py` and `perf_triage.py --check` blocking
  jobs once they've proven stable locally.
- → **observability**: when local evidence contradicts production symptoms — the RUM
  stream settles it.

## Rules

- **Never raise a budget, ceiling, or ratchet to get green.** Recalibration requires a
  written justification in the MR; silence bought by loosening is a lie by omission.
- Wall-clock metrics never block below their generous ceilings; only query counts get
  tight ceilings. Do not "fix" a noisy LCP by making it blocking-with-retries.
- Never report local LCP as user experience — production LCP truth is the RUM stream.
- Keep the measure lists lean. Measuring every route makes the suite slow, and a slow
  perf suite is the first thing a hurried agent skips.
- Vendored bundles (`*.full.js`, `*.iife.js`) are excluded from static triage — they are
  not ours to fix; do not "clean up" findings in them.
- The checklist markdown is generated. Edit the script or the budgets, never the output.
- Never point the measurement at a shared or production database
  (`.agents/autonomy.md`); the in-process E2E boot against the local test DB is the only
  measurement environment.
