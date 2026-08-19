# SECURITY: shell
date: 2026-08-15
invoked_as: chain stage (read-only grader — access: read; report path + VERDICT line specified by caller). Per security-audit skill §5, findings are reported here, not patched. Orchestrator patches.
verdict: findings-open
scanned: semgrep(0 findings / 176 rules / 5 files), gitleaks(0, scoped file + full-history rescan), uv-audit(0 CVEs / 84 packages)
manual_checklist: 7/7 completed
tools_available: semgrep 1.139.0, gitleaks v8.30.1 — both present, both ran (no `not_verified` gaps on the scanner layer)

## Scope
`app/app.py`, `app/api/app_factory.py` (`/ui/shared/<filename>`), `app/core/backend/backend.py`
(chrome + static routes), `app/api/middleware/session_security.py`,
`app/ui/templates/session_expired.html` — per `.agents/specs/shell.md` AC1-AC12.

## Findings

### F1 [fix] `app/api/app_factory.py:59` — hardcoded Flask `SECRET_KEY` fallback is live in every environment, including production
```python
app.secret_key = config.get("app", "secret_key", fallback="dev-secret-key-change-in-production")
```
`app/config/prod.ini`, `local.ini`, and `test.ini` all lack a `[app] secret_key` entry, and no
`SECRET_KEY` env var is wired anywhere in `Dockerfile.multi`, `.gitlab-ci.yml`, or any
docker-compose file (only PostHog's unrelated `SECRET_KEY` appears, for the observability
stack). Confirmed empirically against the running local config:
```
app.secret_key == 'dev-secret-key-change-in-production'
```
This is the literal fallback string — nothing overrides it. Since `prod.ini` has the same gap,
production is exposed to the same default unless something outside this repo injects it (no
evidence found either way; flagging as unconfirmed-safe, not assuming production is fine).

Impact: this key signs **every** session cookie and CSRF token app-wide (Flask's session cookie
is signed, not encrypted — its contents, including the raw CSRF value, are also readable by
whoever holds the cookie). Anyone who knows this fallback string (public in this source tree, or
guessable as a well-known Flask-tutorial idiom even without repo access) can:
- forge a session cookie asserting any `user_id`, defeating `@requires_auth` and tenant_context
  wholesale (full session-forgery-based auth bypass, not scoped to shell)
- forge a matching CSRF token, defeating Flask-WTF's `CSRFProtect(app)` entirely (this is what
  makes F2 below exploitable by a cold, unauthenticated attacker — see PoC there)
- per the existing accepted-risk note in `.agents/reports/crm/review.md` §4, decrypt every
  tenant's stored Xero OAuth tokens, since `XeroOAuthService._fernet()` derives its key as
  `SHA256(app.secret_key)` with no per-tenant salt (`app/features/crm/services/xero_oauth_service.py:47`)

Note: that CRM finding was accepted-risk under a narrower framing ("*if* the key leaks"). This
finding is different and worse: the key isn't a secret that could leak, it's a hardcoded default
that is *already* unconditionally in effect, because nothing in this repo supplies a real one.
The user's prior accepted-risk call on the CRM framing should not be read as covering this.

