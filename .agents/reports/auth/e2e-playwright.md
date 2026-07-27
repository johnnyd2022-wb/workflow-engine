# e2e-playwright gap-fill report: auth

**Verdict: patched**

Scope: `app/api/routes/auth_routes.py` (`auth_bp`, `/auth/*`) against the 21 ACs in
`.agents/specs/auth.md`. Run in gap-fill mode per the task: existing suite is real and
substantial, job was to close coverage gaps, not rebuild from scratch.

## Note on test style

The task asked specifically for Flask-test-client tests, not browser/Playwright tests, for
this gap-fill. Every auth route in scope is plain Flask view logic with no outbound network
call (TOTP verification is local `pyotp` math against a stored secret; no external IdP), so
the gaps were fully testable in-process with the same `flask_app.test_client()` pattern
`tests/test_auth_password_session.py` already uses. No live dev server was needed for any
new test, and none was started for this work — see "Live-server status" below.

## What existed before this pass

- `tests/test_auth_password_session.py` (10 tests, Flask test client, no live server
  needed): password-policy-check, change-password (success/wrong-current/mismatch/
  same-as-current), session-timeout GET/PUT (bounds, missing value).
- `tests/test_2fa_totp_optimized.py` (16 tests) and `tests/test_login_2fa_flow.py` (16
  tests): both entirely `pytest.mark.live_server` — they drive a real server at
  `https://localhost:8005` with `requests.Session()`, not the Flask test client. They cover
  a lot of ground (enroll/enable/disable happy+unhappy paths, TOTP and backup-code login
  completion, backup-code one-time-use, format validation) but only execute when
  `uv run workflow start` is up. `tests/conftest.py`'s `pytest_collection_modifyitems`
  confirms this is a real, honest skip gate (probes the port once per session, skips with a
  stated reason if nothing is listening) — not a mislabeled failure.

Baseline run (`unset ENVIRONMENT && uv run pytest tests/test_auth_password_session.py
tests/test_2fa_totp_optimized.py tests/test_login_2fa_flow.py -v`): **10 passed, 30
skipped**, matching the task's stated baseline exactly.

## Gaps found and closed

None of the 7 ACs called out in the task had server-exercised coverage that runs without a
live server:

| AC | Gap | Status |
|----|-----|--------|
| AC3 | No test that duplicate org name and duplicate email produce the *same* signup error | Closed |
| AC4 | No test that nonexistent user / wrong password / locked account produce the *same* login error | Closed |
| AC8 | Trusted-device happy path (matching cookie+fingerprint) had no in-process test at all; the fingerprint-mismatch and unknown-token fallthrough paths had zero coverage anywhere in the suite (live-server files never test a mismatch) | Closed |
| AC9 | Nothing asserted logout leaves `trusted_device_token` untouched | Closed |
| AC13 | Nothing asserted a backup code cannot mint a trusted-device cookie even with `remember_device=true` | Closed |
| AC17 | Nothing exercised `/auth/2fa/cancel`'s `had_pending` in either state, or that it clears a full session with no pending 2FA at all | Closed |
| AC20 | Nothing asserted change-password invalidates trusted devices while keeping the *requester's own* session valid | Closed |

New file: `tests/test_auth_gap_coverage.py` (Flask test client, `db`/`OrganisationFactory`
fixtures from the shared conftest, no live server). 12 tests written by this pass:

- `test_signup_duplicate_org_name_and_duplicate_email_return_identical_generic_error` (AC3) — asserts byte-identical response bodies, not just similar wording.
- `test_login_generic_401_for_nonexistent_wrong_password_and_locked_account` (AC4) — locks the account directly via `UserRepository.lock_account()` rather than tripping 5 real failed attempts, to avoid colliding with the login rate limiter (a separate AC5 concern); asserts all three failure modes return byte-identical bodies.
- `test_trusted_device_matching_cookie_and_fingerprint_skips_2fa` (AC8 happy path, for contrast)
- `test_trusted_device_fingerprint_mismatch_falls_through_to_2fa` (AC8 unhappy path — valid cookie, wrong fingerprint)
- `test_trusted_device_unknown_token_falls_through_to_2fa` (AC8 unhappy path — cookie matching no stored device)
- `test_logout_does_not_clear_trusted_device_cookie` (AC9) — checks both the absence of a clearing `Set-Cookie` and that the client's cookie jar still carries the token post-logout
- `test_verify_2fa_totp_with_remember_device_sets_cookie_control` — control case establishing TOTP *does* set the cookie, so the AC13 test below is a real contrast, not a tautology
- `test_verify_2fa_backup_code_ignores_remember_device_flag` (AC13) — asserts no `Set-Cookie` for `trusted_device_token` and no `TrustedDevice` row created at all
- `test_cancel_2fa_with_no_pending_state_reports_had_pending_false` (AC17)
- `test_cancel_2fa_with_pending_state_reports_had_pending_true_and_clears_it` (AC17)
- `test_cancel_2fa_clears_a_full_authenticated_session_not_just_pending_keys` (AC17) — logs in fully with no 2FA, calls `/auth/2fa/cancel`, and proves the whole session (not just pending-2FA keys) was wiped
- `test_change_password_invalidates_trusted_devices_but_keeps_own_session` (AC20) — seeds a `TrustedDevice` row directly, changes password, then asserts the caller's own `/auth/me` still resolves while the trusted-device row is gone

## Incidental finding folded in

While this file was in progress, the parallel security-audit pass on this same
review-feature run found and fixed **F3**: `disable_2fa()` deleted backup codes but left
`trusted_device` rows untouched, so an old device token + fingerprint from a prior
enrollment could survive a disable and later skip 2FA under a *new* enrollment. It patched
`app/api/routes/auth_routes.py`'s `disable_2fa()` to delete trusted devices in the same
transaction (mirroring `change_password()`) and added
`test_disable_2fa_invalidates_trusted_devices` to this file. That test is not one of the 7
ACs assigned to this pass (disable_2fa's trusted-device cleanup isn't separately numbered in
the spec — AC16 only mentions backup codes) but it's a direct extension of the AC13/AC20
"trusted device invalidation" theme this pass was already touching, so it stayed in place
rather than being reverted. It passes.

## Before / after

- Before: 10 passed, 30 skipped (3 files).
- After: **23 passed, 30 skipped** (4 files: the 3 original + `test_auth_gap_coverage.py`'s
  13 tests — 12 written by this pass, 1 added by the concurrent security-audit fix).
- Flake check: ran the new file 3 times standalone (all green) and the combined 4-file set
  twice more (all green except one incidental run that hit 2 spurious errors under
  concurrent load from sibling review-feature subagents hammering the same shared test DB
  at the same time — re-running those two tests in isolation immediately passed, confirming
  it was DB contention, not a flaky test; not reproducible against the tests in isolation).

## ACs still without server-exercised coverage, and why

- **AC5, AC6, AC7, AC10, AC11, AC12, AC14, AC15, AC16, AC18, AC19, AC21**: out of this
  pass's assigned scope (task named 7 specific ACs to close). Most of these already have
  live-server coverage in the two `pytest.mark.live_server` files (AC7/AC11/AC12/AC14/AC15/
  AC16 in particular are well covered there when a dev server is up) or unit coverage in
  `test_auth_password_session.py` (AC18, AC19 explicitly; AC21 has no dedicated test in
  either file and remains a genuine gap, but was not in this pass's assigned list).
- No AC in this pass's assigned list (AC3/AC4/AC8/AC9/AC13/AC17/AC20) required a live
  server — all 7 are now covered in-process.

## Live-server status

`python3 scripts/preflight.py --json` reported `app_server: down` (`https://localhost:8005/
not listening`) both before and after this pass — no dev server was started, so the 30
`pytest.mark.live_server` tests in `test_2fa_totp_optimized.py` and
`test_login_2fa_flow.py` were **not exercised** in this run; they skipped with their
standard stated reason (`no dev app server listening... start it (uv run workflow start)`),
exactly matching the task's stated baseline. Starting the server was not required because
every AC this pass was responsible for is pure in-process Flask/pyotp logic.

VERDICT: patched
