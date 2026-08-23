# SECURITY: demo-data
date: 2026-08-23
mode: chain-stage (read-only grader — findings reported, not patched)
verdict: findings-open (F1 severity revised downward post-audit — see "Empirical
  correction" section: a platform defense-in-depth layer already blocks the exploit in
  practice; still worth patching for legibility/resilience, not as a live bypass)
scanned: semgrep(0 findings, scoped to app/features/demo_data/), gitleaks(65 findings repo-wide, 0 in scope), uv-audit(0 vulnerabilities)
manual_checklist: 7/7 completed

## Findings

- F1 [fix] `app/features/demo_data/routes/api_routes.py:22-29` — cross-tenant destructive
  action, no caller-identity/org check.
  repro/evidence: `reset_demo_db_route` is decorated only with `@requires_auth`
  (`api_routes.py:23`). The only gate is `config.environment not in ("test", "local")`
  (`api_routes.py:26`), which restricts *which environment* the route is reachable in,
  not *who* may call it. `reset_demo_db()` (`services/resetdb.py:67-75`) resolves its
  target `org_id` solely from `UserRepository.get_user_by_email(DEMO_USER_EMAIL)` —
  never from `g.current_org_id` or `g.current_user` at all. So in any environment where
  the route is reachable, **any authenticated user of any org** can POST to
  `/api/core/reset-demo-db` and have all of the demo org's `Process`, `Step`,
  `Execution`, `ExecutionStep`, and `InventoryItem` rows deleted and replaced —
  regardless of whether the caller belongs to, or is, that org. This confirms the gap
  the reconstructed spec flags (`.agents/specs/demo-data.md` "Known gaps"). Verified
  against the repo's own cross-cutting invariant #1 ("every query filters on `org_id`"):
  every query inside `reset_demo_db`/`clear_demo_db` *is* correctly filtered by
  `org_id` — but that `org_id` is a fixed constant looked up by email, never derived
  from or checked against the caller's identity. The invariant is satisfied at the
  query layer and violated at the authorization layer: this is a missing-authorization
  bug (CWE-862 / broken access control on a destructive action), not a missing-filter
  bug. `@requires_org_scope` would not fix it even if added — that decorator only
  checks `g.current_org_id` is *set* (`permissions.py:42-52`), not that it matches the
  resource being mutated — the actual fix needs an explicit identity/role check (e.g.
  caller's org must equal the demo org's `org_id`, or a staff-only role gate).
  severity: environment-gated (unreachable in production per `api_routes.py:26`), but
  within `test`/`local` it is a full authorization bypass on a destructive,
  irreversible write with no rate limiting. Real-world exposure depends on deployment
  topology this audit could not verify from code alone — see `not_verified` below.
  patch: not applied (chain-stage, read-only). Recommend routing to `fix-bug` (flagged
  security) per the skill's routing table — needs a red-then-green repro test: "user in
  org A hits reset-demo-db, org B's (demo org) data is wiped" must fail before it
  passes. Candidate fix: compare `g.current_user.org_id` (or a dedicated
  `is_demo_admin`/staff-role check) against the demo user's `org_id` before proceeding,
  returning 403 on mismatch.
  rule_added: none — this is a single-instance, feature-specific authorization gap
  (fixed org target divorced from caller identity), not a mechanically-generalizable
  pattern across the codebase. A semgrep rule matching "route with `@requires_auth`
  only, no org check" would false-positive heavily on the app's other legitimately
  auth-only routes (e.g. `/auth/*`, user-profile-only endpoints). Not scaffolded.
  history: recorded `confirmed` (sig `29d57f523c88`) — first observation, no prior
  verdict existed.