repro/evidence: `app/config/prod.ini` `[app]` section (no `secret_key` key);
`grep -rn "SECRET_KEY\|secret_key" .gitlab-ci.yml Dockerfile.multi docker-compose*.yml` → no
Flask-app hits; live `app.secret_key` value printed above from `app/app.py`'s own `create_app()`.
patch: not applied (chain-stage read-only). Recommend: fail loudly outside local/test if
`secret_key` is unset (mirror the existing pattern at `app_factory.py:390-395`, which already
does exactly this for a missing Flask-WTF install), provision a real per-environment secret via
KeePassXC/env (matching this repo's existing secrets pattern), and re-encrypt existing Xero
tokens once a real key is live. This is app-wide blast radius, not shell-scoped — routing this
as **escalate** (architectural/session-design class) per the skill's remediation table, not a
shell-local patch.
rule_added: none (read-only chain stage; recommend a `learned.yml` rule flagging
`config.get(..., "secret_key", fallback=...)` with a non-empty string literal fallback)
history: recorded `confirmed`, sig `9de11bd0dda7`

### F2 [fix] `app/app.py:159-167` (spec AC11) — `POST /initialize` is genuinely exploitable by an unauthenticated, cold attacker — CONFIRMED, not a false alarm
```python
@app.route("/initialize", methods=["POST"])
def initialize():
    LOGGER.info("initialize_route_accessed")
    try:
        initialize_database()
        return redirect(url_for("index"))
    except Exception as e:
        LOGGER.exception("initialize_route_failed", error=str(e))
        return f"Database initialization failed: {str(e)}", 500
```
No `@requires_auth`, no environment gate, no rate limit (no `@limiter.exempt` needed because the
shared `Limiter()` instance has no `default_limits` configured at all — confirmed in
`app/api/routes/auth_routes.py:132` — so nothing throttles repeated calls to this route or any
other undecorated one). Registered directly on `app.app:app`, which `tests/e2e/conftest.py`
confirms is the production shape (not a bare `create_app()`).

**Tenant-context middleware does not block it either**: `app/api/middleware/tenant_context.py`
returns early (line 76-78) for any request with no `session["user_id"]` at all — i.e. a fully
anonymous request skips tenant-context loading entirely and reaches the undecorated view.

**Task asked me to confirm whether some other layer (network policy, reverse proxy) already
gates this — I found none.** No nginx/ingress/WAF-rule config exists in this repo; the only
network-layer reference found is `cursor_instructions/auth-account-polish.md:3`
("production-bound behind Cloudflare WAF"), which is a generic DDoS/WAF layer with no
route-specific rule visible anywhere in-repo. `Dockerfile.multi`'s production stage just execs
`uv run workflow start` and exposes the port — nothing scopes `/initialize` to an internal-only
caller. Per the spec's own instruction, absence of such a gate in code means the fix is to
express it in code, not assume it.

**I also checked whether Flask-WTF's global `CSRFProtect(app)` (not exempted for this endpoint —
only `auth.*` and the two telemetry-ingest endpoints are exempt, `app_factory.py:387-389`)
already closes this off, since a raw cookie-less `POST /initialize` does get a 400 "CSRF token is
missing" today.** It does not, because of F1. End-to-end PoC (Flask test client, monkeypatched
`initialize_database` to a no-op so no real DDL/subprocess ran — no destructive action taken):

