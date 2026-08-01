# E2E: reconciliation
date: 2026-07-30
role: e2e-playwright stage (review-feature chain), sharing this worktree read/write with a
      read-only security-audit stage this turn — writes confined to `tests/e2e/reconciliation/`
      (new files only); nothing under `app/`, `scripts/`, or any other test directory touched.
spec: .agents/specs/reconciliation.md
suite: tests/e2e/reconciliation/ (did not exist before this run — confirmed empty/absent first)

## Summary

12 new Playwright E2E tests across `test_reconciliation.py`, all passing, 3/3 clean runs
(no flakes). `conftest.py` adds process/step/untracked-item creation helpers (all via real
HTTP routes, not DB shortcuts) plus a `two_org_sessions` fixture built on the shared
`two_org_two_user` world. AC8 (tenant isolation) — the spec's explicitly-called-out gap —
is now covered for all three cross-org input vectors (`untracked_item_id` on both write
routes, `step_id`, `process_id`), using a differential comparison (real-object-in-other-org
vs. random-nonexistent-id) rather than a hardcoded expected status, since that comparison
*is* what AC8 requires.

One of those four AC8 tests surfaces a real finding rather than a clean pass — see below.

## AC → test → result

| AC | Test | Result |
|----|------|--------|
| AC1 | `test_ac1_matching_untracked_matches_name_case_insensitively_and_unit_exactly` | pass |
| AC1 | `test_ac1_matching_untracked_missing_params_returns_empty_list_not_400` | pass |
| AC1 | `test_ac1_matching_untracked_excludes_fully_reconciled_item` | pass |
| AC2 | `test_ac2_via_addition_happy_path_reconciles_partial_balance` | pass |
| AC2 | `test_ac2_via_addition_unit_mismatch_rejected` | pass |
| AC2 | `test_ac2_via_addition_zero_balance_untracked_item_rejected` | pass |
| AC3 | `test_ac3_via_execution_happy_path_creates_execution_and_reduces_untracked` | pass |
| AC3 | `test_ac3_via_execution_idempotency_guard_rejects_second_identical_reconcile` | pass |
| AC8 | `test_ac8_via_addition_cross_org_untracked_item_id_indistinguishable_from_nonexistent` | pass |
| AC8 | `test_ac8_via_execution_cross_org_untracked_item_id_indistinguishable_from_nonexistent` | pass |
| AC8 | `test_ac8_via_execution_cross_org_step_id_indistinguishable_from_nonexistent` | pass |
| AC8 | `test_ac8_via_execution_cross_org_process_id_indistinguishable_from_nonexistent` | pass (see finding below) |

Flake check: ran 3 times in a row (`pytest tests/e2e/reconciliation -q`), 12/12 passed each
time, no intermittent failures.

## Finding: AC8 process_id path is a 500, not the graceful 400 the other two vectors get

`test_ac8_via_execution_cross_org_process_id_indistinguishable_from_nonexistent` passes —
a cross-org `process_id` and a fully nonexistent `process_id` produce byte-identical
responses (same status, same body), so no cross-tenant existence leak was found on that
axis. But both cases are an **uncaught 500 Internal Server Error**, not the clean
`{"error": "..."}` 400 the `untracked_item_id` and `step_id` checks return. Confirmed
directly (both via a raw service call and a full HTTP round trip before writing the final
test):

```
ValueError: Process <id> not found or does not belong to org <id>
```

raised from `ExecutionRepository.create_execution` (`app/core/db/repositories/execution_repo.py:76`)
and left uncaught all the way up through `reconcile_via_execution`'s
`except Exception: session.rollback(); raise` (`app/core/backend/reconciliation_service.py:679-681`)
and the route's bare `try/finally: session.close()` (`app/core/backend/reconciliation_routes.py:148-168`)
— there is no app-wide error handler for `ValueError` (`app/api/app_factory.py` registers
only `@app.errorhandler(401)`), so it's a genuinely unhandled exception at the WSGI layer.

This matches **security-audit's F1** in `.agents/reports/reconciliation/security-audit.md`
(same worktree, same turn, read independently) almost exactly, down to the same repro
exception text — their framing (status-code inconsistency across the three cross-org
vectors is itself a distinguishing signal, plus a Werkzeug-debugger leak risk since
`local.ini`/`test.ini` both set `debug = true`) is complementary to this suite's framing
(the two same-shape cases are identical to each other, so no leak on *that* axis, but the
500 is still real). Not re-filing as a duplicate finding — routing follows security-audit's
F1 (→ fix-bug, red-then-green: "org A process_id against org B fails as 400, not 500").
The passing test here is intentionally the guardrail that repro must turn green against
once fixed, so it stays in the suite rather than being deleted or downgraded.