- F2 [accepted-risk candidate] `app/features/demo_data/routes/api_routes.py:44` — raw
  exception string returned in 500 response body.
  repro/evidence: `except Exception as e: ... return jsonify({"success": False,
  "message": str(e), "error": "RESET_FAILED"}), 500`. Any exception raised inside
  `reset_demo_db` (DB constraint violation, driver error, etc.) has its `str()`
  returned verbatim to the caller — could include table/column names, constraint
  identifiers, or fragments of query state. This confirms AC5 / the spec's "Known
  gaps" item.
  severity: low. Scoped to non-production (same environment gate as F1) and requires
  authentication (not exploitable pre-auth). The realistic worst case is an internal
  schema/constraint detail leaking to an already-authenticated user in a dev/test
  environment — not a credential or PII leak. Distinct from F1: this doesn't need a
  repro test to prove exploitability, it's a straightforward info-disclosure pattern.
  patch: not applied (chain-stage, read-only). Recommend: log `str(e)` server-side
  (already done via `logger.exception` at line 43) and return a generic message in the
  response body, e.g. `{"error": "RESET_FAILED", "message": "Demo reset failed, see
  server logs"}`. Small enough to fix inline wherever F1 gets fixed rather than a
  separate MR.
  rule_added: none — candidate pattern (`str(e)` interpolated directly into a
  `jsonify(...)` error body) is mechanically detectable and *would* generalize across
  the app, but scaffolding a fixture pair and verifying it was out of scope for a
  read-only audit stage authoring only its report file. Flagging for whoever picks up
  F2 to scaffold via `scripts/rule_candidates.py` (`bize-raw-exception-in-response` or
  similar) as part of that fix.
  history: recorded `confirmed` (sig `674ec59db2d3`) — first observation.

## Attempted but clean

- **Mass assignment**: route takes no request body at all (`POST` with no `request.json`
  read anywhere in `api_routes.py` or `resetdb.py`) — nothing to assign from. Clean.
- **Injection**: every DB access in both files goes through SQLAlchemy ORM
  query/filter calls or repository methods (`ProcessRepository`, `InventoryRepository`,
  `ExecutionRepository`, `UserRepository`) — no raw SQL, no string-built queries,
  no `subprocess`/`shell=True`, no user-controlled file paths. Clean.
- **SSRF / uploads**: slice has no URL inputs or file uploads. N/A.
- **Secrets in this slice**: gitleaks found 65 leaks repo-wide (git history scan,
  1095 commits) but zero of them are under `app/features/demo_data/` — all are in
  `app.py`/`app.py.bak`/`app.py.xero_processing_updates_in_progress`, `ci/scripts/*`,
  `config/prod.ini`, prior audit report JSON files, and skill/rule docs. Pre-existing,
  already tracked outside this slice's scope (cf. the committed-origin-key writeup at
  `.agents/reports/security-audit/2026-07-17-committed-origin-key.md` for the pattern
  of how those get triaged) — not re-litigated here since none touch the audited code.
- **CSRF**: `reset-demo-db` is a state-changing `POST` and is *not* in the CSRF-exempt
  set built in `app/api/app_factory.py:432-434` (which only exempts `auth.*` endpoints
  and the two telemetry ingest routes). It is covered by the app-wide
  `CSRFProtect(app)` (`app_factory.py:428`). Clean.
- **CORS**: no CORS configuration specific to this route found; no `*`-with-credentials
  pattern in this slice. Clean.
- **Tenant isolation of the queries themselves**: every delete/create query in
  `clear_demo_db`/`reset_demo_db` filters by `org_id` (derived once from the demo
  user, then threaded through consistently) — no bare-`id` lookups, no cross-org leak
  *within* the operation. The gap is entirely at the authorization boundary (F1), not
  in query construction.
- **Auth presence**: the slice's one route carries `@requires_auth`; no bare/unguarded
  route exists in this blueprint. `clear_demo_db` has no route at all (grepped
  `app/**/*.py` for `clear_demo_db` — only its own definition and the three test files
  named in the spec call it, all as direct Python imports, never through HTTP).
- **Dependency CVEs**: `uv audit --frozen` — 84 packages audited, 0 vulnerabilities,
  0 adverse statuses.
- **Semgrep (p/python, p/flask, p/owasp-top-ten, .semgrep/)**: 0 findings across both
  files in the slice (174 rules, 100% parse coverage).

## Empirical correction (added by review-feature, post-audit — e2e-playwright stage)

