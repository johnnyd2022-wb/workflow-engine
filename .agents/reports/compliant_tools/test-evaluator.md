# test-evaluator — compliant_tools

## Round 1 — VERDICT: gamed (blocking)

Codex ran static + mutation probes on `git diff main...HEAD -- 'tests/**'`. Key findings:

**Blocking (a mutation survived / a test's name is false):**
1. **AC18** — `test_ac18_migration_downgrade_logs_row_count` stubbed `drop_table` but never
   checked call order; moving `drop_table` *before* `logger.warning` kept the test green.
2. **AC13** — `test_ac13_extreme_finite_inputs_are_rejected_not_crashed` catches
   `CalculatorValidationError` *or* passes on any finite result, so for `gravity_convert`,
   `yield_loss`, `abv_from_og_fg` (whose inputs aren't actually extreme) the test passes
   while proving nothing about rejection.
3. **AC16** — the JS test never asserts the flattened `yield_loss.steps` `item_fields`
   (with `parent`), and `renderResult`'s `per_step` branch is skipped; removing per-step
   rendering would stay green.

**Coverage gaps (not blocking, worth closing):** AC13 fixtures omit the pinned
`per_step[1].remaining_l == 874.0` and `brix == plato`; `math.isclose(abs_tol=...)` keeps
a hidden `rel_tol`; AC9 "no rows written" counts only `User`; AC3 body check omits
"compliant"/"feature"; AC4 checks only one of two ADMIN routes; AC7 doesn't check both
sidebar files; AC10 doesn't check `compliant_pages` / dilution-mapping removal; AC15
doesn't guard `NZ_STANDARD_DRINK_GRAMS_ETHANOL`; AC11 fixture ≠ Appendix A byte-for-byte.
It also confirmed the AC11 catalogue check *is* genuinely independent (mutating the app
catalogue reddened it), and the AC13 FIXTURES values are literal, not solver-recomputed.

## Round 1 → Round 2 resolution (all applied)

- **AC18**: `test_ac18_migration_downgrade_logs_row_count_before_dropping` records call
  order and asserts `execute:regclass → execute:count → warning → drop_index →
  drop_table`. Added `test_ac18_migration_downgrade_noops_when_table_absent`.
- **AC13**: split into `test_ac13_overflowing_inputs_raise_validation_error_not_500`
  (`pytest.raises` — only the 5 inputs that genuinely overflow/underflow: lal,
  standard_drinks, tank_volume, yeast_pitch, keg_fill), a route-level
  `..._return_400_via_the_route`, and `test_ac13_finalise_rejects_a_non_finite_result_directly`.
  The 3 non-extreme inputs were dropped (they were mislabeled valid inputs).
- **AC16**: added `buildFormFields flattens an array field into its item_fields with a
  parent marker`, per-step render assertion inside the per-calculator test, and
  `renderResult omits meta keys ... and escapes text` (XSS).
- **AC13 fixtures**: `test_ac13_extra_pinned_fixture_fields` asserts
  `per_step[1] == {"name":"fermentation","remaining_l"≈874.0}` and `brix == plato`.
  Tolerance comparison is now `== ` when tol is 0 else pure `abs(got-exp) <= tol` (no
  `math.isclose` rel_tol).
- **AC9**: `test_ac7_endpoint_issues_no_write_and_no_extra_query` attaches a
  `before_cursor_execute` listener and fails on any INSERT/UPDATE/DELETE or any
  compliance/inventory/execution read during the solve request.
- **AC14 route-level**: `test_ac14_solve_route_issues_no_query_after_the_gate` (parametrized
  over 4 calculators) — same cursor-listener approach, past the gate.
- **AC3**: 404 body forbidden-terms extended to `subscription, not subscribed, compliant,
  feature, entitle`.
- **AC4**: now checks `POST /api/compliant/alcohol-products` 403 for a member too, plus
  `/compliant/tools` 200 (no role gate).
- **AC7**: `test_ac7_both_sidebars_drop_dilution_and_gate_compliance_on_subscription`
  asserts both `sidebar-v2.html` files: no `/dilution-calculator`, gate on
  `compliant_subscribed`, not `compliant_enabled` alone.
- **AC10**: `_build_nested_compliant_app` gained a `compliant_pages` sub-blueprint + a
  `/compliant` assertion; `test_dilution_calculator_feature_mappings_are_gone` asserts no
  `dilution_calculator` keys remain and `compliant.compliant_pages` maps.
- **AC15**: bans `= 10.0` literals in calculator modules; requires the import when the
  constant name appears.
- **AC11**: renamed to `..._are_json_equal_and_match_appendix_a` — asserts the served
  catalogue, the fixture, and the Appendix A JSON block are all `json.loads`-equal (the
  content is the invariant, not byte formatting). Spec AC11 wording updated to match.

Re-graded in round 2 below.

## Round 2 — VERDICT: gamed

Round-1 blockers all now go red under mutation. 3 NEW permissiveness gaps introduced by
the round-1 fixes:
1. JS `renderResult` meta-key test only checked `solved_field` — shrinking `META_KEYS`
   left disclaimer/sources/per_step rendering as value rows undetected.
2. `test_ac14_solve_route_..._no_query` filtered writes + `compliance_` reads only — a
   `SELECT * FROM inventory_items` slipped through.
3. Same in the dilution AC7 equivalent.

### Round 2 → 3 fixes
- JS test: assert NO meta key renders as a `.ct-result-label` row AND each renders in its
  own block; shrinking `META_KEYS` now fails.
- Both cursor tests: allowlist to `{users, organisations, feature_subscriptions}`; any
  other `from`/`join` target or any write fails.

## Round 3 — VERDICT: gamed

Round-1/2 all red under mutation. 1 NEW: the SQL-text regex was bypassable by quoted
identifiers (`SELECT * FROM "inventory_items"`), CTE reads
(`WITH x AS (SELECT * FROM crm_tasks) SELECT * FROM x`), and CTE-prefixed writes
(`WITH x AS (SELECT 1) DELETE FROM crm_tasks`).

### Round 3 → 4 fix
Extracted `tests/_sql_probe.py::sql_beyond_gate_infra`: dequote first, match write
keywords anywhere (not just prefix), check every `from`/`join` target against the
allowlist while treating CTE aliases as read-through. Self-tested against every named
bypass case. Both cursor tests use it.

## Round 4 (final) — VERDICT: valid

Codex re-ran every historical mutation (AC18 ordering, AC13 non-finite guard, AC16
per-step rendering, `META_KEYS` shrink) + the 3 round-3 SQL bypasses — all go RED. 23
Python checks + the full Node renderer suite pass. "Remaining regex evasions require
deliberately contrived raw SQL and are not realistic for a pure-math solver path."
Worktree unchanged (Codex's temp mutations fully restored). **The test batch is a valid
certification of the spec.**

Round tally: gamed → gamed → gamed → valid.