**Resolved 2026-07-31 (fix-bug), then corrected on rebase.** I initially patched
`reconcile_via_execution` myself and wrote a red-then-green repro at
`tests/test_reconciliation_routes.py::test_reconcile_via_execution_cross_org_process_id_returns_clean_400_not_500`
(confirmed 500 pre-fix, 400 post-fix). Rebasing this branch onto `origin/main` afterward
surfaced a merge conflict on the exact same lines: **`origin/main` already carried an
equivalent fix**, commit `b2b5144` ("fix(inventory): 500 on cross-org process_id in
reconcile via-execution", merged 2026-07-30 — before this fix-bug pass even started, on a
branch that had been cut before that commit landed and never picked it up). Same root
cause, functionally identical patch, its own regression test in `tests/test_inventory.py`,
differing only in the returned message (`"Process not found or access denied"` vs. this
pass's `"Process not found"`). Kept main's version, dropped my redundant patch and test.
This suite's own `test_ac8_via_execution_cross_org_process_id_indistinguishable_from_nonexistent`
needed no change — it asserts status-equality rather than a hardcoded value, so it's still
green post-rebase (12/12), now genuinely proving both cases are identical 400s instead of
identical 500s, via main's fix. F2 (dead `reconcile_output_to_untracked`) was **not** already
done upstream and was removed in this pass. Logged in `.agents/history/findings.jsonl` (sig
`167ec038552c`, `072f2296ebd8`, verdict `fixed`); full duplicate-work writeup at
`.agents/reports/fix-bug/2026-07-31-reconciliation-cross-org-process-id.md`. Full suite pre-rebase: 590 passed, 30 skipped.

## Not covered (by design, not oversight)

- **AC4** (Path C, `reconcile_output_to_untracked_reduce_only`) — no HTTP route of its own;
  it's called from inside execution's `complete_step` (`backend.py:2499-2538`), which is the
  execution slice's surface, not this one's. An E2E test exercising it would really be an
  execution-slice test asserting reconciliation math as a side effect — out of this suite's
  scope per the spec's own "Out of scope" section. Leaving to that slice's E2E suite (or an
  integration test) if/when it gets one.
- **AC5** (row-level locking under concurrent requests) and **AC6** (invariant assertions
  guarding against a negative balance) — these are concurrency/defensive-code properties,
  not independently E2E-observable behavior distinct from what AC2/AC3's happy-path tests
  already drive through the real lock-acquiring code path. A real concurrency test needs
  two simultaneous requests racing the same row, which is an integration-test concern
  (threading/async against the DB directly), not something a serial Playwright flow can
  exercise meaningfully.
- **AC7** (audit trail entries in `extra_data.reconciliation_history`) — every AC2/AC3 test
  here exercises the code path that appends to it, but asserting the exact history-entry
  shape (timestamp, user id/email, method, amounts) is an implementation-detail assertion
  the skill's own rules discourage ("assert on outcomes the user cares about... not
  implementation details"); left to unit/integration coverage of `reconciliation_service.py`
  if that's wanted, rather than E2E asserting on JSON-column internals.

Not claiming any of AC4/5/6/7 as "covered" by the AC2/AC3 tests above, per the skill's rule
against marking an AC covered by a test that doesn't genuinely exercise it end to end.

## Tooling note (not a code finding, flagging for whoever owns it)

`scripts/e2e_coverage.py` globs `tests/e2e/*.py` (non-recursive — `E2E_DIR.glob("test_*.py")`,
`scripts/e2e_coverage.py:120,223`), so it does not see test files inside `tests/e2e/<slug>/`
subdirectories. This suite lives at `tests/e2e/reconciliation/test_reconciliation.py` (as
directed by this task's scope), so the coverage script currently still reports
`matching-untracked` / `via-addition` / `via-execution` as gaps despite being covered by the
tests above. Did not fix — `scripts/e2e_coverage.py` is outside this task's declared write
scope (`tests/e2e/reconciliation/` new files only). Worth a follow-up to widen the glob (or
add `tests/e2e/**/test_*.py`) so future per-feature subdirectories don't silently
under-report.

## Setup notes for whoever runs this next

- `two_org_two_user` (`tests/conftest.py:92`) was written for API-only tests with no real
  login and its teardown does a plain `DELETE FROM users`/`DELETE FROM organisations`. A
  real browser login (`login_through_ui`) writes an `audit_logs` row referencing the user,
  which turns that plain delete into a foreign-key violation. `two_org_sessions`
  (`tests/e2e/reconciliation/conftest.py`) works around this locally by running `purge_org`
  (the same schema-walking, FK-safe cleanup `fresh_user`/`e2e_user` already use) before
  `two_org_two_user`'s own teardown runs, so that teardown's delete matches zero rows
  instead of failing. Did not modify `tests/conftest.py` itself (outside this task's write
  scope) — if another E2E suite adopts `two_org_two_user` with real logins, it will hit the
  same issue and may want the same workaround, or `two_org_two_user` itself widened to use
  `purge_org`.

## Handoff

Suite passes and is stable (3/3). Hand to **ci-gate** to make
`pytest tests/e2e/reconciliation` a required check. The AC8 `process_id` finding routes to
**fix-bug** per security-audit's F1 (already filed); once fixed, the passing
`test_ac8_via_execution_cross_org_process_id_indistinguishable_from_nonexistent` test in
this suite should still pass (both cases should then be identical 400s instead of identical
500s) — no test change needed, it already asserts the status-equality invariant rather than
a hardcoded value.

VERDICT: patched — F1 (AC8 process_id 500) already fixed upstream (main's b2b5144, discovered on rebase), F2 (dead code) fixed here 2026-07-31, see Resolution note above; suite green 12/12
