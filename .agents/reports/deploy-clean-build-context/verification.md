# Deploying with local untracked files

Date: 2026-10-27
Branch: `fix/deploy-clean-build-context`
Base: merged MR !594, main `742c4b53f12779d7bbefb6dc8e06a9be37abc762`.

The founder tried `scripts/run_test.sh` from an up-to-date main checkout. The new
source guard refused dozens of generated, untracked agent reports and files. Their
`git reset --hard` correctly left these files in place because Git does not reset
untracked files. No files in that checkout were deleted or edited by this change.

Both manual deployment scripts now require clean **tracked** files and the exact
freshly fetched main commit. Builds take `git archive` of that pinned commit into a
private temporary directory and pass only that directory to Docker. Untracked and
ignored local files stay in the checkout and outside the image. The temporary context
is removed after success, build failure, or INT/TERM. A second source check still
aborts before database operations if tracked files or main changed during the build.

Validation:

- `uv run pytest --noconftest tests/test_prod_deploy.py tests/test_prod_config_bringup.py tests/test_config_production_secrets.py -q`:
  **81 passed**. The fake Docker build inspects the real archive context for its tracked
  Dockerfile and source, rejects a local untracked file, and records that the temporary
  context has been removed. Production and staging both exercise the path.
- ShellCheck and `bash -n` on affected deployment scripts: clean.
- Ruff check/format on tests and `git diff --check`: clean.
- Semgrep `--config=auto --error` on affected scripts/test: 293 rules, zero findings.

Read-only inherited-model review found one P3 cleanup gap: a signal sent to the build
helper could bypass EXIT and leave the private snapshot. INT/TERM now exit via cleanup.
Targeted interruption tests for production/staging pass; final review clean. Same-engine
review, not an independent model. No live Docker, staging/production database, secrets,
or service were touched. Archive/source orchestration is verified; actual image startup
and migration compatibility remain covered by the prior deploy MR's operational limits.

The prior main pipeline for MR !594 passed its test build, staging deployment, E2E check,
and stable-image promotion. This follow-up does not itself deploy staging or production.
