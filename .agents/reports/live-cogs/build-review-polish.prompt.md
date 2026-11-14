# build-review — live-cogs polish batch 2 (advisory)

Worktree `/home/johnny/workflow-engine/.claude/worktrees/live-cogs-polish`, branch
`feat/live-cogs-polish`. You are read-only: do NOT edit files. Review
`git diff origin/main...HEAD` (run `git fetch origin main` first if you can; otherwise use the
local `origin/main` ref as it is).

Contract: `.agents/plans/live-cogs-polish.md` ("Status after polish batch 2" and "Still open"),
spec `.agents/specs/live-cogs.md`. Founder rules that bind every costing change: costing works
with no Xero connected; an unknown cost is never shown as $0 or as ready; all queries are
tenant scoped by `org_id`.

## What the change claims (acceptance criteria → tests in `tests/test_costing_polish_followups.py`)

- **AC1** Readiness (`app/features/costing/readiness.py`, `_details`/`_lot_rows`): once the
  shared engine's node/work budget is spent (`TooLargeError`, which `CostEngine.lot()` turns into
  a row with warning `too_large`), the product that overflowed and every later one is costed on
  `engine.own_budget()`, so a list row's `ready` equals its own `/readiness/<key>` page.
- **AC2** A material row that ran out of budget is never written to `lot_rows_cache`, so the next
  product doesn't inherit "unknown".
- **AC3** `rules.upsert_by_matchers` keeps an existing rule's typed `payee_display` /
  `description_display`; a rule with none (saved before the typed form existed) takes the new
  casing. Matching (the normalised `payee_pattern`) is unchanged.
- **AC4** Costing settings and the alcohol profiles are read once per request:
  `CostEngine.own_budget(reuse_loaded=True|False)` replaces the private `_own_budget` helpers in
  `readiness.py` and `price_history.py` and the bare `CostEngine(db, org_id)` rebuilds in
  `price_history.py` (`_history`, `_primed`, `list_materials`) and `margins.py` (`_Costs`).
- **Not changed, on purpose:** the credit-note tax backfill cap (500 notes a sync; the plan says
  why). Out of scope: the multipack pack-size hint and "Paid for by".

## What to check hardest

1. `own_budget(reuse_loaded=True)` shares the loaded caches **by reference**. Is every place that
   calls it after a `TooLargeError` safe? Known hazard: `CostEngine.prime` sets
   `_in_flow_cache[id] = []` before it spends its work budget, so an engine whose `prime` raised
   is half loaded and must only be used with `reuse_loaded=False` (or dropped). Find any call that
   reuses an engine whose `prime` overflowed, or any other way a shared cache could hold a wrong
   row (so a lot reads as having no flows, i.e. costed as unknown/zero when it has a price).
2. Readiness: can a product ever read `ready: true` that its own page reads `false` (or the
   reverse) after this change? Think about the product that overflows part-way, the order of
   products, `declared_inputs` products, and `_add_unit_costs` (which already used its own
   engine). Is "unknown never shown as ready" preserved?
3. `rules.upsert_by_matchers`: any path where the typed display now goes stale or wrong (e.g.
   an existing rule edited to different casing through `update`, then remembered)? Any case where
   `existing.payee_display` is set but the new normalised matcher differs from the stored one?
4. `price_history.py` after the edit: trace `_history`, `_primed`, `list_materials` for each of
   (primed ok / prime overflowed / facts overflowed / per-lot overflow). Does every branch still
   cost each lot on a budget of its own and never raise a `TooLargeError` out of the request?
5. Tests: would each AC test go red if the behaviour it guards broke? Any that pass for the wrong
   reason (e.g. the settings-read count measured on the wrong engine, or fixtures that never
   overflow)?

Rank findings HIGH / MEDIUM / LOW honestly. Each finding: `file:line`, the concrete failing
scenario, and the fix. End with exactly one line: `VERDICT: pass` or `VERDICT: fail`.
