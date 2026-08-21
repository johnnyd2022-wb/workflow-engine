# E2E: dilution_calculator
date: 2026-08-21
role: chain stage (gap-fill mode; invoked from review-feature)
verdict: patched

## Note on this report's authorship
The e2e-playwright stage (Herdr pane w19:p3, session `c8c7b9d2-49be-414c-bec0-a258c63a60fb`)
wrote the tests below and verified them (3 consecutive green runs, incl. a flake check)
but the `claude -p` process went idle before writing its own report file or emitting the
mandatory `VERDICT:` line. Per `.agents/verification-chain.md` §5 (the orchestrator is
responsible for capturing a stage's outcome when the stage itself can't write it), this
report is written by the review-feature orchestrator from the stage's transcript
(`~/.claude/projects/.../c8c7b9d2-....jsonl`) and independently re-verified — not
transcribed blind.

## Starting coverage
`tests/e2e/test_dilution_calculator_flow.py` (pre-review, 6 tests): page/API auth
requirement, authenticated render, one worked-example solve via UI (AC2's exact
identity + contraction `water_to_add_ml > naive`), UI-vs-API result match (also checks
AC8's disclaimer field), one invalid-direction error path (AC5, `final_volume_ml`
branch only).

## Gaps identified against .agents/specs/dilution_calculator.md (AC1-AC9)
- AC5's other branch (`solve_for` an ABV field → `final_volume_ml <=
  starting_volume_ml` check) was unit-tested but never driven through the real form.
- AC5's explicit divisor guard (`final_abv == 0` when solving `final_volume_ml`) was
  unit-tested but not exercised via the UI as a real round trip (server error path,
  not a 500/blank page).
- AC4's range/positivity checks (ABV out of `[0,100]`, non-positive volume) were only
  unit-tested at the service layer — no UI test confirmed the server-side error
  actually reaches and renders in the DOM (vs. being silently swallowed).
- AC4's client-side required-field check had no UI test distinguishing it from the
  server-side message (different wording — display label vs. raw field name).
- AC3's round-trip property was unit-tested for two of the four solve directions
  (`final_volume_ml`→`final_abv`, `starting_volume_ml`→`starting_abv`) but never
  exercised end-to-end through the browser, and the other two `solve_for` targets
  (`final_abv`, `starting_abv` as the *first* solve) had no UI click-path coverage at
  all before this batch.

## Tests added (7)
1. `test_ac5_solving_abv_field_rejects_shrinking_volume_in_ui`
2. `test_ac5_divisor_guard_final_abv_zero_shows_error_in_ui`
3. `test_ac4_abv_out_of_range_shows_error_in_ui`
4. `test_ac4_non_positive_volume_shows_error_in_ui`
5. `test_ac4_blank_required_field_shows_error_in_ui_without_calling_api`
6. `test_ac3_round_trip_final_volume_then_final_abv_via_ui`
7. `test_ac3_round_trip_starting_volume_then_starting_abv_via_ui`

Full diff: `tests/e2e/test_dilution_calculator_flow.py` (+213 lines). All 4 `solve_for`
directions are now clicked through the real form at least once; all 5 distinct 400
error paths named in AC4/AC5 have a UI-level assertion, not just a unit test.

## Scope note: cross-tenant probe
Per the spec, this slice is `tenant_scoped: no` — no `org_id`, no models, no
persistence (verified independently by security-audit, same review run). The
review-feature skill's mandatory cross-tenant probe does not apply: there is no
tenant-scoped resource for a second org to attempt to read or write. Not added, by
design, not by omission.

## Not covered (judged out of scope for E2E)
- AC7 (statelessness / writes no rows) and AC9 (no server-side rounding) are
  data-shape assertions already covered at the unit level
  (`test_ac7_endpoint_writes_no_rows`, `test_ac9_solved_value_is_not_rounded` in
  `tests/test_dilution_calculator.py`) — not meaningfully re-testable through a
  browser click-path.

## Live-server note
Preflight reported `live_server_tests: skip` (no `uv run workflow start` listening).
That decision is about the separately-started dev server; this Playwright suite boots
its own self-contained app instance via its `conftest.py` fixtures and does not depend
on the dev server being up — it ran directly, not skipped.

## Verification (run independently by the orchestrator after the stage went idle)
```
uv run pytest tests/e2e/test_dilution_calculator_flow.py -q
13 passed, 1 warning in 20.59s
```
Matches the stage's own reported 3x-green flake check (13 passed each run).

VERDICT: patched
