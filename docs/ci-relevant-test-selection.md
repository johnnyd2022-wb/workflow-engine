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
3. A conventional `tests/test_<module>.py` companion is included when a Python source
   file has one; frontend filenames do not accidentally pull in a same-named backend test.
4. Shared CI/dependency/config/migration/app-factory changes, or an unmapped `app/` or
   `scripts/` code path, select the complete `tests/` suite. The selector therefore
   fails safe rather than silently under-testing a new architecture area.
5. Documentation and agent-workspace-only changes select no pytest tests.

The mapping is code, covered by `tests/test_select_relevant_tests.py`, and validates
that every configured test file still exists. Its output includes reasons, so reviewers
can see and challenge every selection.

## CI rollout

- `relevant_tests` runs on merge requests. It asks the selector for the pytest targets,
  starts PostgreSQL only when the selected tests need it, and installs Node.js, Chromium,
  or starts the local app only when a deliberately selected test requires each runtime.
  Documentation-only work exits before dependency/database setup. UI source changes
  select the fast frontend/JS regression suites.
- `mr_e2e` runs `tests/e2e/test_smoke.py` on every merge request against a local TLS
  app and test PostgreSQL service. It is a blocking gate independent of relevant-test
  selection, so even a documentation-only MR exercises login and page protection flows.
  `cd_e2e` continues to smoke-test the deployed candidate on `main`.
- `unit_tests` runs `pytest tests/ -v` on `main` only. This preserves a full-suite gate
  as part of the post-merge CD pipeline before build and deploy. The separate `cd_e2e`
  job remains the browser gate against the deployed candidate, so the unit-test job does
  not download Chromium or start an unused local server.
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

## Opt-in fast MRs

Add the GitLab label **`ci::fast`** before creating an MR pipeline. For an existing
MR, add the label then use **Run pipeline** in its Pipelines tab to create a new
MR pipeline. Retrying jobs from an old pipeline does not refresh its label values.

The first allow-list covers:

- Markdown files under `docs/` and `README.md`.
- Changes to only `google_sign_in.keepass_client_id_entry` and
  `google_sign_in.keepass_client_secret_entry` in `app/config/local.ini` and its
  template, optionally with `tests/test_config_google_secrets.py`.

For the Google config case, the selector runs the focused Google credential config
tests without database, Node, or browser setup. Documentation-only fast MRs select
no pytest tests. `mr_e2e` and `migration_reversibility` log the fast-path decision
and exit before dependency/browser/database setup; their runner services may still
start. Lint, route validation, security/secret scanning, dependency auditing,
data-store checks, and the main-green gate remain active.

The selector inspects committed config snapshots and rejects any other config key
change, any additional application/CI/dependency/production file, unreadable config,
or an absent focused test. Mixed or ineligible diffs use normal CI even with the
label. Deleted files are included in the diff so deleting application code cannot
masquerade as documentation-only work. The exact label is recognised only in
`merge_request_event` pipelines; the full `main` release pipeline is unaffected.

Local preview (use the actual MR diff base and committed head):

```bash
CI_PIPELINE_SOURCE=merge_request_event CI_MERGE_REQUEST_LABELS=ci::fast \
  python3 scripts/select_relevant_tests.py --base origin/main --head HEAD --format json
```

Expand the allow-list deliberately with regression tests for each new low-impact
category. The label alone does not provide a blanket test bypass.

The test rollback job declares the `test` environment with `action: prepare`, so it
receives the same environment-scoped authentication secrets as the candidate
deployment without recording a separate successful release.
