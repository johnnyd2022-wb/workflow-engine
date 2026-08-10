# E2E: activity-log
date: 2026-08-09
verdict: patched

Gap-fill mode: zero E2E coverage existed for this slice's three routes before this review
(`scripts/e2e_coverage.py --json` confirmed all three as gaps at baseline). 12 new tests
added under `tests/e2e/activity_log/`.

| AC | Test | File | Result |
|---|---|---|---|
| AC5 (story renders) | `test_ac5_audit_history_panel_renders_created_event` | test_story_panel.py | pass |
| AC3 (single-event story) | `test_ac3_audit_history_panel_shows_empty_state_for_item_with_no_extra_events` | test_story_panel.py | pass |
| AC7 [REGRESSION] | `test_ac7_entity_summary_not_visible_cross_tenant` | test_tenant_isolation.py | pass |
| AC3 | `test_ac3_entity_story_not_visible_cross_tenant` | test_tenant_isolation.py | pass |
| AC11 | `test_ac11_activity_feed_excludes_other_orgs_events` | test_tenant_isolation.py | pass |
| AC1 | `test_ac1_invalid_entity_type_returns_400` | test_unhappy_paths.py | pass |
| AC2 | `test_ac2_invalid_entity_id_returns_400_not_500` | test_unhappy_paths.py | pass |
| AC-gap [REGRESSION] | `test_regression_non_numeric_limit_on_story_returns_400_not_500` | test_unhappy_paths.py | pass |
| AC-gap [REGRESSION] | `test_regression_non_numeric_offset_on_activity_feed_returns_400_not_500` | test_unhappy_paths.py | pass |
| AC15 | `test_unauthenticated_story_request_returns_401` | test_unhappy_paths.py | pass |
| AC11/AC14 | `test_ac11_activity_tab_renders_org_events` | test_activity_tab.py | pass |
| AC12 (real-world) | `test_activity_tab_shows_only_login_event_before_any_business_action` | test_activity_tab.py | pass |

Flake check: full suite run 3x, 12/12 pass every time (33.1-33.4s each).

## Mandatory cross-tenant probe

`test_tenant_isolation.py` covers all three routes with a real two-org, two-browser-session
setup (`logged_in_two_orgs` fixture in `tests/e2e/activity_log/conftest.py`). AC7 is the
headline: proves `entity_summary_detail`'s fix holds behind the real cookie/CSRF stack, not
just at the `app_client` level (see `tests/test_activity_log.py` for that unit-level twin).

## Fixture design note

Did not reuse `tests/e2e/traceability/conftest.py`'s `two_tenants_with_chains` (which seeds
via `build_linear_dag`/`process_repo.add_step`) because that currently fails on this shared
test DB: a `steps.org_id` NOT NULL violation traced to a migration
(`tenant_org_id_notnull_001`) present on the DB's `alembic_version` but absent from this
worktree's migration files — a concurrent worktree's in-flight schema change, unrelated to
this slice (confirmed via `alembic current`/`alembic heads` showing a head mismatch).
Activity-log's own routes never touch `Process`/`Step`, so `logged_in_two_orgs` (two fresh
orgs via the existing `fresh_user` fixture, no DAG) sidesteps the contamination rather than
working around it. Flagged for the user's awareness, not fixed here (infrastructure/shared
test-DB concern, out of this slice's scope).

## ACs not covered by this suite (covered elsewhere or not UI-observable)

- AC4, AC6, AC8-AC10, AC13, AC16: pure backend/API-shape assertions with no UI-observable
  symptom (pagination totals, legacy-audit-merge details, diff-humanisation fallback
  rendering) — covered at the `app_client`/unit level in `tests/test_activity_log.py`
  instead, matching the split established in `tests/test_traceability.py`.

## Coverage script note

`scripts/e2e_coverage.py --json` still reports all three routes as gaps after this suite was
added — verified this is a pre-existing script limitation (`E2E_DIR.glob("test_*.py")` is
non-recursive, so it never looks inside `tests/e2e/<slug>/` subdirectories) rather than
anything wrong with these tests: the already-merged, well-tested traceability routes
(`/api/core/sourcemap/*`, 20 e2e tests, commit `7c32b89`) show the identical false gap.
Not fixed here — shared tooling outside this slice's scope; reported for whoever picks up
`scripts/e2e_coverage.py` next (docs-truth or a scripts maintenance pass).

VERDICT: patched
