# BASELINE: shell
date: 2026-08-15
git status: clean (before this review; .agents/specs/shell.md added by this review's spec-reconstruction step)
command: `unset ENVIRONMENT; uv run pytest tests/ -q`
result: 1487 passed, 31 skipped, 0 failed (683.41s)
note: tests/TEST_DOCUMENTATION.md / CLAUDE.md quote "730 passed, 30 skipped" as the
expected baseline — actual count has grown to 1487/31 since that was last written. Not a
shell-slice finding; flagging for docs-truth, not patching here.
No tests/test_shell.py exists — this slice has no dedicated unit-test file; its only
coverage today is the e2e suites listed in the feature index (test_pages_render,
test_smoke, test_landing_regressions, test_security_headers, test_settings_flow).
