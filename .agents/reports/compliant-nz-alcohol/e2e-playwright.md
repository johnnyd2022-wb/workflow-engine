# E2E — compliant-nz-alcohol (gap-fill)

Scope: existing `tests/e2e/compliant-platform/` already covers generic CRUD, auth/ADMIN
gates, tenant isolation, and CSV export for the `/api/compliant/*` routes. This pass adds
coverage only for NZ-alcohol-module *behavior* that no existing test exercised: framework
applicability filtering, trade-waste council binding, and the audit-pack applicability
gate. No existing file was modified.

New file: `tests/e2e/compliant-platform/test_nz_alcohol_framework_applicability.py`
(kept in the existing directory to reuse its `admin_page`/`enable_profile`/`csrf_headers`
fixtures rather than re-seeding a parallel fixture set).

## Coverage

| AC (spec: "Framework applicability end-to-end") | Test | Result |
|---|---|---|
| `alcohol_product_types` setting filters `np3-food-control` / `wine-standards` in `evaluate()`'s output; `customs-alcohol` (`all_alcohol`) is unaffected | `test_product_type_setting_filters_np3_and_wine_frameworks_in_overview` | pass |
| Empty/unset `alcohol_product_types` shows every non-trade-waste framework (show-everything-before-choice default) | `test_unset_product_type_setting_shows_every_non_trade_waste_framework` | pass |
| `trade-waste` applies iff a consent reference is set OR `trade_waste_required` is truthy | `test_trade_waste_framework_appears_only_with_consent_or_required_flag` | pass |
| `framework_for_profile()` overlays the selected council's `version`/`source_title`/`source_url`/`controls` onto `trade-waste`, and actually changes when the council changes | `test_trade_waste_framework_reflects_selected_council` | pass |
| `build_audit_pack()` 400s a real-but-inapplicable framework via `framework_applies()`, before any query, distinct from the unknown-slug 400 already covered elsewhere | `test_build_audit_pack_rejects_a_real_but_inapplicable_framework` | pass |

All five exercise `GET /api/compliant/overview` and/or `POST /api/compliant/reports/<slug>`
through the real authenticated browser session (`page.request`), same pattern as the rest
of the directory — not unit calls into `service.py`/`catalogue.py` directly.

## Deliberately not covered here (and why)

- `catalogue.py` / `councils.py` pure-function edge cases (`framework_by_slug(None)`,
  `council_catalogue(None)`, the exact `CONTROL_REQUIREMENTS` map, `capture_requirements`'s
  `require_core_source_refs` force-add) — these are unit-testable pure functions with no
  browser-observable branch beyond what the above tests already prove through the route;
  `tests/test_compliant_catalog.py` is the right place for exhaustive input coverage, not
  a second E2E test per pure-function branch.
- `module.py`'s `register_checks()` / `run_check()` (the `CoreChecksRunner` registration,
  `CHECK_ID = "compliant.nz_alcohol"`, the `compliant_enabled` config gate) — this has no
  HTTP route of its own; it is registered against a `CoreChecksRunner` instance and its
  only browser-visible surface is the dashboard/banner system, which belongs to
  `compliant-platform`'s dashboard page (already reviewed, out of scope here per the spec's
  Provenance section). Confirming `run_check()`'s `flagged`/`data` shape is an integration/
  unit-test concern (calls `ComplianceService` directly), not a Playwright one.
- `AlcoholProductProfile` CRUD validation (`product_type` enum, ABV range, uniqueness) —
  already covered by `tests/e2e/compliant-platform/test_alcohol_products_flow.py`, not
  re-touched.

## Verification

- New file run standalone: `uv run pytest tests/e2e/compliant-platform/test_nz_alcohol_framework_applicability.py -q` — 5 passed, 3/3 runs, no flakes.
- Full directory re-run after the addition: `uv run pytest tests/e2e/compliant-platform/ -q` — 57 passed (0:02:37), no regressions in the pre-existing 52.
- Not run: `ci-gate` hookup (per this task's instructions, writes were confined to `tests/e2e/`; the suite is already collected under the existing `pytest.mark.e2e` marker so no CI wiring change is needed).

VERDICT: patched
