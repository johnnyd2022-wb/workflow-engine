# Staging deployment extension and shared helper verification

Date: 2026-10-27
Branch: `fix/prod-deploy-safety`
Follows the initial production verification report and green MR !594 head pipeline
`2993184390` at `2856bd8a4fee45594c9b19be4213b222946feae7`.

The founder asked to apply the same safeguards to `scripts/run_test.sh`. The manual
staging and production scripts now source `scripts/deploy_common.sh` for the clean
current-main gate, per-environment lock, validated private PostgreSQL backup, and
candidate/port handover with app restoration. Staging keeps its test-specific secrets,
database, network, image, and port. `scripts/deploy_test_simple.sh` and the registry CD
flow are separate and unchanged; concurrent manual/CI staging deploys require operator
coordination.

## Verification

- `uv run pytest --noconftest tests/test_prod_deploy.py tests/test_prod_config_bringup.py tests/test_config_production_secrets.py -q`:
  **79 passed**, 32.65 seconds. The 54 orchestration cases run both real deploy scripts
  inside disposable Git repositories with fake Docker, curl, uv, and secret export.
  Existing production config/secrets tests are also included.
- `bash -n` and ShellCheck on all four affected shell scripts: clean.
- Ruff check/format on the orchestration tests: clean.
- Semgrep `--config=auto --error` on four shell scripts and the test file: 293 rules,
  five targets, zero findings.
- `git diff --check`: clean.

The extra coverage asserts the same dirty/stale/fetch-failure gates, backup-first order,
incomplete-archive removal, migration/candidate failure safety, final startup and
health rollback, rename/stop failure handling, lock contention, detached current main,
and successful release for both environments.

Read-only inherited-model review found one new P2 issue in the first shared-helper
version: `deploy_app` ran in a subshell, so SIGTERM sent to the launcher's original PID
bypassed cleanup. The reviewer reproduced it with fake commands against both scripts.
The helper now runs in the launcher shell; the regression test targets the launcher's
PID explicitly. Second review verified six signal cases (launcher termination and
rename interruption for both environments) and `bash -n`; **verdict clean**. This is
same-engine review, not an independent model review.

No live Docker, production or shared test database, production credentials, or staging
service were accessed. Fake-command validation cannot prove real Docker/container
startup, full archive restoration, or migration backward compatibility. A deployed
application smoke test and restore rehearsal remain operator follow-up.
