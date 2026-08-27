# SPEC: demo-data
status: reviewed
name: Demo Data
slug: demo-data
blueprint: app/features/demo_data/
url_prefix: /api/core (mounted on core_bp, not its own prefix)

## Description
A dev/test-only endpoint and service that wipes and reseeds one fixed organisation's
process/execution/inventory data with a distillery-themed demo dataset (malted barley
through bottled whisky). Two consumers: (1) manual product demos via the UI hitting
`POST /api/core/reset-demo-db`, and (2) three test files (`test_corechecks`,
`test_executions`, `test_dag_traversal`) that import `reset_demo_db`/`clear_demo_db`/
`DEMO_USER_EMAIL` directly as fixture infrastructure — this is load-bearing test
plumbing, not just a dev convenience, per the feature index.

## Users & permissions
- Any authenticated user (`@requires_auth` only — no `@requires_org_scope`, no check
  that the caller belongs to, or is, the demo org/user).
- Route self-gates on `config.environment in ("test", "local")`; returns 403 otherwise.
  ASSUMPTION: this is meant to make the route unreachable in `production`, not to scope
  *who* within test/local may call it.

## Acceptance criteria
- AC1: `POST /api/core/reset-demo-db` cannot succeed without an authenticated session.
  CORRECTED (was: "returns 401" — wrong, verified against real behavior by
  e2e-playwright): Flask-WTF's `CSRFProtect` runs as a global `before_request` hook
  that fires before any route's `@requires_auth` check, repo-wide, and only the
  authenticated SPA shell (`base_spa.html`) embeds a `csrf-token` meta tag — there is no
  public page an anonymous visitor can use to obtain one. So a fully anonymous POST
  (no session, no CSRF token) observably returns **400** ("CSRF token is missing"), not
  401; a 401-before-CSRF path is not reachable over real HTTP for this route, and this
  is true of every state-changing route in the app, not specific to demo-data.
- AC2: `POST /api/core/reset-demo-db` when `config.environment == "production"` returns
  403 with `{"success": false, "error": ...}`, regardless of auth. ASSUMPTION: derived
  from the explicit `if config.environment not in ("test", "local")` guard.
- AC3: On success (`environment` is `test` or `local`, demo user exists), returns 200
  with `{"success": true, "message": ...}`, and afterwards, for the org owning
  `demo@whistlebird.co.nz`:
  - all pre-existing `Process`, `Step`, `Execution`, `ExecutionStep`, `InventoryItem`
    rows for that org are gone (except what the reseed itself creates),
  - exactly one `Process` ("Distillery Spirit Production") with 5 `Step`s exists,
  - exactly one completed `Execution` with 5 `ExecutionStep`s exists,
  - at least one `InventoryItem` has `expiry_date` in the past (the Yeast raw material,
    dated 7 days before the run) — this is the fixture's check-needed trigger for
    compliance-checks' expired-materials check.
- AC4: If no user with email `demo@whistlebird.co.nz` exists, returns 400 with
  `{"success": false, "error": "USER_NOT_FOUND", ...}` and makes no data changes.
- AC5: If `reset_demo_db` raises partway through, the route rolls back the session and
  returns 500 with `{"success": false, "error": "RESET_FAILED", "message": <str(e)>}`.
  ASSUMPTION: `message` exposes the raw exception string; there is no redaction — this
  route is dev/test-only so treated as lower risk, but see Known gaps.
- AC6: `clear_demo_db(session)` deletes all `InventoryItem`, `ExecutionStep`,
  `Execution`, `Step`, `Process` rows for the demo org and commits; it is a no-op
  (no query issued beyond the initial user lookup) if the demo user doesn't exist.
- AC7: Inventory quantity decrements performed during reseed (simulating consumption
  per step) are wrapped in `allow_inventory_quantity_write(RESETDB_DEV)` — writes
  outside that context are expected to be rejected by the guard per the inventory
  slice's hard rule (conventions.md §5).
- AC8: The reseed is *not* isolated between runs — a partial/failed prior run can leave
  rows behind that violate unique constraints on the next run (documented as a known,
  accepted rough edge in the feature index, not a bug to silently swallow).

## Data model
No models of its own. Operates on `Process`, `Step`, `Execution`, `ExecutionStep`,
`InventoryItem` (owned by process-design/execution/inventory slices) scoped to one
fixed org (the org of `demo@whistlebird.co.nz`).

## External surfaces
- `POST /api/core/reset-demo-db` — the only route.
- Python-level API used directly by tests: `reset_demo_db(session)`,
  `clear_demo_db(session)`, `DEMO_USER_EMAIL` constant
  (`app/features/demo_data/services/resetdb.py`).

## Out of scope
- Creating the `demo@whistlebird.co.nz` user itself (assumed to already exist via
  seed/migration or manual setup).
- Any UI for triggering the reset (assumed to be a settings-page button elsewhere, not
  part of this slice).

## Known gaps (informs Step 3 of review)
- No dedicated test file (`tests/test_demo_data.py`) exercises the route or
  `reset_demo_db`/`clear_demo_db` directly — only indirectly via three other suites'
  fixture usage. Zero coverage of AC1, AC2, AC4, AC5 (auth/env-gate/error paths).
  Already fixed: `tests/test_demo_data.py` now exists with 7 tests (verified 2026-08-25
  by findings-sweep).
- Route authorization: any authenticated user of *any* org (not just the demo org) can
  trigger a destructive reset of the demo org's data — `@requires_auth` without
  `@requires_org_scope` or an explicit identity check. Confined to non-production
  environments, but still a tenant-isolation gap against this repo's own invariant #1
  ("every query filters on `org_id`" — here the target `org_id` is not derived from the
  caller at all). Already fixed by commit `df26e40`:
  `app/features/demo_data/routes/api_routes.py:36-56` now has an explicit `unscoped()`
  caller-identity check requiring `g.current_org_id == demo_user.org_id` (verified
  2026-08-25 by findings-sweep).
- AC5's raw exception string in the JSON response body is a minor info-disclosure
  surface (stack-trace-adjacent detail returned to any authenticated caller), scoped to
  non-production only. Already fixed by commit `df26e40`: the exception handler now
  returns a generic message, no `str(e)` (verified 2026-08-25 by findings-sweep).

## Assumptions (reconstructed spec — no user available to interview)
- ASSUMPTION: The route's intended caller is Whistlebird's own staff/demo account, not
  arbitrary customer orgs; the missing org check is treated as a real gap because the
  code and index give no indication it was a deliberate choice.
- ASSUMPTION: "success" for AC3 means the fixture matches the theme comment at the top
  of `resetdb.py` (distillery: inputs/outputs/processes/inventory, one expired raw
  material) — not a formally specified data shape beyond what the code produces.
