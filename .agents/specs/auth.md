# SPEC: auth
status: reviewed
name: Authentication & 2FA
slug: auth
blueprint: app/api/routes/auth_routes.py (registered directly in app/api/app_factory.py as auth_bp)
url_prefix: /auth

## Description
Session-based authentication: signup (org + admin user creation), login with account
lockout and optional TOTP 2FA (trusted-device bypass), logout, current-user/org context,
2FA enrollment/enable/disable/cancel, session-timeout preference, password-policy
checking, password change, and user profile settings. Backed by `AuthService`
(app/core/security/auth_service.py), `OrgManager`, `UserRepository`,
`TrustedDeviceRepository`, and Flask-Limiter for per-route rate limiting.

## Users & permissions
- roles: anonymous (signup, login, logout, /me, verify-2fa, 2fa/cancel,
  password-policy-check are all pre-auth or public), authenticated user
  (`@requires_auth`: 2fa/enroll, 2fa/enable, 2fa/disable, session-timeout,
  change-password, settings)
- tenant_scoped: yes for authenticated routes (`user.org_id` / `g.current_org_id`
  implicitly scopes all reads/writes to the caller's own org+user row; there is no
  cross-org listing in this blueprint).
- ASSUMPTION: `/auth/2fa/cancel` and `/auth/logout` are intentionally unauthenticated —
  they only clear session state and don't touch another user's data, so no auth
  decorator is required.

## Acceptance criteria

### Signup & login
- AC1: `POST /auth/signup` creates an org + admin user, starts an authenticated
  session (with `rotate_session()` to avoid session fixation), logs the action, and
  emits `user.created`; rate-limited to 5/min per IP+email (relaxed to 1000/min under
  `CI`/`GITLAB_CI`/`ENVIRONMENT=test`).
- AC2: `POST /auth/signup` rejects mismatched `password`/`password_confirm`, invalid
  email format, and invalid/missing phone number with 400, all before any DB write.
- AC3: `POST /auth/signup` returns the same generic "Cannot complete request" 400 for
  both duplicate org name and duplicate email — no user/org enumeration via error text.
- AC4: `POST /auth/login` authenticates by email+password (optionally scoped to
  `org_id` if supplied), clears any stale session data first, and returns the same
  generic 401 message whether the account doesn't exist, the password is wrong, or the
  account is locked — no enumeration via error text or status code.
- AC5: 5 consecutive failed logins for a user locks that account for 1 minute
  (`increment_failed_login_attempts` → `lock_account`); a successful login or a
  `password_reset: true` login resets/unlocks it.
- AC6: A locked-out login attempt, a failed attempt, and an account lock each write an
  audit `log_action` and (for lock/failure) emit an event, capturing IP + User-Agent —
  never the password.
- AC7: When `user.two_factor_enabled`, login does not fully authenticate; it returns
  `{"requires_2fa": true}` and stores only `pending_2fa_user_id` +
  `pending_2fa_created_at` in the session — `user_id`/`org_id` are explicitly absent
  until 2FA succeeds.
- AC8: A valid trusted-device cookie (`trusted_device_token`, matching stored hash) AND
  a matching device fingerprint together let login skip 2FA entirely and establish a
  full session; a mismatch on either falls through to the 2FA challenge.
- AC9: `POST /auth/logout` clears the full session (but leaves the trusted-device
  cookie intact) and logs the logout if a session existed; always returns 200.
- AC10: `GET /auth/me` is public, always returns 200, and returns
  `{"user": null, "organisation": null}` when logged out vs. the user/org context when
  logged in.

### 2FA verification & management
- AC11: `POST /auth/verify-2fa` requires a live `pending_2fa_user_id` in the session
  (set only by `/auth/login`); without one, or once it's older than
  `PENDING_2FA_EXPIRY_MINUTES` (5 min), it returns 401 and clears any stale pending
  state.
- AC12: `POST /auth/verify-2fa` accepts either a 6-digit TOTP code or an 8-char
  alphanumeric backup code (format-validated before any DB/crypto work); on success it
  rotates the session, establishes full auth, and clears the pending 2FA state.
- AC13: A backup code cannot be used to create a trusted-device cookie
  (`remember_device` is ignored when `backup_code_used`), even if requested.
- AC14: `POST /auth/2fa/enroll` (auth required) generates a TOTP secret + QR code;
  re-calling it while enrollment is in-progress (secret set, not yet enabled) returns
  the same secret rather than rotating it; calling it once 2FA is already enabled
  returns 400.
- AC15: `POST /auth/2fa/enable` (auth required) requires two different, both-valid TOTP
  tokens before enabling 2FA and issuing 10 backup codes, atomically (single
  transaction; any failure rolls back both the enable and the codes).
- AC16: `POST /auth/2fa/disable` (auth required) is idempotent — disabling an
  already-disabled account returns 200 with `already_disabled: true` rather than an
  error — and atomically deletes all backup codes when it does disable.
- AC17: `POST /auth/2fa/cancel` clears the whole session (not just pending-2FA keys)
  and always returns 200 with `had_pending` reflecting prior state; no auth required.

### Session, password, settings
- AC18: `GET/PUT /auth/session-timeout` (auth required) reads/writes the caller's own
  `session_timeout_minutes`, validated against `MIN_SESSION_TIMEOUT_MINUTES`/
  `MAX_SESSION_TIMEOUT_MINUTES` on PUT; out-of-range or non-int values return 400.
- AC19: `POST /auth/password-policy-check` is public/advisory-only: it never blocks,
  only returns `warnings` + `is_valid` for length/upper/lower/digit/special-char rules.
- AC20: `POST /auth/change-password` (auth required) verifies `current_password`
  against the stored hash, rejects mismatched confirmation and a new password equal to
  the current one, hashes the new password with bcrypt, invalidates all trusted
  devices for the user (forcing 2FA again elsewhere), and rotates the current session
  (new session id, same device stays logged in).
- AC21: `GET/PUT /auth/settings` (auth required) reads/updates the caller's own
  first/last name, email, and phone number only (never `org_name`, never another
  user's row); email format and name length (<=255) are validated; a duplicate email
  returns 409, not 400/500.

## Data model
- changes: none (existing `user`, `organisation`, `trusted_device` tables)
- destructive: no

## External surfaces
- None third-party. Internal: TOTP (pyotp) + QR generation (qrcode) are local
  crypto/rendering, no outbound calls. Rate limiting via Flask-Limiter
  (in-process/storage backend, not reviewed here — see its own config).

## Out of scope
- `AuthService` internals (hashing, TOTP verification, backup-code generation) — unit
  covered by its own tests; this spec covers the route contract, not the crypto
  implementation.
- `OrgManager.create_org_with_admin_user` internals — shared with the `org` spec; only
  the signup route's use of it is in scope here.
- Flask-Limiter storage backend configuration (in-memory vs Redis) — infra concern,
  not part of this feature's behavior.
