# CI-GATE: execution
date: 2026-08-02
verdict: patched

## Verify mode
This branch's own `.gitlab-ci.yml` already exists (built by a prior ci-gate run, per
its discovery-mapping comment at the top). This pass verifies everything added by this
review is actually collected and enforced by it — the chain contract's own warning:
"everything added above must be collected and enforced or it evaporates."

## What's already enforced
- `unit_tests` (stage `test`) runs `ENVIRONMENT=test uv run pytest tests/ -v` against a
  real Postgres service container with the app's own migrations applied — a blanket
  `tests/` invocation, so `tests/test_evidence.py` (new file) and this review's changes
  to `tests/test_executions.py` / `tests/test_dag_traversal.py` are picked up
  automatically with no CI config change needed.
- `semgrep` (stage `security`) runs against `app/` including `.js` — covers
  `app/core/backend/dagtraversal.py`, `evidence/*.py`, and
  `app/core/frontend/js/execution-modal.js`, all touched by this review's fixes.

## Gap found and fixed: Playwright e2e tests never actually ran in the blocking job
`unit_tests`'s `before_script` never installs a Chromium binary. `tests/e2e/conftest.py`
gates every Playwright test on `_chromium_available()`, which — correctly, per
suite-warden's "absent dependency is a skip, never a failure" rule — **skips** rather
than fails when Chromium is missing. Net effect: `pytest tests/ -v` in `unit_tests` has
been silently skipping **every** file under `tests/e2e/`, including the pre-existing
`tests/e2e/test_workflow_flow.py`, since whenever this job was written — not something
this review introduced, but this review's new `tests/e2e/test_execution_flow.py` (7
tests, including the mandatory cross-tenant probe) would have inherited the exact same
fate: added, green locally, silently inert in CI forever.

The `cd_e2e` job (stage `deploy`, post-merge) does run `uv run playwright install
--with-deps chromium`, but only exercises `tests/e2e/test_smoke.py` — a deploy smoke
test, not a merge gate, and not this file.

Fixed by adding the same `playwright install --with-deps chromium` line to
`unit_tests`'s `before_script`, right after `uv sync --extra dev`. This is the only
change to `.gitlab-ci.yml` — no new job, no new stage, matching an existing, already-
proven command from `cd_e2e`.

**Could not be verified by actually running the pipeline** (this session has no GitLab
runner access) — verified instead by: (1) confirming `.gitlab-ci.yml` parses as valid
YAML with the new line at the correct indentation inside the existing list, (2)
confirming locally that `tests/e2e/test_execution_flow.py` and
`tests/e2e/test_workflow_flow.py` both pass when Chromium *is* available (this
session's dev environment already has it installed), and (3) reading
`tests/e2e/conftest.py`'s skip logic directly to confirm the causal chain (no Chromium
→ `_chromium_available()` False → `pytest_collection_modifyitems` marks every e2e test
skipped). Flagging the "not run against a live GitLab runner" limitation explicitly
rather than claiming full verification.

## Not changed
- `cd_e2e` / promotion / rollback jobs: out of scope, unaffected by this review.
- No new CI job added for the evidence/dag-traversal/execution unit tests — they ride
  the existing blanket `pytest tests/ -v` invocation, which is the intended, lean
  pattern this repo already uses (one test job, not one per file).

VERDICT: patched
