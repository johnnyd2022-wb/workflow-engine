# build — compliant_tools

Branch: `nz-alc-tools` (existing worktree, per spec assumption). Engine: Sonnet.

## What shipped

### Entitlement primitive (core)
- `app/core/db/models/feature_subscription.py` — `FeatureSubscription(Base)`, `(org_id, feature_key)` unique, `active` bool, `granted_at`, `granted_by_user_id` (FK SET NULL), `notes`.
- `app/core/db/repositories/feature_subscription_repo.py` — `FeatureSubscriptionRepository` (`get`, `is_active`, `grant` [idempotent], `revoke`, `list_for_org`), every method takes `org_id` explicitly.
- `app/core/security/entitlements.py` — `org_has_feature(session, org_id, feature_key)`.
- `app/core/db/migrations/versions/feature_subscriptions_001.py` — down_revision `system_findings_cache_001`. **Destructive**: `downgrade()` drops the table, logs a WARNING with the row count + "irrecoverable except from CSV export"; docstring carries the export/restore runbook. up/down/up verified against the test DB.
- Model registered in `app/core/db/models/__init__.py` and `migrations/env.py`.
- `FeatureSubscriptionFactory` added to `tests/factories.py`.

### CLI
- `app/cli/admin.py` + `app/cli/__init__.py` — `workflow grant-feature` / `revoke-feature` / `list-features`, all under `unscoped()`, validate the org exists, exit non-zero on bad/unknown `--org-id`.
- **whistlebird_test** (`354a8be6-…`) granted `compliant` in the local/test DB via `workflow grant-feature` — recorded here per spec assumption; test/prod grants are operator actions.

### Subscription gate
- `app/features/compliant/compliant_bp.py` — single `before_request` on the parent `compliant` blueprint: no-op when `g.current_org_id` unset (→ `@requires_auth` gives 302/401); else compute `bool(config.compliant_enabled) and org_has_feature(...)` once, cache on `g.compliant_subscribed`, `abort(404)` (generic) + one `access_denied` / `org_not_subscribed` warning log when false. Covers api/pages/tools sub-blueprints + the `/compliant/static` route.
- `app/api/app_factory.py` — `_inject_feature_flags` now also injects `compliant_subscribed` (reuses `g.compliant_subscribed`; else one query when `g.current_org_id` set and `compliant_enabled`; else False). Dilution blueprint registration + import removed.
- `app/ui/templates/shared/sidebar-v2.html` — hard-coded "Dilution Calculator" `<li>` replaced by a `{% if compliant_subscribed %}` "Compliance" `<li>` → `/compliant`.
- `app/ui/shared/sidebar-v2.html` — `{% if compliant_enabled %}` → `{% if compliant_subscribed %}` on the same item. Neither file references `/dilution-calculator`.

### Dilution relocation
- `app/features/dilution_calculator/` deleted. Solver moved verbatim to `app/features/compliant/tools/calculators/dilution.py` — maths/validation/error strings/payload byte-identical; only the exception base changed to `CalculatorValidationError` (alias `DilutionValidationError` kept). `/api/dilution-calculator/solve` and `/dilution-calculator` are gone (404).
- `app/observability/context.py` — dropped `dilution_calculator.*` mappings; added `compliant`, `compliant.compliant_api`, `compliant.compliant_pages`, `compliant.compliant_tools` → `"compliant"`. `tests/test_observability_context.py` updated (compliant nested-app test replaces the dilution one).

### Tools suite (10 Tier-1 calculators)
- `app/features/compliant/tools/` — `errors.py`, `calculators/_validate.py` (shared validation + `solve` shapes), one module per calculator (`dilution`, `lal`, `standard_drinks`, `abv_abw`, `gravity_convert`, `abv_from_og_fg`, `tank_volume`, `yield_loss`, `yeast_pitch`, `keg_fill`), `registry.py` (`CALCULATORS` + `CATALOGUE` from `catalogue.json`, import-time key-sync check).
- `app/features/compliant/modules/nz_alcohol/constants.py` — `ETHANOL_DENSITY_20C_G_PER_ML`, `NZ_STANDARD_DRINK_GRAMS_ETHANOL`. No calculator re-literals them.
- `catalogue.json` = byte copy of spec Appendix A; `tests/fixtures/compliant_tools_catalogue.json` identical.
- `app/features/compliant/routes/tools_routes.py` — `GET /compliant/tools` (page), `GET /api/compliant/tools` (catalogue), `POST /api/compliant/tools/<key>/solve` (dispatch: unknown key → 404, `CalculatorValidationError` → 400, `compliant.tool_solved` / `compliant.tool_rejected` logs).
- `app/features/compliant/frontend/templates/compliant/tools.html` — server-renders one form per calculator from the catalogue, grouped by category; `data-calculator="<key>"` + `[data-result]`.
- `app/features/compliant/frontend/static/tools-render.js` — pure module (`buildFormFields`, `buildPayload`, `solveUrl`, `renderResult`, `renderError`), CommonJS export for `node --test`.
- `app/features/compliant/frontend/static/tools-page.js` — wires submit → solve → render; array "add row".
- `app/features/compliant/frontend/static/tools.css`.

## Tests

| File | Count | Covers |
|---|---|---|
| tests/test_feature_subscriptions.py | 7 | AC1, AC2, AC8, AC18 |
| tests/test_compliant_subscription_gate.py | 8 | AC3, AC4, AC5, AC6, AC7 |
| tests/test_compliant_tools.py | 54 | AC9, AC11–AC15, AC17 |
| tests/test_compliant_dilution.py (migrated) | 40 | AC9 parity — every original dilution assertion |
| tests/js/compliant-tools-render.test.js | 42 | AC16 |
| tests/test_observability_context.py (updated) | 3 | AC10 |
| tests/e2e/compliant-platform/test_tools_flow.py | 6 | AC19 |

Fixture hand-arithmetic independently re-verified by spec-critic round 3; every Tier-1
calculator's pinned fixture passes.

## Full-suite status

`uv run pytest tests/` — 1799 passed, 5 skipped, **0 unit/integration failures**. The 64
failed + 13 errored are ALL E2E (`tests/e2e/`), from two expected ripples:
1. `tests/e2e/compliant-platform/*` + `tests/e2e/process_templates/*` — their fixtures
   mint an org but never granted the new `compliant` subscription → 404. Fixed:
   `_grant_compliant(org_id)` added to both conftests right after org creation.
2. `tests/e2e/test_dilution_calculator_flow.py` — tested the removed `/dilution-calculator`
   page. Deleted; replaced by `tests/e2e/compliant-platform/test_tools_flow.py` (AC19).

E2E re-run in progress after the fixture fixes.

## Known pre-existing issue (not from this branch)

- `tests/e2e/test_execution_flow.py:75` trips ruff `UP037` (quoted annotation). Untouched
  by this work; `uv run ruff check app/` (the CI ruff job's scope) is clean.
- Test DB alembic collision: another worktree (`feat/live-sync`) had stamped the shared
  test DB with `entity_events_seq_001` (a sibling of this branch's migration off
  `system_findings_cache_001`). Re-stamped the DB to the common parent and applied this
  branch's migration; noted for the multi-worktree shared-DB hazard.
