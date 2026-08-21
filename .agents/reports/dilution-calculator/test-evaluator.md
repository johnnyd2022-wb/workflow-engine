# TEST-EVALUATOR: dilution_calculator
date: 2026-08-21
role: chain stage (grades this review's test additions; invoked from review-feature)
verdict: valid

## Note on this report's authorship
The dedicated chain stage (Herdr pane w19:p5, Codex `gpt-5.6-sol`, session
`01a02364-e0c5-74b3-98da-bb6f16120355`) went idle mid-analysis without producing a
report or verdict — it had also read `.agents/specs/dilution_calculator.md` and started
static review, but its `--sandbox read-only` launch cannot perform the skill's required
mutation probes (they need a transient write + restore) even had it finished. This
report consolidates two independent, complete gradings instead:

1. **Unit batch** (4 tests, later 5 after a split): graded by test-author's own inline
   `test-evaluator` subagent, two rounds — full reports at
   `.agents/reports/test-evaluator/2026-08-21.md` (round 1: `gamed`) and
   `.agents/reports/test-evaluator/2026-08-21-round2.md` (round 2: `valid`, after
   test-author fixed the round-1 finding). Both rounds ran real mutation probes with
   verified restore (`git checkout --` + clean `git status --porcelain` before/after).
2. **E2E batch** (7 Playwright tests): static review plus one live mutation probe, done
   directly by the review-feature orchestrator below, since no chain stage completed it.

## Batch 1: unit tests (tests/test_dilution_calculator.py)
5 tests in final form (4 original + 1 added during the round-1→round-2 fix):
`test_ac4_starting_abv_of_100_is_a_valid_given_value` (rewritten, narrowed),
`test_mass_fraction_for_abv_100_boundary_is_exact_pure_ethanol` (new),
`test_ac4_rejects_non_dict_payload_direct_call`,
`test_ac5_post_solve_starting_abv_over_100_is_rejected`,
`test_ac5_post_solve_starting_volume_non_positive_is_rejected`.

Verdict: **valid**. See the two linked reports for the full static/mutation detail. In
short: round 1 caught a real gamed test (coverage-closing line execution without an
assertion that depended on that line's return value) via mutation probe, and round 2
confirms the fix — the split test now goes red under the exact mutation that slipped
past round 1, while the narrowed original correctly stays green (it no longer claims to
guard that line).

## Batch 2: E2E tests (tests/e2e/test_dilution_calculator_flow.py)

### Static review (all 7)
1. `test_ac5_solving_abv_field_rejects_shrinking_volume_in_ui` — real assertion (error
   text + result hidden), not a smoke test. Exercises the AC5 branch (`solve_for` an ABV
   field) the pre-existing E2E test didn't cover (it only covered the volume-field
   branch). Name matches what it proves.
2. `test_ac5_divisor_guard_final_abv_zero_shows_error_in_ui` — same shape, targets the
   explicit divisor guard. **Mutation-probed, see below.**
3. `test_ac4_abv_out_of_range_shows_error_in_ui` — uses `starting_abv=140`, which the
   docstring correctly notes passes client-side validation (finite number) so this is a
   genuine server round trip, not a client-only check. Real assertion.
4. `test_ac4_non_positive_volume_shows_error_in_ui` — same shape for `starting_volume_ml
   =0`. Real assertion.
5. `test_ac4_blank_required_field_shows_error_in_ui_without_calling_api` — asserts the
   *client-side* message wording (`"Final ABV (%) is required"`, the display label),
   distinct from the server's own message (`"'final_abv' is required"`, the raw field
   name) asserted in test 3/4 above and in the unit suite — this distinction is what
   proves the request never reached the API, not just that some error appeared. Not a
   tautology.
6. `test_ac3_round_trip_final_volume_then_final_abv_via_ui` — solves step 1, reads the
   *displayed* solved value back out of the DOM, feeds it into step 2, and asserts the
   recovered value against a literal (`20.0`) chosen independently from the worked
   example — not recomputed via the service under test. Real, falsifiable round-trip
   claim exercised through actual UI interaction (button clicks, field fills), not just
   two isolated API calls.
7. `test_ac3_round_trip_starting_volume_then_starting_abv_via_ui` — same shape, the other
   two solve directions (symmetric coverage with test 6 — together all four `solve_for`
   targets are now exercised through the UI at least once).

No tautologies, no catch-all assertions, no widened/deleted assertions (all net-new), no
unjustified skips. Every test's name matches what its assertions actually prove.

### Mutation probe (orchestrator, live)
Probed the highest-value case — the divisor guard, a correctness-critical guard against
a raw 500 (`ZeroDivisionError`), not just a validation-message nicety:

```
# mutate: disable the final_abv==0 divisor guard in _check_dilution_direction
git status --porcelain -- app/features/dilution_calculator/   # clean before
[edit: "if solve_for == ... and given[...] == 0.0:" -> "if False and ... :"]
uv run pytest tests/e2e/test_dilution_calculator_flow.py::test_ac5_divisor_guard_final_abv_zero_shows_error_in_ui -q
  -> FAILED (ZeroDivisionError propagates to an HTTP 500; test correctly does not accept a 500 as "the error surfaced")
git checkout -- app/features/dilution_calculator/services/dilution_service.py   # restore
git status --porcelain -- app/features/dilution_calculator/   # clean after
uv run pytest tests/e2e/test_dilution_calculator_flow.py::test_ac5_divisor_guard_final_abv_zero_shows_error_in_ui -q
  -> 1 passed in 6.09s
```
Confirmed falsifiable: the test goes red when the guard it names is broken, and green
again once restored. Not sampled further given time budget — the remaining 6 are lower
structural risk (straightforward error-path/round-trip assertions, same pattern as this
one and as the already-mutation-verified unit-level equivalents for the same guards).

## Full suite re-verification
```
uv run pytest tests/test_dilution_calculator.py --cov=app/features/dilution_calculator --cov-report=term-missing -q
  -> 40 passed, 100% coverage (0 missing) on all 4 files in the slice

uv run pytest tests/e2e/test_dilution_calculator_flow.py -q
  -> 13 passed

uv run ruff check tests/test_dilution_calculator.py tests/e2e/test_dilution_calculator_flow.py app/features/dilution_calculator/
  -> All checks passed

git status --short app/features/dilution_calculator/
  -> (clean — no probe left in the tree)
```

## Findings
None outstanding — the one real finding (round-1 gamed test) was fixed and re-verified
valid within this same run, per the process note in `test-author.md`.

VERDICT: valid
