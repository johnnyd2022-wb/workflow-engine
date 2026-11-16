# OAuth security check: RFC 9700 and the MCP authorization spec (public MCP 8.2h)

Scope: the app's authorization server (`app/features/mcp_oauth/`), as of 8.2b + 8.2h. Tests named below
are in `tests/mcp_oauth/` (`test_oauth_bcp.py` is new in 8.2h).

**Sources, and what could not be reached.**
- MCP authorization: read live (the `/latest/` text is the **2026-07-28** revision; the draft was also read).
- RFC 9700: **could not be fetched.** The fetch of `rfc-editor.org` was refused with a permission error in this
  session and I did not try another route. The section titles below are written from memory of the published RFC
  and are cited by *title*; verify the numbers against the RFC before quoting them.

## RFC 9700 checklist

| # | Item (RFC 9700 topic) | Status | Proof |
|---|---|---|---|
| 1 | Exact redirect URI matching; no wildcards or prefixes | Met | `test_ac4_redirect_uri_must_match_a_registered_one_exactly`, `test_ac4_an_unknown_redirect_uri_shows_an_error_page_and_never_redirects`. Stricter than RFC 8252's loopback "any port": a loopback client registers the port it will use. |
| 2 | No open redirectors (AS and the sign-in hop) | Met | AS: AC4 page-error tests (bad client or URI never redirects). Sign-in hop: the return target is no longer in the URL (`test_bcp_no_open_redirect_through_the_sign_in_hop`, `test_ac42_a_next_in_the_query_string_is_ignored_…`); the builder only emits `/oauth/authorize?…` (`test_ac42_the_return_url_is_always_the_authorize_path_…`, `test_ac42_a_tampered_session_entry_never_becomes_a_return_url`). |
| 3 | CSRF defence: PKCE and `state` | Met | PKCE S256 is mandatory (AC4 parametrised errors). `state` is echoed unchanged and bounded (`test_ac4_a_bad_protocol_parameter_redirects_with_an_error_and_the_same_state`). The consent form is CSRF-protected (`test_the_consent_form_is_csrf_protected`). |
| 4 | PKCE downgrade: a code without a challenge must not exist | Met | `code_challenge` is NOT NULL, `plain` is refused, and a code exchange without a verifier is `invalid_request` (`test_bcp_a_code_exchange_without_a_verifier_is_refused_and_every_code_has_a_challenge`, `test_ac7_a_wrong_verifier_…`). |
| 5 | Authorization server mix-up (RFC 9207 `iss`) | **Fixed in 8.2h** | `test_ac41_*` (every error and success redirect carries `iss`; metadata advertises it). |
| 6 | Authorization code: single use, short life, bound to client, redirect URI, resource | Met | AC7, AC8, `test_ac7_every_binding_on_the_code_must_match`, `test_ac7_a_code_for_one_client_cannot_be_redeemed_by_another`. Replay revokes the grant. |
| 7 | Implicit grant not offered | Met | `test_bcp_implicit_and_password_grants_are_not_offered`, `test_ac4_…response_type_token`. |
| 8 | Resource owner password credentials grant not offered | Met | same test (`password`, `client_credentials` → `unsupported_grant_type`). |
| 9 | Access tokens never in a URL | Met | `test_ac18_a_token_never_works_in_the_query_string_or_a_cookie`. The only credential in a redirect is the one-time code. |
| 10 | Referer and history leakage of codes and state | Met | Consent: `Referrer-Policy: same-origin` (`test_bcp_the_consent_page_sends_no_referer_to_other_sites`, 8.2b fix); `Cache-Control: no-store` (`test_bcp_oauth_responses_are_not_cached`); codes live 60 s and burn on use. |
| 11 | Refresh token: rotation with reuse detection for public clients | Met | AC9, `test_f3_*`. |
| 12 | Refresh token bound to its client | Met | `test_ac9_a_refresh_token_belongs_to_one_client` (and revoke: `test_another_clients_revoke_does_not_end_the_grant`). |
| 13 | Token audience and privilege restriction (RFC 8707, scope) | Met | AC18 (audience), AC12–AC14 (read-only, per-permission), `test_ac9_refresh_cannot_widen_the_scope`. |
| 14 | Short-lived access tokens | Met | 1 h (`test_ac7_the_stored_values_are_hashes_and_the_expiries_match_the_spec`). |
| 15 | Stolen-token misuse: sender-constrained tokens | **Not now** (DPoP, out of scope per spec). Mitigated by 1 h life, per-request org and role check (AC16), revocation (AC23), read-only. |
| 16 | No 307 redirect for credentialed POSTs | Met | `test_bcp_the_consent_decision_answers_302_not_307`. |
| 17 | Clickjacking | Met | `test_ac43_every_authorize_response_refuses_framing` (consent, blocked page, error page, decision, error redirect). Comes from the app-wide header hook (only two unrelated paths are framable); the test pins it. Deliberately **no** `form-action`: Chrome applies it to the redirect a form POST is answered with and would stop the browser reaching the assistant (`test_ac43_consent_does_not_restrict_form_action`). A blueprint-level header would be overwritten by the app-wide one, so none is added. |
| 18 | TLS only | Met | HTTP → 301 HTTPS (`test_bcp_plain_http_is_redirected_to_https`), HSTS (`test_bcp_oauth_responses_carry_hsts_over_https`), test and prod `[mcp]` issuer and resource are `https://` (`test_bcp_the_deployed_issuer_and_resource_are_https`), DCR and CIMD redirect URIs must be https or loopback (AC2). |
| 19 | Client impersonating the resource owner | Not applicable: no client-credentials grant, no client-held user identity; every grant is a person's explicit consent. |
| 20 | TLS-terminating reverse proxy attacks | Not applicable: no mutual TLS or client certificates; the proxy only forwards `X-Forwarded-Proto`, which the HTTPS redirect uses. |
| 21 | Discovery-document DoS / SSRF on client metadata | Met | CIMD fetch is SSRF-guarded, 5 s and 64 KB capped, and only after sign-in (AC3, `test_f1_*`). |

