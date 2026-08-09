# CI-GATE: activity-log
date: 2026-08-09
verdict: patched (scoped) — two pre-existing, cross-cutting environmental issues surfaced, neither caused by or specific to this slice

## This slice's own gates: all green

- `ruff check app/core/backend/backend.py tests/test_activity_log.py tests/e2e/activity_log/` — clean.
- `ruff format --check` — clean after reverting two ruff-format hunks that touched
  pre-existing, unrelated code (`reorder_steps`, `create_inventory_item`'s validation error)
  the diff had no business touching; kept the diff scoped to the actual patch.
- `python3 -c "import ast; ast.parse(...)"` — syntax OK.
- semgrep (`p/python`, `p/flask`, `p/owasp-top-ten`, `.semgrep/`) scoped to the slice's files
  — 0 findings pre-patch, 0 post-patch; new learned rule
  `bize-entity-event-summary-missing-org-filter` verified (fires on the bug, silent on the
  fix).
- gitleaks — 0 leaks, 976 commits scanned.
- `uv audit` — 0 vulnerabilities, 84 packages.
- `tests/test_activity_log.py` — **90/90 passed**.
- `tests/e2e/activity_log/` — **12/12 passed**, re-run 3x with no flakes.
- `tests/e2e/test_perf_budgets.py` — 21/21 passed (20 pre-existing + the one route this
  review added to `measure.api`), 0 ceiling/budget breaches.

## Full-suite run: 128 failed, 125 errors — both causes pre-existing and unrelated

Ran the whole suite (`pytest tests/ -q`) as a final check. It came back far off the
documented baseline (730 passed/30 skipped). Investigated rather than reported blind:
**every one of the 253 failed/error entries** falls into exactly two categories, both
confirmed pre-existing, both confirmed unrelated to this review's changes:

1. **Shared test-DB schema drift** (~most of the 253). `alembic current` on this worktree
   fails: `Can't locate revision identified by 'tenant_org_id_notnull_001'` — a migration
   that exists on the shared test DB's (`localhost:8401`, one Docker container shared by
   every concurrent `review/*` worktree today) `alembic_version`, but not in this worktree's
   migration files (`alembic heads` here resolves to `crm_revenue_baseline_target_001`,
   unrelated). That migration made `steps.org_id` NOT NULL on the live shared DB; nothing in
   this worktree's checkout sets it, so every test that creates a `Step` row
   (`test_executions.py`, `test_evidence.py`, `test_dag_traversal.py`, `test_inventory.py`'s
   execution/reconciliation cases, `test_traceability.py`, `test_process_design.py`, and the
   e2e suites that seed a DAG) fails with a real `IntegrityError`. Verified: the failing
   `INSERT INTO steps` statement has zero relation to anything this slice's routes touch.
   Already flagged once in `migration-safety.md` and `e2e-playwright.md`; the full-suite run
   is the same root cause showing up at much larger scale.
2. **The live dev server preflight found at `https://localhost:8005/` belongs to a
   different worktree**, not this one. `ps aux` shows the process serving that port is
   `review-process-design`'s `.venv`, running since Aug 2 — a leftover from a review
   completed and merged 2026-08-03 that was never torn down. `scripts/preflight.py`'s
   `_live_server_available()` only checks that *something* answers on the port; it can't
   tell whose worktree it is. Every `pytest.mark.live_server`-marked test in this run
   (`test_2fa_totp_optimized.py`, `test_auth_gap_coverage.py`, `test_login_2fa_flow.py`, the
   non-activity-log `tests/e2e/*` browser suites) was therefore silently exercising a
   different, stale checkout — not this branch's code, and not a meaningful signal either
   way for this review. `tests/test_activity_log.py` and `tests/e2e/activity_log/` are
   unaffected: the former never makes an HTTP call to `:8005` (in-process `test_client()`
   only), and the latter boots its own ephemeral-port app instance per
   `tests/e2e/conftest.py`'s documented pattern (`E2E_BASE_URL` unset, confirmed) rather than
   pointing at the shared dev server.

Neither issue is this review's to fix: (1) would mean running migration commands against a
database four-plus concurrent worktrees are actively using mid-review, and (2) would mean
killing another active session's server process. Both are flagged here for the user —
likely `worktree-sweep`/`session-sweep` territory (stale process cleanup) and a
cross-worktree migration-coordination gap (a `review/*` branch's own in-flight migration
shouldn't be applied to a DB every other concurrent worktree shares) respectively.

not_verified: full-suite green run (blocked by the two issues above, neither attributable
to this slice).

VERDICT: patched
