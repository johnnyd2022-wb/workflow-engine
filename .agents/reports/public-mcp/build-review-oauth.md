# Build review: public MCP 8.2b (sign-in for assistants)

Advisory review by an independent Claude reviewer (`code-review` at high effort plus a manual pass on
a security brief: tenant isolation, token handling, CSRF, open redirect, SSRF, scope escalation),
over `git diff origin/main...HEAD`. Codex is out of quota until 17 Nov 2026. Regression run of the
existing suite (excluding e2e): 4817 passed, 31 skipped, 2 failed; both failures were F2 below.

| # | Sev | Finding | Disposition |
|---|---|---|---|
| F1 | High | A signed-out visitor could make the server fetch any https `client_id` URL, and the "5 s" cap was per read, not total | **Fixed.** Unknown or stale metadata-URL clients are looked up only after sign-in (signed-out goes to login first); the fetch uses `Timeout(total=5)` and `read1` so the deadline is checked after every bit of data; the DB transaction is committed before the network call. Test: `test_f1_*`. |
| F2 | High | `tests/test_data_export.py` red; the admin "every record" export would include token/code hashes and `auth_stamp` | **Fixed.** `oauth_tokens`, `oauth_authorization_codes` excluded; `oauth_clients` classified non-tenant; `oauth_grants.auth_stamp` excluded; `mcp_allowed_roles.role_key` declared safe. |
| F3 | Med | A refresh token revoked by a reconnect (M2) counted as "reuse" and killed the new connection | **Fixed.** Only a token with `replaced_by_id` (rotated out) triggers grant revocation. Test: `test_f3_*`. |
| F4 | Med | `disabled_at` only blocked consent | **Fixed.** Checked in bearer auth, code exchange and refresh. Test: `test_f4_*`. |
| F5 | Low | Approving again refreshed `auth_stamp` in place, reviving tokens after a password change | **Fixed.** A live grant with a stale stamp is revoked and a fresh one created. Test: `test_f5_*`. |
| F6 | Low | Error redirects before sign-in let an attacker with a DCR client redirect from our domain | **Rejected.** AC4 and the spec require redirecting protocol errors to a registered redirect URI; unknown clients and URIs already show a page. Noted as a follow-up (verified-only redirects). |
| F7 | Low | `next` is honoured for password/2FA only; Google sign-in and the admin 2FA-enrolment path land on the dashboard | **Deferred.** AC5 names password + 2FA. Stated in the MR; follow-up. |
| F8 | Low | Token endpoint mints/rotates while the org switch is off | **Rejected.** Deliberate: every request is refused with `mcp_not_allowed` and flipping the switch back restores the same token (AC16). |
| F9 | Low | `scripts/tenant_copy.py` would copy grants/tokens without `oauth_clients` | **Deferred.** Tokens are audience-bound, so copies are useless; follow-up to skip these tables. |
| F10 | Low | Nothing prunes expired codes, rotated tokens, unused clients | **Deferred.** Follow-up cleanup job. |
| F11 | Nit | `Bearer` scheme matched case-sensitively | **Fixed.** Test: `test_f11_*`. |
| F12 | Nit | Global `oauth_clients` queries log `tenant_filter.no_context` | **Left.** Harmless warning on a deliberately global table. |
| F13 | Nit | `urllib3`/`certifi`/`limits` imported directly, installed transitively | **Left.** Already pinned through `requests` and `flask-limiter`. |
| F14 | Nit | Denied token on a non-`/api/` page route with `Accept: */*` is a 302 not 403 | **Left.** Existing behaviour of the denial branch; API paths return 403. |
| F15 | Nit | Log `g.current_org_id`; tick 8.2b; advisory Content-Length | **Tick done in the MR;** the rest left (the app-wide `MAX_CONTENT_LENGTH` bounds bodies). |

Checked and sound (reviewer): CSRF exemptions are exactly register/token/revoke; consent POST is
protected and frame-denied; redirect_uri exact match and error-page-not-redirect; `next` is not an
open redirect; hashes only; PKCE constant-time; code single use under row lock; audience binding;
SSRF address policy and IP pinning; autoescaped display; bearer path never overrides a session user;
tenant scoping and composite FKs; migration shape.
