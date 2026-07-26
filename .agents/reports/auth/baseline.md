# BASELINE: auth
date: 2026-07-26
git: review-feature branch, clean

## Command
`unset ENVIRONMENT && uv run pytest tests/test_auth_password_session.py tests/test_2fa_totp_optimized.py tests/test_login_2fa_flow.py -v`

## Result
10 passed, 30 skipped (live_server-marked 2FA suites — no app server running; per
preflight decisions.live_server_tests=skip, this is expected, not a failure)

## Notes
- No pre-existing failures.
- The 30 skips are entirely in test_2fa_totp_optimized.py and test_login_2fa_flow.py —
  both require a live app server for the full 2FA round trip. Re-run with
  `uv run workflow start` up to get real coverage numbers for AC7-AC17.
