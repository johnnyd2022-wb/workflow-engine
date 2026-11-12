# build-review round 1 (of max 3) — live-cogs 8.1a cost engine

Worktree: /home/johnny/wt-live-cogs, branch feat/live-cogs. You are read-only: do NOT edit files.
Review the diff `git -C /home/johnny/wt-live-cogs diff origin/main...HEAD -- app/` (the code), with
`.agents/specs/live-cogs.md` v4 as the contract (8.1a scope only: Data model cost_flows /
lot_cost_entries / costing_settings, Cost roll-up, Recompute, Users & permissions, API, ACs
AC22–AC29, AC31–AC32, AC36–AC37, AC40–AC42, AC52–AC63, A9–A10). The tests in
`tests/test_costing_*.py` were written first and all pass; your earlier test-evaluator report is
`.agents/reports/live-cogs/test-evaluator-8.1a.md` and its findings were addressed.

Assume the code is guilty. This is round 1 and should be your MOST thorough pass: report every
real defect now, ranked by impact. Hunt specifically for:

1. Wrong numbers: any input where the engine's figure differs from the spec's rules
   (`app/features/costing/engine.py`): price-fact precedence, residuals, whole-lot vs flow
   prices, partial floors, split_weights branches, rounding/remainder, unit conversion
   direction (`_unit_factor`), estimate selection, memoisation returning a value computed
   under a cycle or under a different allow_estimate, WIP passed between steps of one
   execution (`_exec_building`), reconciled_in.
2. Hook correctness in Core (`execution_routes.py` complete_step, `inventory_repo.py`,
   `step_outputs.py`, `flows.py`): flows written in the same transaction, never on a failed
   path, right quantity/unit/key, output_id resolution and its 400, any regression to existing
   step completion behaviour (warnings, reconciliation, library stock, lot holds).
3. Backfill (`backfill.py`): key parity with live hooks, idempotency, events it misreads,
   cross-org leakage, performance traps.
4. Security/tenancy: every query org-filtered, composite FKs, permission table entries,
   feature gate ordering vs auth (401/403/404), error handlers leaking details, the CLI.
5. Data integrity: migration vs models drift, constraints, cascade behaviour on lot/execution
   deletion, concurrency (two PUTs racing on one slot, partial unique indexes), downgrade.
6. Anything the tests don't cover that a user would hit.

You may run read-only commands (grep, git, python -c for arithmetic). Tests use a private DB:
`PYTEST_XDIST_WORKER=cogs env -u ENVIRONMENT uv run pytest tests/test_costing_engine.py -q -p no:cacheprovider`
if your sandbox allows it; don't rely on it.

Output: markdown, findings ranked high→low, each with file:line, a concrete failing input or
scenario (observed vs expected), and the fix. End with exactly one line:
`VERDICT: pass` or `VERDICT: fail`.