## MCP authorization spec, 2026-07-28 re-check

| Topic | Spec says | Ours | Result |
|---|---|---|---|
| CIMD vs DCR | CIMD SHOULD, DCR MAY (deprecated), clients prefer pre-registered, then CIMD, then DCR | Both supported; metadata advertises `client_id_metadata_document_supported` | OK |
| DCR `application_type` | Clients MUST send `native` or `web` | Unknown fields are ignored | OK (`test_mcp_spec_dcr_accepts_application_type`) |
| `resource` (RFC 8707) | Client MUST send in authorize and token requests | Required on authorize, checked on token and refresh | OK |
| AS discovery | RFC 8414 or OIDC discovery; `issuer` must match | `/.well-known/oauth-authorization-server`, issuer from config, no path | OK |
| PKCE | S256; clients refuse if `code_challenge_methods_supported` is absent | Advertised, S256 only | OK |
| RFC 9207 | SHOULD send `iss`, and then MUST advertise the flag; clients reject a missing one | Done in 8.2h | OK (was a gap) |
| Redirect URIs | https or localhost, exact match | Same | OK |
| Tokens | Header only, never the query string; audience validated | Same | OK |
| Refresh | Public-client rotation is an AS MUST | Rotating, with reuse detection | OK |
| Scope step-up | 403 `insufficient_scope` with `scope`; client SHOULD step up, cap retries | One scope (`bize.read`); a write or settings route can never be reached by a larger scope. The MCP server maps the app's 403 to a tool error, so no client sees a step-up challenge | **Not supported on purpose.** Revisit with `bize.write` |

### Follow-ups the check turned up (not fixed here: `bize_mcp/` is 8.2c's)

1. **Token passthrough (8.2c design, needs a decision).** The spec says "The MCP server MUST NOT pass through
   the token it received from the MCP client" to an upstream API, which "is a separate token, issued by the
   upstream authorization server". Our `bize_mcp` forwards the caller's token to the app. The app *is* the
   issuer and validates the audience, so the confused-deputy risk the rule targets is not there, but a literal
   reading still flags it. Options: (a) keep it and record it as a deliberate deviation; (b) have the MCP server
   hold its own service credential and pass the user identity separately (bigger change, new trust surface).
   Recommendation: (a) for the MVP, with the founder told.
2. **Protected-resource metadata path.** For a resource with a path (`…/mcp`), clients fall back to
   `/.well-known/oauth-protected-resource/mcp` before the root one when no `resource_metadata` is given.
   8.2c should serve both.
3. **`scope` in the MCP server's 401 challenge** (SHOULD): add `scope="bize.read"` next to `resource_metadata`.
4. `append_query` keeps a registered redirect URI's own query; a URI that already carries `code`, `state` or
   `iss` would duplicate them. Only the registrant can cause it, so it harms only itself. Left.

## F7 (8.2b review): sign-in returns to the pending request

Done. `/oauth/authorize` stores the allowlisted parameters in the session (`pending_authorization`: 15 min,
bounded to fit the cookie, re-validated on read) and sends the visitor to `/?login=1`. Password, 2FA, Google,
Google+2FA and first-time 2FA enrolment (`/auth/me` → `return_to`) all return to `/oauth/authorize?` rebuilt from
the stored values; the endpoint validates the request afresh. The `next=` query parameter and its landing-page
script are gone. `rotate_session()` keeps only a well-formed pending request.
Not covered by a browser test: the three small JS changes (landing, Google challenge page, settings) are
pinned by text checks and the server tests, not Playwright.
