# test-evaluator (+ spec-critic round 3, scoped) — live-cogs 8.1a

Worktree: /home/johnny/wt-live-cogs, branch feat/live-cogs. You are read-only. Do NOT edit files.

The founder wants a solid plan with minimal bugs, with tests written BEFORE the code so the
final implementation must pass them. The implementation (`app/features/costing/`) does not
exist yet; every test currently fails on import. That is expected.

Read:
1. `.agents/specs/live-cogs.md` (v4). Only these parts are in scope: "Data model"
   (`lot_cost_entries`, `cost_flows`, `costing_settings`), "Cost roll-up", "Recompute",
   "Users & permissions", "API" payloads, ACs AC22–AC29, AC31–AC32, AC36–AC37, AC40–AC42,
   AC52–AC63, ASSUMPTIONS A9–A10. Purchases/Xero/rules (8.1b–e) are out of scope.
2. The tests: `tests/costing_helpers.py`, `tests/test_costing_engine.py`,
   `tests/test_costing_flows.py`, `tests/test_costing_routes.py`, `tests/test_costing_transfer.py`.
3. Any app code you need to confirm a test's setup is realistic (e.g.
   `app/core/backend/execution_routes.py` complete_step, `app/core/db/repositories/inventory_repo.py`,
   `app/features/reconciliation/service.py`, `app/core/backend/step_outputs.py`,
   `app/features/site_transfers/service.py`, `app/core/security/access_policy.py`).

Grade, in ONE thorough pass (this is round 1 of at most 3; report everything real now):

A. For each test: is the expected value actually what the spec's rules produce? Recompute the
   arithmetic yourself. Flag any test whose expectation contradicts the spec or another test.
B. Falsifiability: would the test go red if the behaviour it names were broken? Name tests that
   would pass against a plausible wrong implementation (tautologies, assertions that hold
   either way, setup that never reaches the code path).
C. Setup realism: will the setup actually work against the real app code (route payloads,
   fixtures, untracked reconciliation, library stock, transfer fixtures, custom roles)? Flag
   anything that will fail for reasons unrelated to costing.
D. Coverage: which in-scope ACs or spec rules have no test, or only a weak one? Especially:
   output identity, split rules, partial propagation, residual pricing, whole-lot vs flow
   price precedence, backfill keys/idempotency, cycles, tenant isolation, permissions.
E. Spec gaps (in-scope sections only): anything still ambiguous enough that two competent
   implementers would build different numbers.

Output: a markdown report with sections A–E, each finding with file:line, severity
(high/medium/low), what's wrong, and the concrete fix. End with exactly one line:
`VERDICT: valid` or `VERDICT: weakened` or `VERDICT: gamed` or `VERDICT: inconclusive`.
