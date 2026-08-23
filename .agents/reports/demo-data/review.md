# REVIEW: demo-data
date: 2026-08-23
baseline: 119/119 tests green (3 suites exercising demo-data's fixtures), with 4
  pre-existing, unrelated errors excluded and documented (dirty shared test DB —
  `tests/factories.py`'s sequential `UserFactory` emails colliding with stale rows;
  root-caused, not fixed here, see baseline.md)
verdict: patched

| stage | verdict | findings | report |
|-------|---------|----------|--------|
| baseline | pre-existing issue found & excluded | 1 (test-infra, not demo-data) | baseline.md |
| security-audit | findings-open → patched | 2 (F1 auth gap, F2 info-disclosure) | security-audit.md |
| e2e-playwright | patched | 1 gap closed (0 → 3 tests) | e2e-playwright.md |
| unit coverage / test-author | patched | 1 gap closed (0 → 7 tests) | test-author.md |
| test-evaluator | valid | 0 (4 mutation probes, all correctly red) | test-evaluator.md |
| perf-guardrails | within-budget (excluded by design) | 0 | perf-guardrails.md |
| observability | instrumented | 2 event lines added | observability.md |
| ci-gate | pass (with 1 flagged, unfixed, repo-wide gap) | 1 (e2e never gates CI) | ci-gate.md |

## What this review found and fixed

**F1 — missing caller-identity check (security-audit.md, patched in
`app/features/demo_data/routes/api_routes.py`).** The route was gated only by
`@requires_auth`; `reset_demo_db()` always targets the fixed "demo" org, resolved by
email, never checked against the caller's own org. Static analysis alone read this as
"any authenticated user of any org can wipe the demo org's data." **Running the actual
e2e cross-tenant probe surfaced something static analysis missed**: a platform-wide
defense-in-depth layer (`app/core/db/tenant_filter.py`) already silently blocks this in
practice — but via a confusing `400 USER_NOT_FOUND`, with no `access_denied` log, and
undocumented reliance on a side effect neither `demo_data` nor its own tests stated.
Patched with an explicit, `unscoped()`-based caller-org check: `403 FORBIDDEN` +
`access_denied` warning log, independent of the incidental filter. Severity was real
but lower than first assessed — full writeup in security-audit.md's "Empirical
correction" section; this is the kind of gap only dynamic testing catches, which is
exactly why the chain runs both.

**F2 — raw exception string in the 500 response body**, unrelated to F1. Patched: a
generic client-facing message, with the real exception still logged server-side
(`logger.exception`, already present).

**Coverage, before → after:**
- `app/features/demo_data/routes/api_routes.py`: 29% → 91% (uncovered lines are now-dead
  defensive branches — see test-author.md for why they're not worth a contrived test).
- `app/features/demo_data/services/resetdb.py`: 96% → 97%.
- `tests/e2e/demo-data/`: did not exist → 3 tests, 3/3 flake-checked.
- `tests/test_demo_data.py`: did not exist → 7 tests (the exact gap the feature index
  flagged) — 3/3 flake-checked.

**Observability:** two new structured log lines (`demo_data_reset_completed` INFO,
`access_denied` WARNING), both asserted via `caplog` in the unit suite.

**Tests are honest, not just green:** `test-evaluator.md` — 4 mutation probes (dropping
the org check, reverting the raw-exception fix, neutering the env gate, removing
`@requires_auth`) each run live against the test DB, each correctly went red, each
reverted cleanly. Codex (the intended independent grader engine) is currently broken in
this environment (version-skew in its own model-list parsing, unrelated to this repo) —
disclosed in the report; graded by Claude instead, same agent that wrote the tests, so
treat the static-check half of that report as self-review rather than independent eyes.

## What remains open (not fixed here, flagged for follow-up)

**Repo-wide, pre-existing: `tests/e2e/` never runs as a pre-merge CI gate.**
`.gitlab-ci.yml`'s only pre-merge test job sets `ENVIRONMENT=test` without
`E2E_BASE_URL`, which `tests/e2e/conftest.py` unconditionally treats as "skip every e2e
test." The only job that ever runs a `tests/e2e/*` file is a post-deploy smoke check
scoped to `test_smoke.py` alone. This means every e2e suite in the repo — including
this review's new 3 demo-data tests, and the dozens across other slices — is currently
decoration in CI: real locally, invisible to the pipeline. Recommend a dedicated
ci-gate pass to add an `e2e` stage (chromium + TLS cert setup already proven working in
`unit_tests`'s `before_script`, `ENVIRONMENT` left unset). Out of scope for this
slice-scoped review; not silently patched here per "don't refactor beyond what findings
require."

**Pre-existing, unrelated test-infrastructure debt:** `tests/factories.py`'s
`UserFactory.email = factory.Sequence(...)` against a shared, never-truncated test
Postgres instance (4465+ organisations accumulated) causes sporadic unique-constraint
collisions when stale rows from a prior run share the current run's sequence range —
hit 4 such errors in `test_corechecks.py`'s `TestComplianceChecksTenantIsolation`
during baseline, unrelated to any demo-data fixture. Root-caused in baseline.md,
recommend routing to a scheduled test-fixtures/suite-warden pass.

## Recommendation
Ship the code changes in this review (F1/F2 fix, new unit + e2e tests, observability).
The two flagged-open items are real but appropriately routed elsewhere: the CI e2e gate
is a pipeline-infrastructure change with repo-wide blast radius, and the factory-email
collision is test-fixtures' territory — neither is demo-data's code, and patching
either here would exceed this review's scope.
