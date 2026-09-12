# TEST-EVALUATOR: auth
date: 2026-07-26
grader: codex (gpt-5.6-sol, read-only sandbox, direct `codex exec` — herdr-tabs launch was
broken this run, see note in review.md)

## Verdict
gaps-found (patched in this pass)

## Findings
- G1 (real, patched): `AuthService.authenticate()`'s F1 fix pays a dummy-bcrypt-hash cost
  for nonexistent email, wrong org_id, *and* inactive user — but only the first two had a
  test. No test proved the inactive-user path also gets timing parity. Patched: added
  `test_authenticate_invokes_bcrypt_for_inactive_user`. Already fixed: present and passing
  at `tests/test_auth_login_security.py:123` (verified 2026-08-25 by findings-sweep).
- G2 (real, patched — the more serious of the two): `test_login_generic_401_for_...locked_account`
  (in `tests/test_auth_gap_coverage.py`) proves the *response body* is identical across
  nonexistent/wrong-password/locked-account, but F1's route-level half of the fix was
  moving `auth_service.authenticate()`'s call to *before* the lockout branch, specifically
  so the lockout early-return doesn't skip bcrypt. A body-identity assertion cannot catch
  a revert of that reordering — the JSON response is identical either way; only the
  bcrypt-call count (and real timing) would differ. Patched: added
  `test_login_locked_account_still_invokes_bcrypt`, which spies on `bcrypt.checkpw` through
  a real `/auth/login` POST against a locked account and asserts exactly one call.
  **Verified this test is real**: manually reverted the route-level reordering (moved the
  `authenticate()` call back below the lockout branch) and confirmed the new test fails
  (`0 == 1`) against the reverted code, then confirmed the file was correctly restored
  and the full auth suite (33 passed / 30 skipped) plus the whole repo suite
  (506 passed / 30 skipped) are green against the actual patched code. Already fixed and
  re-confirmed present at `tests/test_auth_login_security.py:142` (re-verified 2026-08-08
  by findings-sweep).
- G3 (noted, not patched): the grader felt `test_change_password_keeps_session_permanent`
  (F2) "proves the outcome rather than that `rotate_session()` was specifically called."
  Judgment call: asserting the observable `Set-Cookie: ...Expires=...` header is the
  correct level to test at — asserting `rotate_session()` was called via a mock would be
  an implementation-detail (tautological) test that breaks on refactor and doesn't prove
  the actual security property (a persistent cookie surviving password change). No change
  made; logged as considered-and-rejected rather than silently dropped (already handled:
  not a defect, no action needed — verified 2026-09-13 by findings-sweep).

## Incidental note
Mid-review, restoring one of the F1 regression tests (`test_login_locked_account_still_invokes_bcrypt`)
required a `git checkout -- app/api/routes/auth_routes.py` to undo a deliberate revert used to
prove the test catches a regression. That command discarded *all* uncommitted changes to the
file, including F1(route-half)/F2/F3 and their nosemgrep suppressions from security-audit — a
real mistake (checkout reverts the whole file, not just the last edit). Recovered in full from
an unreachable git blob (`git fsck --unreachable --dangling`, matched by content and confirmed
against the diff's recorded target blob hash `5cb588e`) — zero data loss, but noted here since
it's a mistake worth remembering: never use `git checkout -- <file>` to undo a small experimental
edit on a file with other uncommitted work; use a targeted `git stash`/manual re-edit instead.
