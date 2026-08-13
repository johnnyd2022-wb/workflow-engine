# TEST-EVALUATOR: dashboard
date: 2026-08-12
verdict: valid
invoked_as: chain stage (read-only grader, Codex `--sandbox read-only`), 2 passes
note: this file was written by the orchestrator, not the stage itself — a genuine
  `--sandbox read-only` Codex process cannot write files (confirmed live both passes:
  `error=patch rejected: writing is blocked by read-only sandbox`). Per
  `.agents/verification-chain.md` §5, the orchestrator captured each pass's verbatim final
  message from the pane transcript and persists the final (pass 2) result here.

## Pass 1 (verdict: invalid) — findings and disposition

- `tests/e2e/dashboard/test_tenant_isolation.py:115` (`test_ac16_ac17_metrics_cross_tenant_isolation`):
  "metrics isolation deliberately omits the known leaking `operational_counters.counts`
  field. It remains green with F1 present. It also checks execution counts without
  seeding any org-A execution." → **fixed**: added `start_execution(page_a, process_id)`
  plus a positive sanity assertion (`body_a["active_executions"] == 1`).
- `tests/e2e/dashboard/test_tenant_isolation.py:35` (`test_ac15_dashboard_summary_per_field_isolation`):
  "dashboard 'per-field' isolation never checks `insight_series` and seeds no positive
  revenue, so series- or sales-only tenant leaks remain green." → **fixed** (series half):
  added a baseline-vs-after comparison of all 6 series' final cumulative point for org B,
  plus a sanity check that org A's own series does move. The revenue half is documented
  as genuinely out of reach for this suite (no Xero-sandbox seed plumbing exists anywhere
  in the test suite; adding it is out of this slice's scope per the spec's own "Out of
  scope: CRMService... revenue correctness" line) rather than silently dropped.
- `tests/e2e/dashboard/test_dashboard_summary_api.py:113` (`test_ac7_ac8_compliance_summary_is_well_formed`):
  "AC7/AC8 only checks types/ranges. Hard-coded score, state, drivers, and risk count
  would pass." → **fixed**: added a new sibling test,
  `test_ac7_ac8_compliance_score_reflects_real_untracked_item_finding`, proving the score
  is computed (100 → exactly 97 after one untracked item, `untracked_items` surfaces as a
  top driver) rather than replacing the original well-formedness check.
- `tests/e2e/dashboard/test_dashboard_summary_api.py:66` (`test_ac3_window_days_empty_string_falls_back_to_default`):
  "empty `window_days` expects 200, contradicting AC3's non-integer rejection contract."
  → **disputed and confirmed false positive** (see pass 2). No change made.
- `tests/e2e/dashboard/test_dashboard_summary_api.py:161`: "claims to test PENDING
  executions but the API creates an IN_PROGRESS execution." → **fixed**: renamed
  `test_ac10_operations_counts_reflect_new_pending_execution` →
  `test_ac10_operations_counts_reflect_new_active_execution` (test body unchanged, matches
  what its own docstring already said).

## Pass 2 (verdict: valid) — grader's verbatim re-grade

"1. Metrics isolation: resolved. Org A now has a real `IN_PROGRESS` execution; org B must
report 0 while org A reports exactly 1. This proves isolation rather than comparing two
empty orgs. The known `operational_counters` leak remains separately tracked as security
finding F1 and is explicitly excluded.

2. Insight-series isolation: resolved. All six series are covered collectively with the
existing exact-key assertion, baseline comparisons, and org-A positive sanity check. A
real execution-series leak would fail. Merely deleting the local `org_id` predicate may
remain green because the global ORM tenant filter still enforces isolation; disabling
effective isolation would make it red.

3. Compliance score: resolved. After creating one untracked item, the test requires score
97, count 1, and an `untracked_items` driver. A hardcoded score of 100 would fail.
Existing helper coverage carries state and active-use-risk semantics.

4. Empty `window_days`: prior finding was a false positive/not-a-bug. `""` is replaced by
`"30"` before parsing, while `"abc"`, `"12.5"`, and `"  "` reach `int()` and fail. The
tests cover distinct, non-contradictory branches.

5. Active execution rename: resolved. The name now matches the actual `IN_PROGRESS`
behavior.

No blocking test-validity findings remain within the re-grade scope. Live tests and
mutation probes were not rerun due the stated preflight and read-only constraint."

(Orchestrator note: the "live tests... not rerun" caveat refers to the grader's own
sandbox, which has no DB access — as before. The orchestrator independently ran the full
patched suite outside the sandbox: `env -u ENVIRONMENT uv run pytest
tests/test_dashboard_summary.py tests/e2e/dashboard -q` → 61 passed; `ruff check` /
`ruff format --check` on `tests/e2e/dashboard/` → clean.)

VERDICT: valid
