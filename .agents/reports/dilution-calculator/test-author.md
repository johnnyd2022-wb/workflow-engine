# TEST-AUTHOR: dilution_calculator
date: 2026-08-21
role: chain stage (unit coverage gap-fill; invoked from review-feature)
verdict: patched

## Note on this report's authorship
The test-author stage (Herdr pane w19:p4, session `5ecbeea2-ce6b-41b9-9fa1-eccfe2856d77`)
did the actual work end to end, including its own mandatory test-evaluator grading
round-trip (see below) — it did not stall. Herdr's idle-detection fired several times
mid-run (between nested Agent-tool turns), which made the pane look finished when it was
still working; this report was written by the review-feature orchestrator once the
transcript and git tree had genuinely settled, and every claim below is independently
re-verified (coverage re-run, ruff, full slug suite), not transcribed blind.

## Starting point
`pytest tests/test_dilution_calculator.py --cov=app/features/dilution_calculator
--cov-report=term-missing` showed 95% on `services/dilution_service.py` (85 stmts, 4
missed: lines 63, 77, 141, 143), 100% on the three route/blueprint files. 35 tests, all
passing — no pre-existing failures.

## Gaps closed (4 uncovered lines, all real branches, none dead code)
- **Line 77** (`_validate_and_extract`, non-dict payload guard): unreachable via the
  HTTP route (`api_routes.py` already 400s a non-dict body before calling
  `solve_dilution`), but a real contract check for any direct/non-HTTP caller. Closed by
  `test_ac4_rejects_non_dict_payload_direct_call`, calling `solve_dilution([1, 2, 3])`
  directly.
- **Line 141** (post-solve "outside 0-100" guard, ABV solve_for branch): AC5's pre-solve
  pair check (`final_volume_ml > starting_volume_ml`) doesn't bound the *magnitude* of
  the solved `starting_abv` — a large volume ratio passes the pre-check but still
  overshoots 100. Closed by `test_ac5_post_solve_starting_abv_over_100_is_rejected`
  (`starting_volume_ml=100, final_abv=90, final_volume_ml=2000` → solves to 1800,
  correctly rejected rather than returned).
- **Line 143** (post-solve "non-positive volume" guard, volume solve_for branch):
  `final_abv=0.0` is a legal AC4 boundary value and passes this branch's pre-check
  (`0 < starting_abv`), but the closed-form solve for `starting_volume_ml` then divides
  through to exactly 0. Closed by
  `test_ac5_post_solve_starting_volume_non_positive_is_rejected`.
- **Line 63** (`_mass_fraction_for_abv`, `abv_pct >= 100.0` fast path): closed in two
  passes — see "Self-correction" below. The first attempt technically executed the line
  but didn't assert anything that depended on its return value; the shipped version
  fixes that.

## Self-correction: a gamed test caught and fixed inside this stage
test-author's skill mandates handing every batch to test-evaluator before finishing.
Rather than wait for the orchestrator's separately-launched chain stage, it spawned its
own grading subagent inline (an `Agent` tool call running the test-evaluator skill) —
not the intended chain shape (grading is meant to be a separate, independently-launched
stage), but it executed the skill correctly and safely: every mutation probe was a
surgical in-place edit, verified restored via `git checkout --` and a clean
`git status --porcelain` before and after each one.

**Round 1 verdict: `gamed`.** `test_ac4_starting_abv_of_100_is_a_valid_given_value`
closed coverage on line 63 by executing it, but its assertions
(`result["starting_abv"] == 100.0`, `math.isfinite(result["water_to_add_ml"])`) don't
depend on that line's return value. Probe: mutated `return 1.0` → `return 0.5` in
`_mass_fraction_for_abv`'s `>= 100.0` branch — test stayed green. Full finding in
`.agents/reports/test-evaluator/2026-08-21.md`.

**Fix**: test-author split the test — narrowed the original to only claim what it
proves (the AC4 acceptance-boundary echo), and added a new
`test_mass_fraction_for_abv_100_boundary_is_exact_pure_ethanol` that calls
`_mass_fraction_for_abv` directly and pins its literal return value (`1.0`, including
the `150.0` over-100 case).

**Round 2 verdict: `valid`.** Same mutation (`return 1.0` → `return 0.5`) now goes red
on the new test (`assert 0.5 == 1.0`) while the narrowed original correctly stays green
(it was never supposed to depend on that line). Full report in
`.agents/reports/test-evaluator/2026-08-21-round2.md`. Tree confirmed clean before and
after.

## Verification (run independently by the orchestrator once the tree settled)
```
uv run pytest tests/test_dilution_calculator.py --cov=app/features/dilution_calculator --cov-report=term-missing -q
services/dilution_service.py: 85 stmts, 0 missed, 100%
TOTAL: 119 stmts, 0 missed, 100%
40 passed, 9 warnings in 4.03s

uv run pytest tests/e2e/test_dilution_calculator_flow.py -q
13 passed, 1 warning in 23.09s

uv run ruff check tests/test_dilution_calculator.py tests/e2e/test_dilution_calculator_flow.py app/features/dilution_calculator/
All checks passed!

git status --short app/features/dilution_calculator/
(clean — source untouched by every probe)
```
A full whole-repo suite run (`uv run pytest tests/ -q`) was also started by the stage as
a final sanity check; it left behind untracked `app/core/process_docs_storage/<uuid>/`
directories (an unrelated pre-existing test-hygiene gap in a different feature's test
fixtures, not gitignored) which the orchestrator removed as run artifacts — out of scope
for this review to fix at the source.

## Process note (not a code finding)
test-author spawning its own `Agent`-tool grading subagent, rather than letting the
orchestrator launch the dedicated `test-evaluator` chain stage, is a deviation from
`.agents/verification-chain.md`'s intended shape (grader as an independently-launched,
engine-routed stage). It caused no harm here — the subagent behaved exactly per the
test-evaluator skill, restored every mutation, and the two-round result is more rigorous
than a single pass would have been — but it's worth `skill-smith` tightening
test-author's skill wording so this stays a chain-launched stage rather than an
author-invoked one, so grading consistently gets its own routed engine (Codex) rather
than whatever model the author is running on.

## Test map
Updated `.agents/test-map.md` row 24 (Dilution calculator) — status now `covered (100%)`,
notes the specific gaps closed and the full E2E addition from the e2e-playwright stage.

VERDICT: patched
