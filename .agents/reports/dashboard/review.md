# REVIEW: dashboard
date: 2026-08-12
baseline: tests green (4/4, tests/test_dashboard_summary.py)
verdict: patched

## Why this slice
`dashboard` was one of five never-reviewed slices (`dashboard`, `crm`, `dilution-calculator`,
`shell`, `demo-data`) surfaced by `scripts/feature_index_sweep.py`'s picklist. Chosen by the
user from that list — a leaf slice (nothing else in the app depends on it), so blast radius
is contained to itself. No spec existed; one was reconstructed from the code
(`.agents/specs/dashboard.md`, `status: reconstructed`, confirmed with the user before the
chain ran).

| stage | verdict | findings | report |
|---|---|---|---|
| migration-safety | skipped | n/a — slice has no models/migrations of its own | — |
| security-audit | findings-open → **fixed** | 1 (F1: cross-tenant leak of `operational_counters` on `/api/core/metrics`) | `security-audit.md` |
| e2e-playwright | findings-open (by design — cross-refs F1) | gap-filled: 29 new tests across 4 new files under `tests/e2e/dashboard/` | `e2e-playwright.md` |
| unit coverage / test-author | patched | closed 54→6 uncovered statements in the slice's own line range; 27 new tests in `tests/test_dashboard_summary.py` | `test-author.md` |
| test-evaluator | invalid → **valid** (2 passes) | 5 findings: 3 real gaps patched, 1 false positive disputed and confirmed, 1 minor rename | `test-evaluator.md` |
| perf-guardrails | clean | 0 breaches; added `/api/core/metrics` to the measured-routes list (was absent) | `perf-guardrails.md` |
| observability | clean | nothing to instrument (no state-changing ops, no per-ID access surface in this slice); existing CRM-failure log line now has test coverage | `observability.md` |
| ci-gate | clean | all additions covered by existing jobs, no CI config change needed | `ci-gate.md` |

## Findings and disposition

### F1 — cross-tenant leak, `GET /api/core/metrics` (security-audit.md) — FIXED
`operational_counters.counts` returned `get_counter_snapshot()`, a process-wide `dict`
with no `org_id` key — every tenant sharing a worker process saw the same internal
failure-counter snapshot as every other tenant. Severity was assessed low (the only keys
incremented are internal anomaly counters — parse failures, budget-exceeded events — not
PII or business data), but it was still a genuine tenant-isolation violation on an
otherwise correctly org-scoped endpoint, and directly contradicted the slice's own stated
assumption (spec AC17).

**Fix**: removed the `operational_counters` field from `/api/core/metrics`'s response
entirely (`app/core/backend/backend.py:4864-4910`, plus the now-unused
`get_counter_snapshot` import). Chose this over the alternative (retrofitting per-org
buckets into `inc_counter`'s 7 call sites across 4 files) because the field had **zero
frontend consumers** — confirmed by grep, nothing in `app/**/*.js` reads
`operational_counters` — so there was no product value being traded away, and the
narrower fix keeps this review's blast radius to the slice it's reviewing rather than
reaching into `internal_counters.py`'s callers across `compliance-checks` and `execution`.
Regression guard: `test_metrics_api.py::test_ac16_metrics_returns_well_formed_shape_for_fresh_org`
now asserts the field's absence. Recorded in `.agents/history/findings.jsonl`
(sig `9014a535e2dc`, verdict `fixed`).

### test-evaluator's 5 findings (pass 1) — 3 fixed, 1 disputed, 1 renamed
1. **Metrics isolation didn't seed an org-A execution** (so `active_executions`/
   `completed_executions` isolation was unproven — two empty orgs trivially match) — fixed:
   `test_ac16_ac17_metrics_cross_tenant_isolation` now calls `start_execution` and asserts
   org A sees its own count.
2. **Dashboard per-field isolation never checked `insight_series`** — fixed: added a
   baseline-vs-after comparison of all 6 series for org B, plus a positive sanity check
   that org A's own series moves. The revenue-leak half of the same finding (no positive
   revenue seeded) is documented as genuinely out of reach without Xero-sandbox seed
   plumbing this suite doesn't have anywhere — out of scope per the spec's own boundary,
   not silently dropped.
3. **AC7/AC8's compliance test only checked shape**, not that the score reflects real
   findings — fixed: added `test_ac7_ac8_compliance_score_reflects_real_untracked_item_finding`,
   which proves the score is computed (100 → exactly 97 after one untracked item) rather
   than replacing the original well-formedness check.
