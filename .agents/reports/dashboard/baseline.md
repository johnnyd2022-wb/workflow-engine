# BASELINE: dashboard
date: 2026-08-12
git_status: clean (only untracked .agents/specs/dashboard.md, this review's own reconstructed spec)

## Tests
`env -u ENVIRONMENT uv run pytest tests/test_dashboard_summary.py -v`

```
4 passed in 0.82s
```

- test_dashboard_task_bucketing_due_today_and_overdue — PASSED
- test_dashboard_compliance_score_formula_v1 — PASSED
- test_dashboard_action_board_excludes_stalled_batches — PASSED
- test_dashboard_operations_summary_org_isolated — PASSED

No pre-existing failures. Clean to proceed into the verification chain.

## Environment
- preflight: blocked on missing venv (`uv sync --extra dev` run to fix) — resolved before this baseline, now `ok: true`, no blockers.
- verification_mode: herdr-tabs
- grader_engine: codex
- live_server_tests: skip (no app server listening — suites needing it will auto-skip with reason)
- test_db: localhost:8401/workflow-engine-test (shared container, already running, healthy)
