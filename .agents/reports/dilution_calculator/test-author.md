# TEST AUTHORING — 2026-07-26

mode: diff-reconcile

preflight: test_db=up, live_server_tests=run (app server up at https://localhost:8005/), blockers=none

## Scope

Chained after the build stage for `feat/dilution_calculator` (6 commits ahead of
`origin/main`). The feature's own inline AC tests (`tests/test_dilution_calculator.py`,
34 tests) were written by the build stage and are out of this stage's authorship scope.
Task: reconcile the rest of the suite against the full diff, and refresh
`.agents/test-map.md`.

Diff surface reviewed beyond the feature's own files:
- `app/api/app_factory.py` — registers `create_dilution_calculator_blueprint()`
  unconditionally (no feature flag, no data model — comment in the diff says as much).
- `app/ui/templates/shared/sidebar-v2.html` — adds one nav `<li>` linking
  `/dilution-calculator`.
- `app/observability/context.py` — adds two `BLUEPRINT_FEATURE` entries mapping the
  dotted nested-blueprint paths (`dilution_calculator.dilution_calculator_api` /
  `...dilution_calculator_pages`) to `"dilution_calculator"`, fixing a bug where Flask's
  `request.blueprint` for a route reached through a *nested* blueprint returns the full
  `parent.child` dotted path, not the bare child name, so these routes were silently
  falling through to `DEFAULT_FEATURE = "platform"`.

## Ripple check

- **`app_factory.py` blueprint registration**: no test in the suite enumerates
  `app.blueprints`, `app.url_map.iter_rules()`, or asserts a fixed blueprint count —
  grepped `tests/*.py` for `url_map|iter_rules|blueprints.keys|app.blueprints`, no hits.
  Existing `create_app()`-based tests (`test_org_routes.py`, `test_auth_password_session.py`,
  `test_wastage.py`, `test_crm.py`, `test_observability_telemetry_ingress.py`) each stand
  up the real app and hit only their own feature's routes; adding an always-on blueprint
  doesn't perturb any of them (confirmed: full suite green, no new failures). No update
  needed.
- **`sidebar-v2.html` nav link**: no unit/integration test renders or asserts on
  `sidebar-v2.html`'s content — nav-link presence for other features (CRM, workflow
  engine) isn't unit-tested either; this is `e2e-playwright`'s domain
  (`tests/e2e/test_dilution_calculator_flow.py` is already in this diff, not mine to
  touch per the skill boundary). No unit-test gap.
- **`observability/context.py` BLUEPRINT_FEATURE fix**: this is exactly the ripple this
  skill exists to catch, and it's already fully reconciled — the build/fix stage added
  `test_feature_mapping_for_nested_dilution_calculator_blueprints` to
  `tests/test_observability_context.py`, which reproduces the real nested-blueprint shape
  (parent `dilution_calculator` registering `api_bp`/`page_bp` as children) rather than
  the flat single-blueprint shape the pre-existing test in that file uses — a test that
  would have passed even with the mapping bug present. Verified no other observability
  test enumerates the feature list (`grep BLUEPRINT_FEATURE|feature_for_request` across
  `tests/test_observability_*.py` → only this file). No further update needed.

No product-code gap surfaced. No test file needed writing or editing by this stage —
the diff's own commits already carried the regression test for the one genuine ripple
(observability context mapping).

## Map sync

`scripts/test_map_check.py` was clean before (33 files on disk, 21 referenced, no drift)
and clean after (33 files on disk, 23 referenced — the two new references are the two
existing lines in row 23's file list, now also implicitly covering the new nested-blueprint
test in the same file, plus the new row 24).

Added a new row and section to `.agents/test-map.md`:

```
## Dilution calculator
| 24 | Solve dilution (a,b,c,d identity + water-to-add) — happy path, validation,
      determinism | dilution_calculator/services/dilution_service.py, routes/api_routes.py,
      routes/page_routes.py | test_dilution_calculator.py | covered | 34 tests ... |
```

Marked `covered` (not `partial`): the flow has no `org_id`-scoped data (stateless
calculator, no DB reads/writes — AC7 explicitly tests "writes no rows"), so the map's
hostile-neighbour tenant-isolation bar doesn't apply here; auth guard (AC6), validation,
and determinism are all exercised. `last_synced` bumped to 2026-07-26.

flows_touched: row 24 (new — Dilution calculator), row 23 (Observability — no status
change, noted the nested-blueprint regression test now living there)

tests_added: none (map maintenance only — the feature's own tests and the observability
regression test were both already written and committed before this stage ran)

tests_updated: none

map_rows_changed: row 24 added (new → covered); row 23 note updated to reference the
nested-blueprint regression test

## Suite result

```
env -u ENVIRONMENT uv run pytest tests/test_dilution_calculator.py tests/test_observability_context.py -q
37 passed
```

```
env -u ENVIRONMENT uv run pytest tests/ -q
538 passed, 1 failed in 239.49s
FAILED tests/test_execution_shared_utils_js.py::test_execution_js_node_unit
  (/usr/bin/node: bad option: --test — stale system node, pre-existing and unrelated
  to this feature; matches the stated baseline exactly)
```

suite_result: 538 passed, 1 pre-existing unrelated failure (0 skipped in this run — dev
app server was up, so the `live_server`-marked 2FA suites ran rather than skipped)

evaluator_verdict: n/a — no new or changed test file to grade. This stage authored zero
test-file changes (`git diff --name-only main...HEAD -- 'tests/**'` shows
`tests/test_dilution_calculator.py`, `tests/e2e/test_dilution_calculator_flow.py`,
`tests/e2e/test_perf_budgets.py`, `tests/test_observability_context.py` — all four were
already present and committed by earlier stages before this run started). Per the skill,
`test-evaluator` grades "the batch of new and changed tests" this stage writes; there is
none. Not invoked.

verdict: covered

## Rules check

- No existing assertion weakened, broadened, deleted, or skipped.
- No service started as a side effect (app server and test DB were already up per
  preflight).
- Nothing written outside `.agents/test-map.md` and this report.
