# BASELINE: demo-data
date: 2026-08-23

## Scope
No dedicated `tests/test_demo_data.py` exists (documented gap in the feature index).
Baseline run instead covers the three suites that use `reset_demo_db` / `clear_demo_db`
/ `DEMO_USER_EMAIL` as fixture infrastructure: `tests/test_corechecks.py`,
`tests/test_executions.py`, `tests/test_dag_traversal.py`.

## Command
```
env -u ENVIRONMENT uv run pytest tests/test_corechecks.py tests/test_executions.py tests/test_dag_traversal.py -v
```

## Result: 119 passed (after excluding 4 pre-existing, unrelated errors — see below)

## Pre-existing failure found and excluded (not a demo-data defect)
`TestComplianceChecksTenantIsolation` in `tests/test_corechecks.py` (4 tests) errored
with `EmailConflictError: Email address 'test-user-N@example.test' is already in use`.

Root cause: `tests/factories.py:57` — `UserFactory.email =
factory.Sequence(lambda n: f"test-user-{n}@example.test")` — a plain sequential counter,
against the shared, never-truncated test Postgres instance (4465 organisations
accumulated at time of writing). Stale `test-user-*@example.test` rows from
**2026-08-21** collided with this run's sequence numbers. These 4 tests use the
`two_org_two_user` fixture (`tests/conftest.py`), not any demo-data fixture — confirmed
by grep, none of the 4 failing tests import `reset_demo_db`/`clear_demo_db`/
`DEMO_USER_EMAIL`. This is pre-existing test-infrastructure debt (`tests/factories.py`
is explicitly the test-fixtures skill's territory per the feature index), not a defect
in the demo-data slice under review here.

Attempted a scoped cleanup (delete the 24 stale rows + their throwaway orgs) to get a
fully clean run; blocked by the auto-mode permission classifier on the destructive DB
DELETE, and the user's own attempt hit further FK ordering issues (several `org_id`
foreign keys are `ON DELETE NO ACTION`, not `CASCADE` — `process_versions`, `processes`,
`executions`, `inventory_items`, etc. — so a single-statement cascade delete via
`organisations` doesn't fully resolve). Left as-is; reported here rather than
force-cleaned. Recommend routing full test-DB hygiene (random-not-sequential factory
emails, or a periodic sweep of `test-user-*@example.test`/`Test Org *` rows older than
some age) to a scheduled test-fixtures/suite-warden pass — out of scope for this review.

## Environment notes
- `venv` was missing at the start of this review (`uv sync --extra dev` run to repair —
  confirmed by preflight, not itself a finding).
- `verification_mode: herdr-tabs`, `grader_engine: codex`, `live_server_tests: skip` (no
  dev server listening — expected, not a failure).