**F1's severity is materially lower than assessed above.** This audit was read-only
(code analysis only, no running app to test against) and reasoned entirely from
`api_routes.py`/`resetdb.py`. It missed a platform-level defense-in-depth layer:
`app/core/db/tenant_filter.py` registers a global SQLAlchemy `do_orm_execute` event
that auto-injects `with_loader_criteria(TenantScoped, org_id == get_current_org_id())`
onto **every** ORM SELECT/UPDATE/DELETE, where `get_current_org_id()` is the
*authenticated caller's* org (set by the tenant-context middleware,
`app/api/middleware/tenant_context.py`, before any route body runs). `User` extends
`TenantScoped` (`app/core/db/models/user.py:22`).

Running the actual cross-tenant e2e probe (`tests/e2e/demo-data/test_reset_demo_db.py
::test_cross_tenant_reset_is_rejected`) against the live app confirms this in practice:
a caller from a different org gets **400 `USER_NOT_FOUND`**, not a successful reset.
`reset_demo_db()`'s own `user_repo.get_user_by_email(DEMO_USER_EMAIL)` call — the very
first thing it does — is silently rescoped by the global filter to `org_id ==
<caller's org>`, so it can never find a user belonging to a *different* org. The route
returns its "demo user not found" error and exits before any delete/create runs. This
is real, reproduced twice, not a fluke of test data.

So: **F1 as originally described ("any authenticated user of any org can wipe the demo
org's data") does not currently work** — the platform's own tenant isolation layer
blocks it, independent of anything `demo_data` does or doesn't check itself.

This does **not** make F1 a non-finding. `tenant_filter.py`'s own docstring is explicit
that it is "purely additive defense-in-depth," not a substitute for each route's own
authorization logic — and the accidental protection here is fragile and misleading:
- The caller sees `USER_NOT_FOUND`, which reads as "the system is broken / the demo
  user got deleted," not "you are not authorized." No `access_denied` log is emitted
  (this app's own convention for a real authorization rejection, e.g.
  `permissions.py:61`) — an operator watching for auth rejections would see nothing.
  A real regression here (e.g. someone reworks `get_user_by_email` to use `.get()`,
  which `tenant_filter.py`'s own "Known residual gap" section says bypasses the filter
  entirely) would silently reopen the hole with no test currently distinguishing
  "blocked by design" from "blocked by accident."
- Nothing in `demo_data` states or tests this dependency; a reader of `api_routes.py`
  alone (as this audit was) reasonably concludes the route is wide open.

Revised recommendation: still add the explicit check (F1's original patch
recommendation), but the driving reason shifts from "closes a live cross-tenant wipe"
to "replaces silent, undocumented, accidental protection with an intentional,
logged, correctly-coded (403 + `access_denied`) one" — the security posture doesn't
change, but its legibility and resilience to future refactors does. Not escalating
severity; downgrading urgency from "live authorization bypass" to "defense-in-depth
hygiene," consistent with how `.agents/reports/demo-data/e2e-playwright.md` frames it.

## not_verified

- Whether any `test`/`local` deployment of this app is ever shared/networked with
  multiple real tenant orgs present (as opposed to a single-developer local DB or an
  isolated CI test DB per the `docker-compose.test.yml` setup CLAUDE.md describes).
  F1's severity in practice depends on this — if `test`/`local` environments are
  always single-tenant or ephemeral, actual blast radius is near-zero; if any shared
  staging environment exists with `ENVIRONMENT=test` and multiple real org accounts,
  F1 is directly exploitable by any of their users today. Could not determine from
  code or config alone; flagging for the human routing decision alongside F1.
- Rate limiting on `/api/core/reset-demo-db` specifically — did not find a
  `@limiter`-related decorator on this route (unlike some routes in
  `app/core/backend/backend.py`), meaning F1, once triggered, could be triggered
  repeatedly with no throttle. Secondary to F1 itself; not filed as its own finding
  since the primary bug is the missing authorization check, not the lack of a rate
  limit on an otherwise-authorized action.
