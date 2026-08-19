# SPEC: shell
status: reviewed
name: Application Shell (sidebar, nav, static assets, landing, settings/integrations chrome)
slug: shell
blueprint: app/core/backend/backend.py (chrome routes only, attached to core_bp),
  app/api/app_factory.py (`/ui/shared/<filename>`), app/app.py (`/`, `/landing-diagram`,
  `/dashboard` alias, `/healthcheck`, `/initialize`) — no dedicated blueprint object; this
  slice is the routes and templates every other page-rendering slice sits inside, not a
  standalone feature
url_prefix: n/a (spread across `/`, `/core/*`, `/static/*`, `/ui/shared/*`)

## Description
The chrome every authenticated page renders inside: the sidebar/nav (`base_spa.html` +
`shared/sidebar-v2.html`, included by every core/CRM page template), the hub/settings/
integrations pages, and the static-asset serving routes those pages depend on (core JS/CSS,
inventory partial assets, images, and the cross-slice `/ui/shared/` JS/CSS bundle). Also
owns the logged-out surface: the landing page, the embedded landing diagram, and the
session-expired flow that fires when an authenticated session times out mid-page. Carries
no models, no repositories, and (with one exception noted below) no `org_id`-scoped reads
or writes of its own — it is presentation plumbing that every other slice's UI depends on.

`app/app.py` additionally registers three routes that sit outside `create_app()`'s
blueprint wiring and are not documented in the feature index's `routes:` block: `/dashboard`
(a `@requires_auth` redirect alias to `/core/dashboard`), `/healthcheck` (public, DB
connectivity probe, no rendering), and `/initialize` (see AC11 — flagged as a finding, not
a confirmed intentional AC). They're included here because `app.py` is otherwise entirely
shell's file (it's where `/` and `/landing-diagram` live) and no other slice claims them.

## Users & permissions
- roles: any authenticated org member for the chrome pages (`/core`, `/core/dashboard`,
  `/core/settings`, `/core/integrations`) — `@requires_auth` only, no elevated role check,
  no `@requires_org_scope` (these routes render a template and read `g.user_email`; they do
  not query `org_id`-scoped tables themselves)
- `/`, `/landing-diagram`, `/healthcheck` are intentionally public (pre-login surface +
  ops probe)
