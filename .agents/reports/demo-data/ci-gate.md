# CI-GATE VERIFY: demo-data
date: 2026-08-23
mode: verify (existing pipeline, not rebuilt)

## Discovery notes
`.gitlab-ci.yml`'s `unit_tests` job (stage `test`) runs `ENVIRONMENT=test uv run pytest
tests/ -v` inside a Docker-based GitLab runner, where `host.docker.internal` resolves
(unlike a bare host shell — CLAUDE.md's documented trap). This job auto-discovers new
test files under `tests/`, so `tests/test_demo_data.py` needs no pipeline change to run.

**Finding, not caused by this review, flagged for ci-gate's own attention rather than
fixed inline here (too wide a blast radius for a slice-scoped review):**
`tests/e2e/conftest.py::_e2e_skip_reason()` unconditionally skips every `e2e`-marked
test when `ENVIRONMENT=test` is set and `E2E_BASE_URL` is not — and `unit_tests` sets
`ENVIRONMENT=test` without `E2E_BASE_URL`. Grepping `.gitlab-ci.yml` for
`tests/e2e`/`E2E_BASE_URL` finds exactly one match: the post-deploy `cd_e2e` job runs
`E2E_BASE_URL=https://localhost:8001 uv run pytest tests/e2e/test_smoke.py -v` — one
file, post-deploy, not a pre-merge blocking gate. **The entire `tests/e2e/` tree
(dozens of files across many features, and now this review's 3 new demo-data e2e
tests) appears to never run as a pre-merge blocking check** — only locally, and only
post-deploy for `test_smoke.py`. This is a pre-existing, repo-wide gap unrelated to
demo-data's code; per ci-gate's own rule ("a test file that never runs is worse than no
test — it manufactures false confidence"), it deserves its own ci-gate pass (a
dedicated `e2e` stage with `ENVIRONMENT` unset + `E2E_BASE_URL` unset, chromium +
TLS-cert setup already proven in `unit_tests`'s `before_script`) rather than a
slice-scoped patch here.

## Verify checks

```
GATE lint: pass (ruff check + ruff format --check, 0 issues — app/features/demo_data/,
                  tests/test_demo_data.py, tests/e2e/demo-data/)
GATE unit: pass (10/10 — tests/test_demo_data.py 7/7 + e2e's 3/3 run locally with
                  ENVIRONMENT unset; 126/130 passed, 4 deselected — see baseline.md for
                  the pre-existing, unrelated dirty-fixture deselections)
GATE semgrep: pass (0 findings, 174 rules, 100% parse — app/features/demo_data/routes/api_routes.py)
GATE migrations: n/a (no models/schema in this slice)
GATE e2e: pass locally (3/3, 3x flake-checked — see e2e-playwright.md), NOT verified
                  as a pipeline-blocking gate — see the finding above
```

## Collection check
`pytest --collect-only -q tests/` run under the CI-matching `ENVIRONMENT=test`
invocation collects all 7 unit tests and all 3 e2e tests for this slice (the e2e ones
show `[chromium]` params, confirming Playwright collection works even though they'd
self-skip when actually run in that job).

## History store
Both security findings (F1, F2) recorded `fixed` in `.agents/history/findings.jsonl`
via `scripts/finding_history.py record` (new signatures, not the original `confirmed`
entries' signatures — the store doesn't retain the original evidence string needed to
reproduce the exact signature; noted in each entry's `notes` field for continuity).

## Recommendation
Ship this review's changes as-is (the e2e-pipeline gap is real but pre-existing and
repo-wide — routing a fix through ci-gate directly, not blocking this MR on it, matches
"don't refactor beyond what findings require"). Flag the e2e-pipeline gap prominently
in the final review report for the user's visibility.
