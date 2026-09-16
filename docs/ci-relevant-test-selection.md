# Relevant-test CI plan

## Goal

Merge requests should exercise the tests most likely to catch a regression in their
changed area, without paying for the entire test suite every time. `main` remains the
release gate: it runs the complete suite before build/deploy.

## Design

`scripts/select_relevant_tests.py` is the single deterministic selector. It compares
the merge-request diff base with the head commit, then reports a JSON/human-readable
plan containing selected test files, the source path/rule that selected each one, and
whether a real server or Chromium is needed.

Selection is conservative:

1. A changed `tests/**/*.py` file always runs itself.
2. Explicit maps cover Core execution/inventory/API/security, Core and Inventory UI,
   Compliant, CRM, operational cases, process templates, demo data, and observability.
3. A conventional `tests/test_<module>.py` companion is included when present.
4. Shared CI/dependency/config/migration/app-factory changes, or an unmapped `app/` or
   `scripts/` code path, select the complete `tests/` suite. The selector therefore
   fails safe rather than silently under-testing a new architecture area.
5. Documentation and agent-workspace-only changes select no pytest tests.

The mapping is code, covered by `tests/test_select_relevant_tests.py`, and validates
that every configured test file still exists. Its output includes reasons, so reviewers
can see and challenge every selection.

## CI rollout

- `relevant_tests` runs on merge requests. It asks the selector for the pytest targets,
  installs Chromium and starts the local app only when a deliberately selected E2E test
  requires them, and exits successfully without bootstrapping a database for
  documentation-only work. UI source changes select the fast frontend/JS regression
  suites; browser smoke coverage remains the existing deployed `cd_e2e` gate on `main`.
- `unit_tests` runs `pytest tests/ -v` on `main` only. This preserves a full-suite gate
  as part of the post-merge CD pipeline before build and deploy.
- Lint, security, migration reversibility, dependency auditing, and data-store checks
  remain independently configured checks; this change only targets the expensive Python
  test-suite invocation.

## Operating locally

```bash
python3 scripts/select_relevant_tests.py --base origin/main --head HEAD
python3 scripts/select_relevant_tests.py --paths app/core/frontend/inventory/inventory.js
python3 scripts/select_relevant_tests.py --format pytest --base origin/main --head HEAD
```

When a new product area is introduced, add its source-to-test rule before relying on
targeted CI. Until then, the selector intentionally chooses the full suite.
