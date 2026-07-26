# E2E Playwright — dilution_calculator

Ground truth: driven against the already-running dev server at `https://localhost:8005`
for this worktree/branch (`E2E_BASE_URL=https://localhost:8005`, `ENVIRONMENT` unset), not
a fresh in-process boot — confirmed up before writing anything
(`curl -sk https://localhost:8005/` -> `200`). No server was started by this run.

Suite: `tests/e2e/test_dilution_calculator_flow.py` (6 tests). Coverage gate
(`scripts/e2e_coverage.py`) confirms both `GET /dilution-calculator` and
`POST /api/dilution-calculator/solve` — previously in the gap list — are now covered.

## AC -> test map

| AC | Test | Result |
|----|------|--------|
| AC6 (unauthenticated GET redirects) | `test_dilution_calculator_page_requires_auth` | PASS |
| AC6 (authenticated GET renders) | `test_dilution_calculator_page_renders_for_authenticated_user` | PASS |
| AC1 (API auth-gated) | `test_dilution_calculator_api_requires_auth` | PASS |
| AC1/AC2 (real browser walkthrough, worked example) | `test_solve_final_volume_matches_worked_example` | PASS |
| AC1/AC2 (independent API-level confirmation of the same numbers) | `test_solve_final_volume_via_api_matches_ui_result` | PASS |
| AC5 (validation error rendered in UI, not silent) | `test_invalid_direction_shows_error_in_ui_not_silent_failure` | PASS |

Flake check: ran 3/3 — all green, no intermittent failures.

## A real bug found and fixed (not a test bug)

The first run of the AC1/AC2 walkthrough and the AC5 validation-error test both failed:
after clicking "Calculate", neither the result card nor the error banner ever became
visible, despite the network tab showing the `POST /api/dilution-calculator/solve` request
completing with `200`.

Root cause, confirmed by tracing requests/responses and a manual `curl`: `base_spa.html`
sets `hx-boost="true"` on `<body>` (line 60), which htmx applies to every descendant
`<form>` and `<a>` by default unless explicitly opted out (the existing notifications link
already does this with `hx-boost="false"` at line 99). The dilution calculator's
`<form @submit.prevent="submit()">` never opted out, so htmx also intercepted the submit
event, fired its own boosted `XHR GET` back to `/dilution-calculator`, and swapped
`#page-content` — destroying the Alpine component's `result`/`error` state right as (or
just after) the real fetch resolved. The result: the app silently ate its own successful
calculation and its own validation errors in a real browser, even though the API and unit
layers were correct.

Fix: added `hx-boost="false"` to the form in
`app/features/dilution_calculator/frontend/templates/dilution_calculator/index.html`,
matching the existing opt-out pattern. Verified via a throwaway debug script (introspecting
Alpine state and network events, since discussed) that the double-navigation stopped and
`result`/`error` render correctly; then confirmed via the actual test suite (re-run 3/3
green). Also spot-checked `tests/e2e/test_pages_render.py` and `tests/e2e/test_smoke.py`
(24 tests) still pass after the template change — no regression to the shared
`base_spa.html` htmx/Alpine wiring.

## A second, smaller finding: AC1's "requires auth" is CSRF-first, not auth-first

`test_dilution_calculator_api_requires_auth` initially asserted a bare `401` for an
unauthenticated POST and got `400` instead. Confirmed directly with `curl` (no cookies, no
CSRF token) against the running server: `400 Bad Request — "The CSRF token is missing."`.
Flask-WTF's global CSRF check runs ahead of `@requires_auth` for this route (only `/auth/*`
is CSRF-exempt per `tests/e2e/conftest.py`'s `csrf_headers` docstring), so a token-less POST
never reaches the auth check at all. This is correct, defense-in-depth behavior, not a bug
— the test was asserting a status code this code path can never actually produce. Rewrote
the assertion to the honest, still-meaningful claim: an unauthenticated/token-less caller
never gets `200` and never gets a `solved_value` back (`status in (400, 401)` and
`"solved_value" not in body`), mirroring the same defensive style
`test_crm_customers_api_requires_auth` already uses for the equivalent CRM check.

## Scope notes

- No cross-tenant probe: the spec states `tenant_scoped: no` — the feature "touches no
  org_id-scoped table" and creates no rows, so there is no tenant-scoped object to probe
  a second org against. The skill's cross-tenant mandate doesn't have a target here; noting
  the reason rather than silently omitting it.
- AC3 (round-trip), AC4 (field-level validation matrix), AC7 (determinism/statelessness),
  and AC9 (full-precision, no server-side rounding) are exact-arithmetic/API-shape
  properties already suited to unit/integration tests, not browser interaction — out of
  this stage's scope per the task brief, not silently skipped.

## Files touched

- `/home/johnny/workflow-engine-dilution_calculator/tests/e2e/test_dilution_calculator_flow.py` (new)
- `/home/johnny/workflow-engine-dilution_calculator/app/features/dilution_calculator/frontend/templates/dilution_calculator/index.html` (bug fix: `hx-boost="false"` on the form, plus `role="alert"` and `data-testid` hooks added for accessible/stable E2E selectors — the result card had neither a role nor a testid before)

VERDICT: patched
