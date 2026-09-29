# SECURITY: auth
date: 2026-07-26
verdict: patched
scanned: semgrep(1 finding pre-fix → 0 post-fix; a learned rule added during this audit surfaced 3 more false positives in already-correct code, also suppressed), gitleaks(17 repo-wide, 0 in the audited files), uv-audit(0 vulnerabilities across 82 packages)
manual_checklist: 7/7 completed

Scope: `app/api/routes/auth_routes.py` (1501 lines, whole file), `app/core/security/auth_service.py`,
`app/core/security/org_manager.py`, `app/api/middleware/session_security.py`,
`app/core/db/repositories/trusted_device_repo.py`, `app/core/db/repositories/user_repo.py`, plus
`app/core/db/repositories/backup_code_repo.py` and `app/core/db/models/trusted_device.py`
(transitively imported by the above, read for AC12/AC13/AC8 correctness).

## Findings

- F1 [fix] `app/core/security/auth_service.py::authenticate()` + `app/api/routes/auth_routes.py::login()` —
  timing-based user/org enumeration side channel.
  repro/evidence: `authenticate()` returned `None` immediately (no bcrypt call) when the
  email didn't exist, the account was inactive, or the supplied `org_id` didn't match the
  account's real org — while a real account with a wrong password paid bcrypt's ~100ms+
  cost via `verify_password()`. Separately, `login()`'s account-lockout branch returned
  before ever calling `authenticate()`, so a locked account also responded near-instantly.
  AC4 requires identical *response bodies*, which was already true, but wall-clock latency
  was not — an attacker measuring response time could distinguish "no such email" /
  "wrong org_id for this email" / "locked account" from "wrong password", i.e. enumerate
  valid emails and (via the optional `org_id` login parameter) which org an email belongs
  to. Confirmed structurally: `users.email` carries a global unique index
  (`app/core/db/models/user.py:28`), so `org_id` never disambiguates two same-email
  accounts — its only observable effect pre-fix was this timing oracle.
  patch: `authenticate()` now always performs one bcrypt comparison — a fixed
  `_DUMMY_PASSWORD_HASH` (computed once at import, bcrypt cost 12) when the account
  doesn't exist/is inactive/doesn't match `org_id`, the real hash otherwise. `login()` now
  calls `authenticate()` *before* branching on lockout state, so the bcrypt cost is paid
  exactly once on every path (nonexistent user, wrong org_id, wrong password, locked
  account) before the response is decided. Verified as a real regression: reverting the
  patch fails 3 of the new tests (`test_authenticate_invokes_bcrypt_for_nonexistent_email`,
  `test_authenticate_invokes_bcrypt_for_wrong_org_id`, plus F2's session test) with 5
  passing, confirming these tests exercise the actual fix, not incidental behavior.
  tests: `tests/test_auth_login_security.py` (8 tests: bcrypt-call-count parity for
  nonexistent-email/wrong-org-id/wrong-password, response-body identity across
  nonexistent/wrong-password/wrong-org-id, and two success-path sanity checks).
  rule_added: none — this is a timing/semantic property (bcrypt invocation count vs.
  wall-clock cost), not a syntactic AST shape semgrep can generalize; the regression tests
  are the guard for this class going forward.

- F2 [fix] `app/api/routes/auth_routes.py::change_password()` — session-rotation drift
  lost `session.permanent`.
  repro/evidence: every other auth transition (`signup`, `login`, `verify_two_factor`)
  calls the shared `rotate_session()` helper, which does `session.clear()` +
  `session.permanent = True`. `change_password()` instead hand-rolled
  `session.clear()` followed by a manual per-key restore loop, never re-setting
  `session.permanent`. Flask stores the permanent flag as the `_permanent` key inside the
  session dict itself, so a bare `.clear()` wipes it along with everything else — the
  post-password-change session cookie silently downgraded from a persistent (30-day,
  `Expires=`-bearing) cookie to a browser-session-only one. Not exploitable by an
  attacker directly, but a real functional/security-posture regression: users would be
  logged out on next browser close right after changing their password, with no visible
  cause, and it broke the "same rotation guarantee everywhere" invariant the rest of the
  file relies on.
  patch: `change_password()` now calls the shared `rotate_session()` helper (same call as
  login/signup/verify-2fa) instead of re-deriving the clear+restore by hand.
  tests: `tests/test_auth_login_security.py::test_change_password_keeps_session_permanent`
  — asserts the `Set-Cookie` header carries `Expires=` (persistent-session marker) after
  both login and change-password. Confirmed as a real regression: fails without the patch.
  rule_added: `.semgrep/rules/learned.yml#bize-session-clear-without-rotate` — fires on a
  bare `session.clear()` not immediately followed by `session.permanent = ...` and not
  inside `rotate_session()` itself. Fixture pair at
  `.semgrep/fixtures/bize-session-clear-without-rotate/{vulnerable,fixed}.py`, verified via
  `python scripts/rule_candidates.py verify` (fires on vulnerable, silent on fixed). This
  rule is intentionally broad (any hand-rolled clear-then-repopulate), so it also matched
  three *intentional* full-clears with nothing re-established afterward — see F4.

- F3 [fix] `app/api/routes/auth_routes.py::disable_2fa()` — didn't invalidate trusted
  devices, allowing a stale device to bypass a fresh 2FA re-enrollment.
  repro/evidence: `disable_2fa()` deleted backup codes and cleared `two_factor_enabled`,
  but left `trusted_devices` rows for the user untouched. Those tokens exist purely to
  bypass 2FA and are logically scoped to the enrollment that minted them. If a user
  disabled 2FA and later re-enrolled (new TOTP secret, new backup codes), a
  `device_token`+fingerprint pair from the *old* enrollment would still satisfy
  `login()`'s trusted-device check (`trusted_device.user_id == user.id` and fingerprint
  match — nothing ties it to a specific TOTP secret/enrollment epoch) and skip 2FA under
  the new enrollment entirely, silently defeating the point of re-enrolling.
  `change_password()` already invalidates trusted devices for the analogous reason;
  `disable_2fa()` did not.
  patch: `disable_2fa()` now also calls `trusted_device_repo.delete_user_devices(user.id)`
  inside the same atomic transaction as the backup-code deletion, and logs
  `trusted_devices_deleted` alongside `backup_codes_deleted`.
  tests: `tests/test_auth_gap_coverage.py::test_disable_2fa_invalidates_trusted_devices` —
  enrolls 2FA, mints a trusted device, disables 2FA, re-enrolls, and proves the old
  device token now falls through to a fresh 2FA challenge instead of skipping it.
  Confirmed as a real regression: fails without the patch (old device token still
  bypassed 2FA post-re-enrollment).
  rule_added: none — this is a missing-side-effect (an app-specific "which cleanup
  routines must run together" invariant), not a generalizable syntactic pattern.

- F4 [false-positive] `app/api/routes/auth_routes.py::logout()`, `::cancel_2fa()`,
  `app/api/middleware/session_security.py`'s inactivity-timeout handler — new
  `bize-session-clear-without-rotate` rule (added for F2) also fired here.
  repro/evidence: all three call `session.clear()` and intentionally end the session with
  nothing re-established afterward (AC9: logout leaves the session ended; AC17: cancel_2fa
  clears the whole session; the inactivity handler force-expires and returns
  401/redirect). There is no `session.permanent` to preserve because no new authenticated
  session data is ever written back in these paths — unlike F2's `change_password()`,
  which re-establishes a full session after clearing.
  patch: suppressed with `# nosemgrep: bize-session-clear-without-rotate` and an inline
  justification comment at each of the 3 call sites, rather than narrowing the rule
  itself (a "clear-then-repopulate" dataflow rule that only matches the F2 shape would be
  significantly more complex for marginal precision gain over 3 well-justified
  suppressions).

- F5 [false-positive] `app/api/routes/auth_routes.py:104` (`get_rate_limit_key`) —
  semgrep `python.flask.security.audit.directly-returned-format-string`.
  repro/evidence: `return f"{ip}:{email}"` is a Flask-Limiter `key_func` return value
  (a rate-limit bucket key), never sent to the client as an HTTP response body — the rule
  is designed to catch f-strings returned directly from a Flask *view* (reflected-XSS
  shape), which this is not.
  patch: suppressed with `# nosemgrep: directly-returned-format-string` and a justification
  comment. Note: I recorded this verdict as `false-positive` myself via
  `scripts/finding_history.py record` (the mechanical reasoning is unambiguous — the value
  never reaches an HTTP response), but per the skill's rule that `false-positive` /
  `accepted-risk` verdicts are a human call, this specific history entry should get a
  human nod rather than being taken as final.

- F6 [false-positive] `app/api/routes/auth_routes.py:589,734,891` —
  `bize-verbose-error-to-client` (a rule born from the *concurrent* org-blueprint
  security-audit running in this same worktree, not authored by this audit, but it fires
  inside my scoped file so I triaged it here rather than leaving it unactioned).
  repro/evidence: three `except ValueError as e: logger.warning(f"...{e}")` /
  `logger.exception(...)` blocks where the exception is interpolated into the
  *server-side log line only* — the `jsonify(...)` response returned to the client two
  lines below each is a fixed generic string (`"Invalid request"`,
  `"2FA session expired. Please log in again."`) that never includes `e`. The rule's
  pattern matches any f-string interpolation of the exception inside a `try/except` block
  regardless of whether it lands in the log or the response body, so it can't distinguish
  this (correct) pattern from the real bug class it was written for.
  patch: suppressed with `# nosemgrep: bize-verbose-error-to-client` and a justification
  comment at each of the 3 sites. Did not touch the rule itself or `.semgrep/rules/learned.yml`'s
  ownership beyond this — it belongs to the other audit's finding history.

- F6 [patched 2026-09-25, plan item 0.2] `app/api/routes/auth_routes.py:707` (`verify_two_factor`) — no
  brute-force throttle on 2FA code entry. Recorded here on 2026-09-19 by a findings-sweep
  run while answering findings-index item 5c84c42e; it was not produced by a security-audit
  pass, so this audit has not triaged or graded it yet.
  repro/evidence: `/auth/verify-2fa` carries no `@limiter.limit` (only `/auth/signup` and
  `/auth/login` do, `auth_routes.py:159,256`) and no attempt counter: `failed_login_attempts`
  and `lock_account` are only ever called from `/auth/login` (`auth_routes.py:378-459`),
  `AuthService.verify_totp` is a bare `pyotp.TOTP.verify(token, valid_window=1)`
  (`auth_service.py:188-193`), and the backup-code path has no counter either. Observed with
  a throwaway test (not committed): after a correct-password login for a 2FA-enabled user,
  130 wrong 6-digit codes to `/auth/verify-2fa` in one pending session returned 130 x 401 —
  no 429, no lockout, `failed_login_attempts` still 0, `locked_until` still None.
  impact: anyone who already holds a user's password can guess codes without limit for the
  pending window (`PENDING_2FA_EXPIRY_MINUTES`, 5 min, `auth_routes.py:135`). `valid_window=1`
  accepts about 3 of the 10^6 six-digit codes, so success chance per pending session is
  roughly 3 x guesses / 10^6 (illustratively ~9% at 100 guesses/s for the full window; the
  request rate is not measured). A fresh pending session needs a fresh `/auth/login`, which
  is itself limited to 5/min per ip:email, so this bounds the number of sessions, not the
  guesses inside each one.
  patch (2026-09-25, with plan item 0.2): its own counter, not the login lockout. Five wrong
  codes in one pending session end it (`MAX_2FA_FAILURES_PER_PENDING_SESSION`), so the
  password has to be entered again, and `/auth/verify-2fa` is limited to 5/minute and
  20/hour keyed on the pending account (`_pending_2fa_rate_limit_key`), not the IP. The
  account key is what bounds total guesses: `/auth/login` resets the account's failure
  counter on every correct password, so a per-session cap alone could be sidestepped by
  logging in again. Trade-off accepted: someone who already holds the password can use up
  the owner's 20/hour and delay their sign-in for up to an hour, which is far better than
  unlimited guessing. The limits use the same fail-closed `USE_RELAXED_AUTH_RATE_LIMITS`
  gate as login/signup. Regression test:
  `tests/test_admin_2fa_policy.py::test_wrong_2fa_codes_end_the_pending_session_after_five`.
  Original note follows.
  patch: none. Not started because it needs a policy decision, not just code — should a 2FA
  failure count toward the existing login lockout (a caller who knows the password could then
  lock the owner out), or get its own counter that ends the pending session? What limit
  values? The existing limiter key (`get_rate_limit_key`, ip:email taken from the JSON body)
  does not fit, since `/auth/verify-2fa` carries no email and would degrade to IP-only.
  Whatever is chosen must keep the fail-closed relaxation gate described under Escalations
  below. Route to fix-bug with the repro above as the failing test first; do not encode the
  current unthrottled behaviour in any test (`tests/test_replay_app_contract.py` does not).
  tracking: this report's header verdict (`patched`, 2026-07-26) predates F6 and is left as
  the audit wrote it. The findings index skips reports whose header verdict is closed, so F6
  is tracked as item 4 under "Security findings requiring owner action" in
  `docs/core-load-performance-design.md`. A security-audit pass should triage it and update
  this report's verdict.

## Escalations (not self-fixed — reported per `.agents/autonomy.md`)

- **`USE_RELAXED_AUTH_RATE_LIMITS` / `ENVIRONMENT=test`.** The relaxed 1000/min rate limit
  is gated on `CI`, `GITLAB_CI`, or `ENVIRONMENT=test` env vars, computed once at import
  time from `os.getenv` — not user-controllable from a request, so this is not a
  code-level vulnerability. But it is a real deployment risk *class*: if a production
  deployment's environment were ever misconfigured with `ENVIRONMENT=test` (or `CI=true`),
  brute-force protection on `/auth/login` and `/auth/signup` would silently relax to
  1000/min with no runtime signal. This is an infra/ops guardrail question (e.g. "does the
  production deploy pipeline assert `ENVIRONMENT != test` before serving traffic"), not
  something this audit can fix inside the auth blueprint — escalating per the
  architectural-finding row of the skill's remediation table rather than patching around
  it here.
- **`org_id` as an optional `/auth/login` parameter has no legitimate function.** Since
  `users.email` is globally unique (not per-org), `org_id` never disambiguates two
  same-email accounts across orgs — it can only ever narrow a lookup to "this email, but
  only if it's in org X." F1's fix closes the *timing* oracle this created, but the
  parameter itself still has no product purpose I could find; removing it would shrink
  the attack surface further at zero functional cost. Flagging as a product/architecture
  question for a human call rather than removing an API parameter unilaterally in a
  security-audit pass.

## Attempted but clean

- **Trusted-device bypass logic (AC8), `login()` ~line 420-540.** Traced the full path:
  requires both a `trusted_device_token` cookie AND non-empty `device_fingerprint` data;
  looks up the device by hashed token; then explicitly re-checks `user_id` match,
  fingerprint match, and `is_expired()` before trusting it — any single mismatch discards
  the device and falls through to the 2FA challenge. `TrustedDevice.is_expired()`
  (`app/core/db/models/trusted_device.py`) correctly normalizes naive-vs-aware datetimes
  before comparing. No path found where a mismatched or stale token/fingerprint grants a
  session or skips 2FA. Covered by 3 existing tests in `tests/test_auth_gap_coverage.py`
  (matching pair, fingerprint mismatch, unknown token) plus the new F3 test.
- **User enumeration via error text/status code (AC4).** Verified byte-identical JSON
  bodies and identical 401 status across nonexistent-user, wrong-password, wrong-org-id,
  and locked-account paths (pre-existing + new tests). The *content* was always
  identical; F1 addresses the separate timing dimension.
- **Backup codes: one-time-use + trusted-device blocking (AC12/AC13).**
  `backup_code_repo.verify_and_consume_code()` uses `SELECT ... FOR UPDATE` to lock
  unconsumed rows, `secrets.compare_digest` for constant-time comparison, and only commits
  (marking `consumed=True`) on a match — race-safe one-time use. `verify_two_factor()`
  gates trusted-device creation on `not backup_code_used`, confirmed by existing test
  `test_verify_2fa_backup_code_ignores_remember_device_flag`.
- **Tenant/self-scoping on `/auth/2fa/enroll|enable|disable`, `/auth/change-password`,
  `/auth/settings`, `/auth/session-timeout` (all `@requires_auth`).** Every one of these
  routes reads `g.current_user` (populated by middleware from the session, never from
  request body/path) and passes `user.id`/`user.org_id` into repository calls — no route
  accepts a user id or org id as an operable parameter from the client. `settings` PUT
  reads an explicit allowlist (`email`, `first_name`, `last_name`, `phone_number`) via
  `data.get(...)`, never `org_name`; `update_user()` requires `(user_id, org_id)` together.
- **Mass assignment, injection, SSRF/uploads.** No `Model(**request.json)` / looped
  `setattr`; all queries are SQLAlchemy ORM filters (no raw SQL); no templates render user
  input with `|safe`/`Markup`; no `subprocess`; no file uploads or outbound URL fetches in
  this blueprint (QR generation is local `qrcode`/`pyotp`, no network call).
  Password/backup-code hashing/encryption never logged (spot-checked every `log_action`
  call in the file — none carries a password, token, TOTP secret, or backup code).
- **CSRF.** This blueprint's routes rely on the app-wide Flask-WTF CSRF wiring
  (`WTF_CSRF_ENABLED`, disabled only in test config) rather than per-route logic — nothing
  in this file's scope to patch; consistent with the spec's stated out-of-scope items.
- **`secure_cookie = request.is_secure or X-Forwarded-Proto == "https"`** (trusted-device
  cookie flag in `verify_two_factor()`). Reflects the real WSGI-detected transport or an
  explicit forwarded-proto header; an attacker spoofing that header on a direct
  (non-proxied) request can only make the app *believe* it's HTTPS (setting `Secure=True`
  on a plain-HTTP response, which the browser then drops) — there's no path to force a
  false-negative that ships a cookie without `Secure` over a real HTTPS connection. Noted,
  not a finding.

## not_verified

- `tests/test_2fa_totp_optimized.py` (14 tests) and `tests/test_login_2fa_flow.py` (16
  tests) are both `pytest.mark.live_server` and skipped this run — no dev server was
  listening (`app_server: down` per preflight). These cover 2FA enroll/enable/disable and
  the full login→2FA→verify round trip end-to-end over real HTTPS requests. I substituted
  equivalent in-process coverage where the spec called for it (F1/F2/F3's new tests, plus
  the pre-existing `tests/test_auth_gap_coverage.py`, all driven through the real Flask
  routes via the test client rather than live HTTP), but did not independently confirm
  these two suites pass against a live server in this run — that would need
  `uv run workflow start` first, per the skill's preflight note.
- I did not empirically measure wall-clock response-time parity for F1 (e.g. timing an
  actual login attempt over many samples). That would be flaky in CI and isn't necessary
  to prove the fix: the tests instead assert the mechanism directly (bcrypt is invoked
  exactly once on every path, verified via a `bcrypt.checkpw` spy), which is a stronger and
  non-flaky guarantee than a timing assertion would be.
- `gitleaks` ran repo-wide (900 commits, ~24MB scanned) and found 17 pre-existing leaks,
  none inside the audited auth files — I did not re-triage those; they're unrelated to
  this blueprint and several are already tracked (see the skill's own worked example,
  `app/tls/app_cert.key`, `.agents/reports/security-audit/2026-07-17-committed-origin-key.md`).

## Verification performed

- `env -u ENVIRONMENT uv run pytest tests/ -q` (full suite): **497 passed, 30 skipped**
  (skips are the live-server 2FA suites, expected — no dev server running), 0 failed.
- `uv run ruff check` on every touched file: clean.
- `python scripts/rule_candidates.py verify`: all 3 learned rules (including the new
  `bize-session-clear-without-rotate`) fire on their vulnerable fixture and stay silent on
  the fixed one.
- Reverted each patch in turn (`git stash` on `auth_routes.py`) and re-ran the new
  regression tests to confirm they actually fail pre-patch: F1's two bcrypt-parity tests,
  F2's session-permanent test, and F3's disable-invalidates-devices test all fail against
  the unpatched code and pass against the patched code — proving each is a real
  before/after regression test, not incidental.
