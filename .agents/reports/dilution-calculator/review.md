# REVIEW: dilution-calculator
date: 2026-08-21
baseline: tests green (35 passed, 9 skipped-live-server N/A — no pre-existing failures)
verdict: patched

## Selection
Picked via `scripts/feature_index_sweep.py`'s `picklist_order` (never-reviewed-first).
Of the 4 never-reviewed candidates (dilution-calculator, compliant-platform,
compliant-nz-alcohol, demo-data), the user chose dilution-calculator — the smallest,
lowest-risk, leaf slice (no models, no tenant data, `depended on by: (leaf)`).

## Spec
`.agents/specs/dilution_calculator.md` existed (`status: built`), read against live code
before trusting it — matched with no drift. Left as-is; not re-marked `reviewed` here
(spec status field is separate from the index's `reviewed:` line, which the sweep in
Step 5 updates).

| stage | verdict | findings | report |
|-------|---------|----------|--------|
| baseline | clean | 0 pre-existing failures | `.agents/reports/dilution-calculator/baseline.md` |
| security-audit | clean | 0 | `.agents/reports/dilution-calculator/security-audit.md` |
| e2e-playwright | patched | 7 gaps closed | `.agents/reports/dilution-calculator/e2e-playwright.md` |
| test-author (unit coverage) | patched | 4 gaps closed | `.agents/reports/dilution-calculator/test-author.md` |
| test-evaluator | valid | 1 gamed test found & fixed (2-round) | `.agents/reports/dilution-calculator/test-evaluator.md` |
| perf-guardrails | clean | 0 | `.agents/reports/dilution-calculator/perf-guardrails.md` |
| observability | clean | 0 (already complete) | `.agents/reports/dilution-calculator/observability.md` |
| ci-gate | clean | 0 | `.agents/reports/dilution-calculator/ci-gate.md` |

migration-safety: skipped — no models/migrations in this slice.

## Before / after
- **Unit coverage**: 95% → **100%** on `services/dilution_service.py` (85 stmts, 0
  missed). 35 → **40** unit tests.
- **E2E coverage**: 6 → **13** tests. All 4 `solve_for` directions now exercised through
  the real form at least once; all 5 distinct 400 error paths named in AC4/AC5 now have
  a UI-level assertion, not just a unit test.
- **Security findings**: 0 (semgrep 175 rules/0 hits, gitleaks 0 in-scope, uv audit 0
  CVEs, 7/7 manual checklist, fuzz-tested).
- **Perf**: both routes measured fresh — page 4.8ms/2 queries/72ms LCP, API 5.0ms/2
  queries — both well inside budget, no ceiling risk.
- **Tests added, total**: 11 (4 unit → 5 after the test-evaluator-driven split, + 7 E2E).
- **Rules added to `.semgrep/`**: 0 (no gaps found to codify).

## Findings and how they were resolved
One real finding this run, caught by test-author's own mandatory test-evaluator
grading pass (round 1) rather than slipping through:

**`test_ac4_starting_abv_of_100_is_a_valid_given_value` was gamed** — it closed unit
coverage on `dilution_service.py:63` (the `abv_pct >= 100.0` fast path in
`_mass_fraction_for_abv`) by executing the line, but its two assertions
(`starting_abv` echo, `water_to_add_ml` finiteness) didn't depend on that line's return
value. Mutation probe (`return 1.0` → `return 0.5`) stayed green — proof the test didn't
protect what its docstring claimed. **Fixed**: split into a narrowed acceptance-boundary
test (keeps only the claim it actually proves) plus a new white-box test that calls
`_mass_fraction_for_abv` directly and pins its literal return value. Round-2 re-grade:
**valid** — the new test goes red under the same mutation that slipped past round 1.
Recorded in the history store (`finding_history.py`, sig `96446c38a63f`,
verdict `fixed`) so a future review sees this was already caught and closed, not a
recurring gap.

## Process note (not a code finding — informational, for skill-smith)
The test-author chain stage, rather than waiting for the orchestrator's separately-
routed `test-evaluator` stage, spawned its own inline `Agent`-tool grading subagent to
satisfy its skill's "hand every batch to test-evaluator" rule. It executed the skill
correctly and safely (every mutation probe verified-restored, `git status --porcelain`
clean before/after each), and the two-round result is arguably more rigorous than a
single external pass would have been — but it's a deviation from
`.agents/verification-chain.md`'s intended shape (grading as an independently-launched,
Codex-routed stage, not something the author invokes on itself). No harm this run;
worth tightening the skill wording so grading consistently gets routed to its own
engine. Separately, the dedicated Codex `test-evaluator` chain stage this run's
orchestrator launched stalled mid-analysis without completing (as did the
`e2e-playwright` and initial `test-author` launches, before each resumed or was
completed by the orchestrator) — every stalled stage's actual work product was verified
independently before being reported here, but the `agent_launch.py`/herdr-tabs
mode's reliability for multi-turn stages with nested tool use is worth a look.

## What remains open
Nothing. All chain stages reached a clean/valid/patched verdict; the one finding was
fixed and re-verified within this run.

## Final verification
```
uv run pytest tests/test_dilution_calculator.py --cov=app/features/dilution_calculator --cov-report=term-missing -q
  -> 40 passed, 100% coverage

uv run pytest tests/e2e/test_dilution_calculator_flow.py -q
  -> 13 passed

uv run pytest tests/e2e/test_perf_budgets.py -q
  -> 25 passed (1 unrelated pre-existing advisory breach: /api/core/dashboard/summary)

uv run ruff check app/features/dilution_calculator/ tests/test_dilution_calculator.py tests/e2e/test_dilution_calculator_flow.py
  -> All checks passed

uv run semgrep --validate --config .semgrep/
  -> Configuration is valid, 0 errors, 29 rules

git status --short
  -> only the intended files (test-map.md, both test files) + new .agents/reports/ dirs
```

## Recommendation
Ship as-is. Hand off to **merge-request** to write the MR (blocked in this environment:
`glab` not authenticated — `can_open_mr: false` per preflight — so the branch is ready
but not yet pushed/opened). No further patch rounds needed.
