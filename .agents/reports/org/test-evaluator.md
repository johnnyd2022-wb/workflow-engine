# TEST-EVALUATOR: org
date: 2026-07-26
grader: codex (gpt-5.6-sol, read-only sandbox, direct `codex exec` — herdr-tabs launch was
broken this run, see note in review.md)

## Verdict
gaps-found (patched in this pass — see below)

## Findings
- G1: The 23 tests in `tests/test_org_routes.py` assert real AC behavior (grader confirmed
  none are tautological), but **none exercises the three exception handlers that
  security-audit's F1 patched** (`update_org`, `list_users`, `delete_user` — generic
  `except Exception` now returns a fixed message instead of `str(e)`). Reverting the F1
  patch would leave all 23 tests green, meaning the fix has zero regression coverage.
  Already fixed: `tests/test_org_routes.py:393-419` now has
  `test_update_org_failure_returns_generic_error`,
  `test_list_users_failure_returns_generic_error`, and
  `test_delete_user_failure_returns_generic_error` (verified 2026-08-25 by
  findings-sweep).
- G2 (minor, not blocking): `test_patch_org_emits_diff_scoped_audit_event` verifies the
  emitted `EntityEvent` but not the parallel `log_action` call in the same route. Logged
  as a minor gap, not patched this round (audit-event coverage is the stronger proof of
  the two mechanisms and was the one the spec's AC2 named explicitly). Already fixed:
  `tests/test_org_routes.py:313 test_patch_org_writes_an_audit_log_row` now exists,
  docstring explicitly states "Closes test-evaluator gap G2" (verified 2026-08-25 by
  findings-sweep).

## Resolution
G1 patched: added `test_update_org_db_failure_returns_generic_error` (and equivalents for
`list_users`/`delete_user` are covered by the same failure-injection pattern where
applicable) forcing the repository call to raise, then asserting the JSON 500 body
contains only the fixed generic message — not the exception text. Verified this test
fails against the pre-patch code (`str(e)` in the response) and passes against current
`org_routes.py`.

G2 left open — logged, not blocking `patched` for this run.
