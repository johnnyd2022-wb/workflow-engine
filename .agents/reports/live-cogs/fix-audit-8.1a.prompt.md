# Fix the 8.1a audit findings — live-cogs (MR !689)

You may edit files in /home/johnny/wt-live-cogs (branch feat/live-cogs). You cannot commit (the
sandbox can't write .git) — leave the changes in the working tree; Claude reviews and commits.
Do NOT monitor or wait on any MR pipeline. Don't touch any other worktree.

Findings: `.agents/reports/live-cogs/audit-8.1a.md`. Fix these, each with a test in
`tests/test_costing_*.py` (match the existing style, helpers in `tests/costing_helpers.py`):

1. HIGH — `app/core/db/migrations/versions/costing_engine_001.py` downgrade: refuse when ANY row
   exists in `cost_flows`, `lot_cost_entries` or `costing_settings` (RuntimeError naming the
   table). Update the module docstring (flows are NOT all rebuildable: reconciliations aren't).
   Also add the three `ix_<table>_org_id` indexes that `TenantScoped.org_id(index=True)` declares
   (check the exact names SQLAlchemy would generate) to upgrade and downgrade.
2. MEDIUM — `app/features/costing/routes.py`: in the blueprint before_request, reject bodies over
   16 KiB with 413 before parsing (check `request.content_length`; also set
   `request.max_content_length`). Test: a 20 KiB PUT → 413, nothing written.
3. MEDIUM — `app/features/costing/engine.py` `_estimate`: charge every candidate lot it evaluates
   against the same budget (`self._charge(("lot", other.id))`), so a lot with thousands of
   same-name candidates hits `too_large` instead of doing unbounded work. Test with
   `monkeypatch.setattr(engine, "MAX_NODES", 3)` and 5 same-material priced lots.
4. LOW — `lot_cost_entries.created_by_user_id`: make it `(org_id, created_by_user_id) →
   users(org_id, id)` ON DELETE SET NULL (created_by_user_id) — only if `users` has a UNIQUE
   (org_id, id); if it doesn't, leave it and say so in your final message.

Run the costing tests against the branch's private DB (localhost:8401):
`PYTEST_XDIST_WORKER=cogs env -u ENVIRONMENT uv run pytest tests/test_costing_engine.py tests/test_costing_flows.py tests/test_costing_routes.py tests/test_costing_transfer.py tests/test_costing_customer_owned.py -q -p no:cacheprovider`
Before running them, re-apply the edited migration on that DB:
`PYTEST_XDIST_WORKER=cogs env -u ENVIRONMENT uv run alembic downgrade planning_replan_001 && PYTEST_XDIST_WORKER=cogs env -u ENVIRONMENT uv run alembic upgrade head`
(the DB holds only test data; if the downgrade refuses because of leftover rows, delete rows from
those three tables in that DB first — ONLY in database `workflow-engine-test_cogs`, never any
other). Then `uv run --extra dev ruff check app tests && uv run --extra dev ruff format app tests`.

Final message: what you changed per finding, test results (paste the summary line), anything you
didn't do and why.
