# review-e2e-playwright — process_templates (gap-fill)

verdict: patched

## What happened

Ran the existing suite (`tests/e2e/process_templates/test_process_templates_flow.py`,
8 tests, verdict `patched` from the build-time e2e-playwright stage) first, per this
stage's mandate, to confirm it's still green post-merge. It was not, reliably: 1 of 2
runs failed `test_ac2_org_without_compliant_sees_empty_catalogue` on a real intermittent
flake — see F1. Fixed that, then checked every AC (AC1-AC13) against the spec for E2E
coverage and added tests for the gaps: AC7's mandatory cross-tenant probe, AC6's
copy-endpoint 404 for an unpermitted family, and AC5's unknown-family-filter contract.
Suite is now 11/11, run three times clean (34-37s each).

## Finding — real flake, fixed

### F1: post-login dashboard's own background fetch races test navigation, mislogged as a page fault

`login_through_ui` (`tests/e2e/conftest.py`) returns as soon as the URL becomes
`/dashboard`, but `dashboard.js` kicks off `getDashboardSummary`/`getSystemFindings`
fetches asynchronously *after* that. `compliant_page`/`no_compliant_page`
(`tests/e2e/process_templates/conftest.py`) then immediately either called
`_enable_compliant` (a `page.request` XHR, harmless) or yielded straight to the test,
whose first action is `page.goto(...)` — a real navigation that cancels the dashboard's
in-flight fetch. Chromium's `fetch()` rejects a navigation-cancelled request with a plain
`TypeError: Failed to fetch`, not an `AbortError` (that name is reserved for explicit
`AbortController` cancellation) — so `app/core/frontend/js/core-api.js`'s catch block,
which only special-cases `AbortError`, logs it as a genuine `console.error`, which
`assert_clean_page` then correctly treats as a page fault since it has no way to tell
the two apart either.

This is a shared-infrastructure race (`core-api.js` is used by every SPA page, not just
this feature) — out of scope to patch given this stage's writes are confined to
`tests/e2e/process_templates/` and the concurrently-running security-audit stage. Fixed
test-side instead: both fixtures now call `page.wait_for_load_state("networkidle")`
right after `login_through_ui`, so the dashboard's own fetches resolve before the
fixture yields and before any test-driven navigation can cancel them.

Reproduced deterministically (2 runs, 1 failure, exact same assertion and error text
both times pre-fix) and confirmed clean across 3 consecutive full-suite runs post-fix.

## Gap-fill: new tests

| AC | Gap | Test added |
|----|-----|------------|
| AC7 | Mandatory cross-tenant probe — never had one for a template-sourced process | `test_ac7_second_org_cannot_reach_a_template_sourced_process` — org A copies a template via the real API, org B (a stranger org, no Compliant needed) gets 404 on `GET /api/core/processes/<id>`; org A's own GET still 200s, so the test can't pass by the route always 404ing. |
| AC6 (+AC3's rule extended to the mutating route) | Only the read-only detail route (AC3) had a 404-for-unpermitted-family test; the copy endpoint itself never had one | `test_ac6_copy_404s_for_org_without_permitted_family` — `POST /api/core/process-templates/<id>/copy` from an org without Compliant enabled, 404. |
| AC5 | Family filter's "unknown value → empty list, not 400" contract was untested — existing `test_ac5_family_filter_narrows_the_card_grid` only exercises real family values | `test_ac5_unknown_family_filter_returns_empty_list_not_400` — `?family=not_a_real_family` returns 200 with `templates: []`, and `families` still reports the org's own 3 permitted families (proving the filter narrows templates, not the org's family list). |
| AC12 | Empty-state 200 render for an org with zero permitted families | Already covered: `test_ac2_org_without_compliant_sees_empty_catalogue` asserts `GET /core/flows/create/template-catalog` returns 200 (not 404) and `[data-pt-empty]` is visible for a no-Compliant org — this **is** AC12's contract, just filed under the AC2 test name since both ACs share the same no-Compliant-org scenario. No new test needed; noting here so the AC is traceable. |

New fixture: `cross_tenant_pages` (`tests/e2e/process_templates/conftest.py`) — org A
(Compliant + `nz_alcohol` enabled) and org B (plain), mirroring the `two_tenants` pattern
already used by `tests/e2e/test_tenant_isolation.py` and friends, scoped locally to this
suite since org A additionally needs Compliant enabled to have something to copy.

## Coverage (final)

11/11 green, run 3x with no flakes:
- AC1: chooser at its own URL, scratch card unchanged (2 tests, pre-existing)
- AC2, AC12: empty catalogue + 200 empty-state render for a no-Compliant org (pre-existing)
- AC3: detail route 404 for unpermitted family (pre-existing)
- **AC6: copy route 404 for unpermitted family (new)**
- AC5, AC10: card grid, family filter narrows, advisory string in preview (pre-existing)
- **AC5: unknown family filter → empty list, not 400 (new)**
- AC6, AC13: copy → wizard summary with copied step visible (pre-existing)
- **AC7: cross-tenant probe on a template-sourced process (new)**

AC4, AC8, AC9, AC11: intentionally not covered here — unit/integration-only per the
spec's own testing note (registry-seam unit test, execution-lineage unit test,
`sample_only` override unit test, `EventWriter` event-payload assertions). Confirmed
still present and green in `tests/test_process_templates.py` (27 tests) rather than
re-derived at the E2E layer, matching this suite's own file-header note and the
e2e-playwright skill's "don't re-derive service-layer assertions" guidance.

`scripts/e2e_coverage.py --json` reports zero gaps for any `process-templates` /
`template-catalog` route.

Also re-ran `tests/e2e/test_process_wizard_flow.py` (24 tests) to confirm the earlier
build-time chooser regression stays fixed — still 24/24 green, unaffected by this
stage's conftest change (scoped to `tests/e2e/process_templates/`, not shared conftest).

VERDICT: patched
