# BASELINE: org
date: 2026-07-26
git: review-feature branch, clean

## Command
`unset ENVIRONMENT && uv run pytest tests/test_org_routes.py -v`

## Result
11 passed, 0 skipped, 0 failed.

## Notes
- No pre-existing failures.
- No test in this file exercises cross-tenant isolation (a user in org A hitting
  `/org/users` or `/org/users/<id>` scoped to org B) — flagged for security-audit /
  test-author (maps to AC8 in .agents/specs/org.md).