1. Cold, zero-prior-request attacker signs their own session cookie and `X-CSRFToken` value
   using the known fallback `SECRET_KEY` (`itsdangerous.URLSafeTimedSerializer`, matching
   Flask-WTF's own `generate_csrf`/`validate_csrf` scheme, salt `"wtf-csrf-token"`).
2. Sets a `Referer` header matching the target host (defeats Flask-WTF's `ssl_strict`
   same-origin-referrer check — this header is attacker-controlled on a direct API call, not
   browser-enforced).
3. `POST /initialize` with the forged cookie + `X-CSRFToken` + `Referer` →
   **`initialize_database()` executes** (`initialize_database called: True` in the PoC output),
   route returns `302` to `/`.

This proves the CSRF gate is not a meaningful barrier for a direct (non-browser-mediated)
attacker armed with F1 — and even independent of F1, CSRF tokens were never designed to
substitute for authentication against a first-party attacker who can complete a two-request
token fetch, which this route's own ecosystem doesn't even require here.

On the DDL itself (`app/initialize.py`): confirmed additive-only — `grep -n "DROP\|TRUNCATE\|DELETE FROM" app/initialize.py` returns nothing; every operation is `CREATE TABLE IF NOT EXISTS` or `ALTER TABLE ADD COLUMN`, and table/column names are hardcoded literals in `initialize.py`, not derived from the request (no request body is read at all), so this is not additionally a SQL-injection vector. The exposure is: (a) unauthenticated trigger of schema-mutating subprocess execution against the live DB, unthrottled (DoS-adjacent: unlimited concurrent `subprocess.run` + DB-connection spawns), and (b) `str(exception)` leaked verbatim in the 500 body on failure (internals disclosure — stack detail, DB error text, etc., to an anonymous caller).

repro/evidence: PoC script run against local config (same fallback secret as prod.ini); see F1
for the exact forgery mechanics reused here.
patch: not applied (chain-stage read-only).
rule_added: none (read-only chain stage)
history: recorded `confirmed`, sig `74dc0513095b` (missing-auth) and sig `a40a3d8442ef`
(verbose-error-in-response)

Route recommendation for the caller: **fix-bug, flagged as security**, per the skill's routing
table (auth bypass / data-mutation class needs a red-then-green repro test first) — this one is
shell-scoped and small: add `@requires_auth` at minimum (spec flags this as a FINDING, not a
confirmed intentional AC, so don't assume ops-only intent without a code-level gate), and stop
interpolating `str(e)` into the response body (log it, return a generic message). F1 must also be
fixed or this route's exposure persists via CSRF forgery even with a network-layer fix layered on
top later.

### F3 [fix] `.semgrep/rules/python-multitenant.yml:26-28` — the repo's own `route-missing-requires-auth` rule blanket-excludes `**/app.py`, which is exactly why the scanner reported 0 findings on the real AC11 gap
```yaml
paths:
  exclude:
    - "**/auth_routes.py"
    - "**/app.py"
```
This exclusion appears intended to avoid false positives on `app.py`'s legitimately-public routes
(`/`, `/landing-diagram`, `/healthcheck`), but it's file-scoped rather than route-scoped, so it
also silently exempts `/initialize` — the one route in that file that actually needed the check.
This is the textbook case the skill's §3 compounding step exists for: a manual-pass finding whose
pattern (missing `@requires_auth` on a mutating route) is exactly what an existing rule already
checks for elsewhere, just blinded here by an overbroad path exclude.

repro/evidence: scoped semgrep run (`.agents/reports/shell/semgrep.json`) → 0 results against
`app/app.py`; rule confirmed present and otherwise well-formed by reading
`.semgrep/rules/python-multitenant.yml:18-62`.
patch: not applied (chain-stage read-only; also outside the `app/`, `tests/`, `scripts/`
write-restriction, but still deferred to the orchestrator to keep this stage's only write to the
report file, and because `.semgrep/rules/learned.yml`'s fixture-proof workflow — §3 — needs the
scaffold/verify tooling run, not a hand edit).
recommendation: narrow the exclude to the specific public routes (e.g. a `pattern-not-inside`
for `index`/`landing_diagram`/`healthcheck`, or split `app.py`'s intentionally-public routes into
their own small module the rule can path-exclude precisely) so `/initialize`-shaped gaps are
caught by machine next time, per the skill's whole compounding premise.
rule_added: n/a — this finding *is* about an existing rule; fixing it is editing
`python-multitenant.yml`, not adding to `learned.yml`. Recommend the orchestrator treat this as
part of F2's fix-bug remediation (same PR should adjust the rule so CI proves the class stays
caught), not a separate MR.
history: recorded `confirmed`, sig `0cd9783acff4`

## Attempted but clean

- **AC1-AC4** (`/core`, `/core/dashboard`, `/core/integrations`, `/core/settings`): read
  `app/core/backend/backend.py:633-657` directly. All four carry `@requires_auth`. `show_reset_db`
  is `config.environment in ("test", "local") and user_email == DEMO_USER_EMAIL` exactly as
  specced — cannot render for a real tenant or in production regardless of misconfiguration,
  since both conditions must hold. `/core/integrations` unconditionally redirects, no data path.
- **AC5-AC6** (`/static/js`, `/static/css`, `/static/inventory`, `/static/img`): read all four
  handlers in `backend.py:1087-1243`. Traversal rejection (`..`, `/`, `\\`) precedes every other
  check; `/static/js`/`/static/css` use an extension whitelist, `/static/inventory`/`/static/img`
  use the specced hardcoded filename allowlists (`_INVENTORY_STATIC_ALLOWLIST`,
  `_IMG_STATIC_ALLOWLIST`) rather than extension-only checks, matching AC6's stricter
  requirement; `safe_join` validates before every `send_from_directory` call (never a raw path
  join); `FileNotFoundError` → 404, bare `Exception` → generic 500 with no exception text in any
  of the four handlers (no `str(e)` anywhere in these four).
- **AC7** (`/ui/shared/<filename>`): read `app/api/app_factory.py:120-176`. Uses
  `<path:filename>` (a converter that would otherwise permit `/`), but the explicit
  `"/" in filename` check runs before any file access and rejects regardless — confirmed this
  isn't bypassable via `%2F` since Flask decodes the path segment before the check runs. 401
  gate for non-allowlisted files with no `g.current_user` runs before the traversal check
  (doesn't leak file-existence info via a different status code). `PUBLIC_UI_SHARED_FILES` is a
  tight one-item allowlist (`password-policy.js`) with a documented reason in the surrounding
  comment.
- **AC8-AC9** (`/`, `/landing-diagram`): both use `send_from_directory` on a static `.html` file
  with no Jinja rendering — confirmed no `render_template_string`/`render_template` call
  anywhere in either handler (`app/app.py:66-95`), matching the spec's note that this was
  deliberately moved off `render_template_string` for a prior SSTI finding.
- **AC10** (`/dashboard` alias): `@requires_auth` present (`app/app.py:98-99`), redirects
  unconditionally to `/core/dashboard`, no data path.
- **AC12** (session-expiry render): read `app/api/middleware/session_security.py:99-106` and the
  full `session_expired.html` template. `render_template_string(template_content)` is called
  with **zero** variables/kwargs passed — Jinja has nothing to substitute even if it wanted to.
  Read the entire template: no `{{ }}` / `{% %}` syntax present anywhere, static HTML/CSS/JS only.
  Confirmed no reachable user-controlled content: the template path is a hardcoded disk path, not
  request-derived, and the function that reads+renders it takes no request data.
- **Mass assignment**: no route in scope reads `request.json`/`request.form` into a model at all
  (`/initialize` takes no request body; the chrome routes render templates with no write path).
- **Injection**: `app/initialize.py`'s DDL uses hardcoded table/column literals, not
  request-derived data (see F2) — confirmed not a second injection vector beyond the auth gap.
- **SSRF/uploads**: no upload or outbound-URL-fetch code in this slice's scope.
- **Secrets in this slice's own code**: gitleaks scoped scan and a full-history rescan (1064
  commits) both returned 0 leaks. (F1 is a *design* flaw — a hardcoded fallback value used as a
  cryptographic key — not a leaked secret in the gitleaks sense, so it doesn't show up there; it
  was found by the manual pass.)
- **CORS**: no `Access-Control-Allow-Origin` handling anywhere in the scoped files; nothing sets
  a permissive CORS policy for this slice.
- **uv audit**: 0 vulnerabilities across 84 audited packages.

## Dead files (spec's "Known dead files" section)
Not re-verified independently beyond the spec's own grep-confirmed claims — no security
implication either way for `sidebar-v2.html` / `components/sidebar.html` (genuinely unreachable).
`sidebar.js`/`sidebar.css` are live HTTP surface per the spec but contain no auth/data logic per
a quick read; not treated as a security finding, just noted as already-flagged dead weight.

## Not verified
- Whether production's actual deployment (outside this repo — Cloudflare config, any
  internal-only network policy Codex/orchestrator has access to that this repo doesn't reflect)
  supplies a real `SECRET_KEY` or blocks `/initialize` by other means. I checked every
  in-repo signal (Dockerfile, CI, compose files, ini files) and found none; I cannot see outside
  the repo, so F1/F2 are reported as confirmed against what the code allows, with an explicit
  note that an out-of-band production override — if one exists — would change F1's severity (not
  F2's: even with a real secret, F2's missing `@requires_auth` remains a code-level gap that
  should be fixed on its own, and unlimited unauthenticated DoS-shaped requests would still not be
  blocked by CSRF's referrer check alone since that only requires a same-origin `Referer` header,
  which is not a meaningful attacker deterrent even without F1).
- Live-server E2E behavior (no app server was running per preflight `verification_mode` /
  `live_server_tests: skip`) — all findings above are confirmed via static code read plus an
  in-process Flask test-client PoC (F1/F2), not a live HTTP request against a running deployment.
