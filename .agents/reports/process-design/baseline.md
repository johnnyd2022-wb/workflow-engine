# BASELINE: process-design
date: 2026-08-02
git status: clean (only untracked .agents/specs/process-design.md, this review's reconstructed spec)

## Test run
Command: `env -u ENVIRONMENT uv run pytest tests/ -q` (no dedicated `tests/test_process_design.py`
exists yet — ran full suite; ENVIRONMENT unset resolves to local, pointing at the test DB on
localhost:8401 per CLAUDE.md/preflight).

Result: **748 passed, 30 skipped**, 0 failed (304.5s).

- The 30 skips are the live-server 2FA suites (`pytest.mark.live_server`), auto-skipped because
  no dev server is running (preflight `app_server: down`) — expected, not a defect.
- CLAUDE.md's documented baseline is "730 passed, 30 skipped"; 748 vs 730 is 18 more passing
  tests than documented — net positive drift (tests added since CLAUDE.md was last verified),
  not a regression. Not treating this as a docs-truth finding since it's a >= comparison, not
  a mismatch in kind.

## Verdict
Baseline is green. No pre-existing failures to report. Proceeding to the verification chain.
