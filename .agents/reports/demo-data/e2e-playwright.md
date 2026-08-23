# E2E: demo-data
date: 2026-08-23
mode: chain-stage (gap-fill — no tests/e2e/demo-data/ existed before this review)
verdict: findings-open (pre-patch: 1 of 3 tests correctly red — see below)

## Coverage gap identified
`python3 scripts/e2e_coverage.py --json` — `/api/core/reset-demo-db` (POST) had zero
E2E coverage. New suite: `tests/e2e/demo-data/{conftest.py,test_reset_demo_db.py}`.

## AC → test → result

| AC | Test | Result (pre-patch) |
|---|---|---|
| AC1 (auth required) | `test_ac1_unauthenticated_reset_is_rejected` | PASS (3/3 flake-check) |
| AC3 (successful reset shape) | `test_ac3_demo_org_member_can_reset_and_reseed` | PASS (3/3 flake-check) |
| mandatory cross-tenant probe | `test_cross_tenant_reset_is_rejected` | **FAIL by design** — see below |

## AC1 correction (spec was wrong, not the code)
Original reconstructed spec said "unauthenticated POST returns 401." Actual observed
behavior: **400** ("CSRF token is missing"). Flask-WTF's `CSRFProtect` runs as a global
`before_request` hook that fires before any route's `@requires_auth` check — true for
every state-changing route in the app, not specific to demo-data — and only the
authenticated SPA shell (`base_spa.html`) embeds a `csrf-token` meta tag, so there is no
public page an anonymous visitor can use to obtain one. A clean 401-before-CSRF path is
not reachable over real HTTP for this route. Updated `.agents/specs/demo-data.md` AC1
and the test to match reality rather than force a status code that never occurs.

## Cross-tenant probe: important correction to security-audit's F1
The probe currently fails — **not** because the exploit security-audit described
actually works, but because the real, current status code is 400 (`USER_NOT_FOUND`),
not the 403 the test asserts as the target/secure behavior. Running this test against
the live app surfaced a platform-level defense-in-depth layer
(`app/core/db/tenant_filter.py`) that security-audit's read-only/code-only analysis
missed: a global SQLAlchemy filter auto-scopes every ORM query to the caller's own
`org_id`, and `User` is a `TenantScoped` model — so `reset_demo_db()`'s own
`get_user_by_email(DEMO_USER_EMAIL)` lookup silently can't find the demo user for an
outsider caller, and the route exits before any write. **The demo org's data is not
actually wiped by a cross-org caller today.** Full writeup and revised severity appended
to `.agents/reports/demo-data/security-audit.md` ("Empirical correction" section).

The test is left asserting 403 (the correct, intentional target behavior — clear
rejection + `access_denied` logging) rather than being weakened to accept the
accidental 400, per this skill's "tests are ground truth" rule: today's protection is
real but fragile (relies on a side effect neither `demo_data` nor its tests document),
and 400 `USER_NOT_FOUND` is a misleading signal to log/monitor on. This test should go
green once the explicit check security-audit recommended is patched in.

## ACs not covered here (documented, not a gap)
- AC2 (environment gate, 403 outside test/local): not exercisable via this suite — the
  e2e app fixture (`tests/e2e/conftest.py::app_url`) always boots with `ENVIRONMENT`
  unset (`local`), which is required for E2E to run at all (see that fixture's own
  docstring on why `ENVIRONMENT=test` hangs from a host shell). Testing the production
  branch of the `if config.environment not in (...)` check would need a second app
  boot under a different config, out of scope for this suite. Covered at the unit level
  instead (the `if` is a single, trivially-unit-testable line).
- AC4 (demo user missing): not exercisable without deleting `demo@whistlebird.co.nz`
  from the shared test DB mid-suite, which would break every other suite that depends
  on that row existing (`test_corechecks`, `test_executions`, `test_dag_traversal`).
  Left to unit tests with an isolated fixture instead.
- AC5 (raw exception in 500 body): not forced here; triggering a genuine internal
  exception deterministically over HTTP without mocking would be brittle. Covered by
  security-audit's F2 code-level finding instead.

## Flake check
AC1 and AC3: 3/3 stable. Cross-tenant probe: deliberately red pre-patch, re-run
required after Step 4 patches land (see review.md).

## Handoff
Once F1 is patched (Step 4), re-run this suite; expect all 3 green, then flake-check
the cross-tenant probe 3/3 same as the other two. Hand the suite to ci-gate afterward
so it becomes a required check.
