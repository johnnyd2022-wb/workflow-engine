# UNIT COVERAGE: demo-data
date: 2026-08-23
mode: chain-stage (coverage gap → tests written directly by this review)
verdict: patched

## Before
`pytest --cov=app/features/demo_data --cov-report=term-missing` (run against just the
three suites that indirectly exercise this slice): `api_routes.py` 29% (route handler
body almost entirely untested at the unit/integration level — only reachable, before
this review, via three other suites' indirect fixture usage of the service functions,
never via the Flask route itself), `resetdb.py` 96%. No dedicated `tests/test_demo_data.py`
existed (the exact gap the feature index flagged).

## After
New file `tests/test_demo_data.py`, 7 tests, all green, 3/3 flake-checked:

| Test | Covers |
|---|---|
| `test_env_gate_blocks_outside_test_and_local` | AC2 — env gate at the route level (untestable via e2e, see e2e-playwright.md) |
| `test_unauthenticated_reset_is_rejected` | AC1 — 401 without a login |
| `test_demo_org_member_can_reset` (resets twice) | AC3 + the delete-existing-data branches inside `reset_demo_db` (only exercised on a second reset) |
| `test_outsider_org_member_gets_403_forbidden` | F1's fix — the explicit caller-identity check added this review |
| `test_exception_during_reset_returns_generic_message_not_raw_exception` | F2's fix — generic message, not `str(e)`, in the 500 body |
| `test_reset_demo_db_returns_user_not_found_when_demo_user_missing` | AC4, at the service-function level |
| `test_clear_demo_db_is_noop_when_demo_user_missing` | `clear_demo_db`'s early-return branch |

`app/features/demo_data/routes/api_routes.py`: 29% → 91%.
`app/features/demo_data/services/resetdb.py`: 96% → 97%.

## Design notes
- The real `demo@whistlebird.co.nz` user's password is unknown (it may be a genuinely
  pre-existing seeded account other tooling depends on), so no test logs in as it
  directly. Tests needing "a legitimate demo-org member" use a throwaway `demo_org_member`
  fixture — a second user created in the same org, with a password this test controls —
  same pattern used in `tests/e2e/demo-data/conftest.py`.
- AC4 (demo user missing) is tested at the service-function level with
  `monkeypatch.setattr(UserRepository, "get_user_by_email", ...)` rather than by
  deleting the real seeded row, which would break `test_corechecks`, `test_executions`,
  and `test_dag_traversal` (all import `reset_demo_db`/`clear_demo_db` directly and
  assume that row exists).

## Remaining gaps, left uncovered on purpose
- `api_routes.py:63` (`if not result.get("success"): return ... 400`) and `:68-69`
  (the inner `except Exception: pass` around `session.rollback()`): the first is now
  effectively dead code on the normal path — this review's F1 patch already validates
  the demo user exists (via the explicit `unscoped()` check) before calling
  `reset_demo_db`, so its own `USER_NOT_FOUND` return can now only happen in a TOCTOU
  race (demo user deleted between the two checks). Kept as defensive coding, not
  removed, but not worth a contrived race-condition test to cover. The rollback
  `except: pass` guards `session.rollback()` itself failing, an even narrower case.
- `resetdb.py:359` (`if not inv_id: continue`) and `:371-372`
  (`except Exception: pass` in the quantity-decrement loop): defensive branches inside a
  fixed, hard-coded demo-fixture generator — `actual_inputs` is a small literal list
  this same file defines, not production request data, so these paths are not reachable
  by construction today. Forcing them would mean mutating the seed data specifically to
  hit a branch that exists for future-proofing, not current behavior — not a meaningful
  test.