- static-serving routes (`/static/js`, `/static/css`, `/static/inventory`, `/static/img`)
  are intentionally unauthenticated by design (docstrings: "no auth so they load reliably;
  pages that include them are protected") — protected instead by path-traversal rejection
  and an extension/filename allowlist
- `/ui/shared/<filename>` is auth-gated **inside the view** (not via `@requires_auth`,
  so a 401 doesn't get rewritten to a 302 by the global handler and break script loading)
  except for the `PUBLIC_UI_SHARED_FILES` allowlist (`password-policy.js` only)
- tenant_scoped: no — no route in this slice reads or writes an `org_id`-scoped row.
  `show_reset_db` on `/core` compares `g.user_email` to the hardcoded `DEMO_USER_EMAIL`
  and `config.environment`, not tenant data.

## Acceptance criteria

- AC1 (`GET /core`): requires auth. Renders `core/core2.html` with `active_page="core"`.
  `show_reset_db` is `True` only when `config.environment in ("test", "local")` **and**
  the caller's email equals `DEMO_USER_EMAIL` — the reset-DB button must never render for
  a real tenant or in production regardless of environment misconfiguration.
- AC2 (`GET /core/dashboard`): requires auth. Renders `dashboard/dashboard.html` chrome
  with `active_page="dashboard"` — this route serves only the page shell; live dashboard
  data is fetched client-side from the `dashboard` slice's own API (out of scope here).
- AC3 (`GET /core/integrations`): requires auth. Always 302-redirects to
  `/crm/configuration` — there is no standalone integrations page; this is a permanent
  compatibility redirect for the nav link.
- AC4 (`GET /core/settings`): requires auth. Renders `settings/settings.html` with
  `active_page="settings"`.
- AC5 (`GET /static/js/<filename>`, `/static/css/<filename>`): no auth required. Rejects
  `filename` containing `..`, `/`, or `\` with 400. Rejects any extension other than
  `.js`/`.css` respectively with 400. Serves via `send_from_directory` only (never a raw
  path join) from `app/core/frontend/{js,css}/`; missing file is a 404, not a fallthrough
  to Flask's default static handler; unexpected exceptions are a 500, not a stack trace
  leak. Sets an explicit `Content-Type` and a 1hr `Cache-Control` with SWR.
- AC6 (`GET /static/inventory/<filename>`, `/static/img/<filename>`): no auth required.
  Same traversal rejection, plus a **hardcoded filename allowlist**
  (`_INVENTORY_STATIC_ALLOWLIST = {inventory-icon.svg, inventory-spa-header.css}`,
  `_IMG_STATIC_ALLOWLIST = {hero-wave.jpg}`) rather than a general extension whitelist —
  any filename not in the allowlist is a 400 even if the extension would otherwise be
  valid.
- AC7 (`GET /ui/shared/<filename>`): 401 if `filename not in PUBLIC_UI_SHARED_FILES` and
  no authenticated `g.current_user`. Same traversal rejection and `.js`/`.css` extension
  whitelist as AC5. Serves from `app/ui/shared/`.
- AC8 (`GET /`): public, no auth. Serves `app/ui/templates/landing.html` as a static file
  via `send_from_directory` (not `render_template_string` — that was a prior
  server-side-template-injection semgrep finding, fixed; the page contains no Jinja and
  should never be re-routed through the template engine).
- AC9 (`GET /landing-diagram`): public, no auth. Serves `biz-e-diagram-landing.html` the
  same way, embedded via iframe on the landing page.
- AC10 (`GET /dashboard`, app.py alias): requires auth. Always redirects to
  `/core/dashboard`.
- AC11 (`POST /initialize`) — **FINDING, not a confirmed intended AC**: this route carries
  **no `@requires_auth` and no environment gate**. It shells out to `app/initialize.py`
  (`subprocess.run`, additive `CREATE TABLE`/`ALTER TABLE ... ADD COLUMN` schema
  operations against the configured database — no `DROP` found) and returns a redirect to
  `/` on success or a 500 with `str(exception)` in the response body on failure. It is
  registered directly on the production app instance (`tests/e2e/conftest.py` confirms
  `app.app:app`, not a bare `create_app()`, "is the production shape"). It is excluded
  from required e2e coverage (`scripts/e2e_coverage.py: EXCLUDE_EXACT`) as presumed
  ops-only infrastructure, but nothing in the route itself enforces that — any
  unauthenticated caller who can reach the app can trigger a schema-mutating subprocess
  and, on failure, receive an internals-revealing error string. Audit this in the
  security-audit stage; do not assume the current behavior is intentional just because it
  predates this review. ASSUMPTION: treated as in-scope for `shell` because it lives in
  `app.py` (shell's file) and no other slice claims it — if it turns out to be
  intentionally reachable only from a trusted ops path (e.g. an internal deploy
  init-container hitting `localhost` before the app is exposed), the fix is to say so in
  code, not just in this spec.
- AC12 (session-expiry, `session_security.py`): when session inactivity exceeds the
  configured timeout, the session is cleared. If the request `Accept`s `text/html` or is a
  non-API page route, respond 401 with `session_expired.html` rendered via
  `render_template_string` on file content read from disk at request time (note: this is
  the same pattern the `/` route was deliberately moved *away from* for the SSTI finding —
  `session_expired.html` is static chrome with no user-controllable content reaching the
  string, but confirm during security-audit that no future edit to that template
  introduces one). Otherwise (API request) responds JSON `{"error": "Session expired due
  to inactivity"}`, 401.

## Known dead files (cleanup candidates, not ACs)
Confirmed by grep — none of these are referenced by any template `include`/`extends`,
script tag, or stylesheet link anywhere in `app/`:
- `app/ui/shared/sidebar-v2.html` — unreachable two ways over: Jinja
  `{% include 'shared/sidebar-v2.html' %}` in `base_spa.html:67` resolves against the
  **template** search path (`app/ui/templates/shared/sidebar-v2.html`, the real live
  sidebar), not this file under `app/ui/shared/`; and the `/ui/shared/<filename>` HTTP
  route only whitelists `.js`/`.css` extensions, so a direct request for this `.html` file
  400s. Genuinely dead weight, not a live security surface.
- `app/ui/templates/components/sidebar.html` — old sidebar, still links to the retired
  `/workflow-engine/*` nav; no include/extends anywhere.
- `app/ui/shared/sidebar.js`, `app/ui/shared/sidebar.css` — **not previously flagged by
  the feature index.** Superseded by `sidebar-v2.js`/inline styles; unreferenced by any
  template. Unlike the two above, these ARE live HTTP surface (`/ui/shared/sidebar.js`,
  `/ui/shared/sidebar.css` both pass the extension whitelist and would be served if
  requested) — dead code that still executes if fetched directly, not just an orphaned
  file.

## Depends on
platform (`@requires_auth`, session middleware, observability), identity (session/user
identity backing `g.current_user`, `g.user_email`).

## Depended on by
Every page-rendering slice — all of them extend `base_spa.html` (which includes the
sidebar) and pass `active_page` to it; all of them load `/static/js/*`, `/static/css/*`,
and (most) `/ui/shared/*` assets this slice serves.

## Out of scope
- Dashboard *data* (API, metrics) — owned by the `dashboard` slice; this spec covers only
  the `/core/dashboard` chrome route.
- CRM configuration page itself — owned by `crm`; this spec covers only the
  `/core/integrations` redirect that points at it.
- Auth/session mechanics beyond the session-expiry render path (login, 2FA, CSRF) — owned
  by `identity`.
