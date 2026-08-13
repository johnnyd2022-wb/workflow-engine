# TEST-AUTHOR: dashboard
date: 2026-08-12
verdict: patched
note: the test-author stage (herdr tab w18:p4) wrote all tests below, then stalled waiting
  on a background bash coverage run that had already exited (headless `-p` sessions don't
  reliably deliver background-task completion back to themselves — three consecutive "still
  waiting" turns running `true` with no state change). No pytest process was actually
  running. The orchestrator closed the stalled pane and independently verified the diff it
  left behind (`git diff tests/test_dashboard_summary.py`, 338 insertions, nothing else
  touched) rather than discarding real, already-correct work over a plumbing failure.

## Coverage: before → after
`env -u ENVIRONMENT uv run pytest tests/test_dashboard_summary.py tests/e2e/dashboard tests/e2e/test_tenant_isolation.py -k "not live_server" --cov=app.core.backend.backend --cov-report=term-missing`,
filtered to the dashboard slice's own line range (`backend.py:4183-4912`):

- before: 54 uncovered statements
- after: 6 uncovered statements (4407, 4473, 4503, 4600, 4808, 4811 — remaining isinstance/
  type-guard edge branches judged lower priority than the CRM-exception path; not chased
  further per the skill's "don't chase 100%" guidance)

## Tests added (27 new, all in `tests/test_dashboard_summary.py`)
Priority 1 — the CRM-enabled try/except in `get_dashboard_summary` (AC5), previously
completely unexercised, closed with 4 route-level tests using a real Flask app + monkeypatched
`CRMService`:
- `test_dashboard_summary_crm_failure_is_caught_and_logged_not_propagated` — a raising
  `CRMService.get_overview` still returns 200 with the disabled `sales`/`tasks` shape, and
  the failure is logged (`logger.exception`), not swallowed silently or propagated as a 500.
- `test_dashboard_summary_baseline_target_value_error_falls_back_to_null` — a non-numeric
  `revenue_baseline_target_mtd` degrades to `null` fields rather than raising.
- `test_dashboard_summary_baseline_target_variance_and_attainment_computed` — the success
  path of the same block: a valid baseline produces correct variance/attainment numbers.
- `test_dashboard_summary_route_skips_non_dict_task_and_revenue_rows` — malformed rows from
  CRM (a bare string instead of a task dict, an unparseable revenue day) are skipped, not
  fatal.

Priority 2-4 — pure-function edge cases (`_dashboard_parse_due_date`, `_dashboard_parse_date_like`,
`_dashboard_series_from_date_counts` default-argument branches, `_dashboard_priority_rank`,
`_dashboard_count_red_amber`, `_dashboard_open_action_item_dates` isinstance guards): 23 tests,
parametrized where the skill's existing style already used parametrization.

## Verification (run independently by the orchestrator, not just claimed by the stalled stage)
```
env -u ENVIRONMENT uv run pytest tests/test_dashboard_summary.py -v
# 31 passed in 2.62s

env -u ENVIRONMENT uv run pytest tests/test_dashboard_summary.py tests/e2e/dashboard tests/e2e/test_tenant_isolation.py -k "not live_server" -q
# 71 passed

uv run ruff check tests/test_dashboard_summary.py       # All checks passed!
uv run ruff format --check tests/test_dashboard_summary.py  # already formatted
```

No changes needed to `.agents/test-map.md`'s Dashboard row (line 82) — its "covered" status
was already accurate; this batch deepens coverage within an already-`covered` row rather
than flipping a `gap` to `covered`.

VERDICT: patched