4. **Empty `window_days` "contradicts" AC3's rejection contract** — disputed and confirmed
   a false positive on re-grade: the two tests assert different, non-conflicting code
   branches (`"" or "30"` short-circuits before `int()` ever runs). Both independently
   re-run and pass. Recorded in `.agents/history/findings.jsonl` (sig `7dc00fcf52fe`,
   verdict `false-positive`) so a future audit doesn't re-litigate it.
5. **Test named "pending" but exercises IN_PROGRESS** — renamed
   `test_ac10_operations_counts_reflect_new_pending_execution` →
   `..._new_active_execution` (body unchanged; the docstring already said IN_PROGRESS).

Codex re-graded the patched batch and returned `VERDICT: valid`.

### Notable process incident: a stalled chain stage
The `test-author` herdr-tab stage (Claude, headless `-p`) completed its actual work (27
tests, all correct and passing) but then stalled indefinitely waiting on a background
`pytest --cov` run that had already exited — three consecutive "still waiting" turns
running `true` with no state change, no process left running. Headless `-p` sessions
appear not to reliably deliver background-task completion back to themselves. The
orchestrator closed the stalled pane, independently verified the diff it had already
written (ran the tests, confirmed pass, confirmed coverage gap closed, confirmed
`ruff clean`), and wrote `test-author.md` on its behalf rather than discarding real,
correct work over a plumbing failure. Two Codex (`--sandbox read-only`) stages
(`security-audit`, `test-evaluator` ×2) hit a related but different and expected issue —
the sandbox correctly rejects the stage's own report-file write — handled per
`.agents/verification-chain.md` §5 by capturing the grader's verbatim final message from
the pane transcript.

## Full-suite re-verification after F1's patch
`env -u ENVIRONMENT uv run pytest tests/ -q -k "not live_server"` — **1456 passed, 1
skipped, 30 deselected (live_server), 0 failed.** Confirms removing
`operational_counters` from `/api/core/metrics` didn't break anything outside this
slice (nothing else in the app reads that field — verified by grep before the fix,
confirmed by the full suite after it).

## Before / after
- Route-level test coverage on `/api/core/dashboard/summary` and `/api/core/metrics`:
  **zero → 29 e2e tests** (4 new files under `tests/e2e/dashboard/`) + **4 → 31 unit
  tests** in `tests/test_dashboard_summary.py` (27 added).
- Statement coverage of the slice's own line range (`backend.py:4183-4912`): **54 → 6**
  uncovered statements (the 6 remaining are isinstance/type-guard edge branches judged
  lower priority than the CRM-exception path that was closed).
- Security: **1 real tenant-isolation finding, fixed** (F1).
- Perf: **0 breaches**; measured-routes list gap closed (`/api/core/metrics` was
  unmeasured, now in budget at 9ms/6 queries against a 150ms/15-query default budget).
- Test validity: **invalid → valid** after 2 test-evaluator passes; 1 finding confirmed
  false-positive and recorded so it isn't re-flagged.

## What remains open (by design, not oversight)
- **AC4** (`window_days` accepted, validated, and echoed but never used to scope any
  query) — flagged in the spec as a product/API-contract decision, not a bug. Left as-is;
  the audit's job was to surface it clearly, which it now does (spec AC4, plus 8
  parametrized tests in `test_dashboard_summary_api.py` that pin down exactly which
  branches are and aren't affected).
- **Revenue-leak coverage gap** in `test_ac15_dashboard_summary_per_field_isolation` — no
  positive revenue seeded for org A, so a sales-only leak wouldn't be caught by that test
  specifically (AC13's null-baseline test is the closest existing coverage). Would need
  Xero-sandbox seed plumbing this test suite doesn't have anywhere yet — a bigger lift
  than this review's scope, flagged for whoever picks up CRM/Xero e2e test infrastructure
  next.
- **`scripts/e2e_coverage.py`'s non-recursive glob** under-reports every subdirectory E2E
  suite in the repo (not just this review's `tests/e2e/dashboard/` — also `activity_log`,
  `reconciliation`, `traceability`). Not fixed here (out of scope, not a CI gate), flagged
  in `e2e-playwright.md` and `ci-gate.md` for a tooling-debt pass.
- **`core-active-batches-graph.js`** — feature-index lists it under this slice's frontend;
  it's actually bound to the `/core` hub page (`core2.html`), not `/core/dashboard`. Index
  labeling drift, not a code defect — `docs-truth`'s territory, noted in the spec's "Out of
  scope" section rather than hand-edited here.

## Rules followed
- No refactor beyond what findings required (F1's fix was the minimal field-removal, not a
  counter-architecture rewrite).
- Pre-existing state was green (baseline.md) — nothing quietly fixed and forgotten.
- The reconstructed spec's `ASSUMPTION` lines were confirmed with the user before the
  chain ran, so downstream stages graded against agreed criteria, not silently-invented
  ones.
