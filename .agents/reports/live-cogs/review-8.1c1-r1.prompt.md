# build-review round 1 (of max 3) — live-cogs 8.1c-1 recording purchases into stock

Read-only. Worktree /home/johnny/wt-live-cogs-alloc, branch feat/live-cogs-alloc (stacked on
8.1b feat/live-cogs-xero). Do NOT monitor any MR pipeline. Contract: section
"## 8.1c-1 build contract — recording purchases into stock" of `.agents/specs/live-cogs.md`
(plus the earlier ACs it names, adjusted there).

Diff: `git -C /home/johnny/wt-live-cogs-alloc diff feat/live-cogs-xero...HEAD`. Code:
`app/features/costing/actions.py` (new), engine.py (allocations as price facts, refunds),
service.py (editable_reason), purchase_sources.py (change hooks), routes.py (purchases API),
models + `costing_allocations_001`. Tests: `tests/test_costing_allocations.py` — NOTE you wrote
these while Claude's implementation was appearing in the same tree, so they never ran red;
treat them as possibly shaped to the code and check each against the contract.

One thorough pass, ranked by impact:
A. Money: any sequence of actions that leaves a lot's cost or a line's open amount wrong
   (double counting between allocations and manual entries, flow quantity overrun across
   several lines, refunds, rescaling, edit_allocations, unlink, a lot linked then its line
   voided then re-synced active again).
B. State and tabs: derive_state edge cases, skipped handling, review re-flagging on every
   re-sync, lines that vanish from every tab while holding allocations.
C. Concurrency and transactions: locks (line, lot) and their order, idempotency, partial
   writes on 400, the record path creating lots under the inventory repo's own rules.
D. Security: permissions per route (record/link/edit need inventory.adjust), tenant isolation,
   input validation.
E. Tests: falsifiability, contract mismatches, missing ACs.

Each finding: file:line, concrete failing scenario, fix. End with exactly one line:
`VERDICT: pass` or `VERDICT: fail`.
