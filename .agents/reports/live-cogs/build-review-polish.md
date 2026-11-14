# build-review — live-cogs polish batch 2

**Codex did not report.** `build-review` was launched on `git diff origin/main...HEAD` (herdr pane
`w29:p3Q`, prompt `build-review-polish.prompt.md`) and exited, but this builder session has no
permission to read `~/.codex/sessions` or the herdr pane (both refused), so the report could not be
retrieved. Rather than skip the advisory review, the same diff was reviewed with Claude's
`/code-review` at `high` effort (below). **Codex's verdict is still owed**; the founder-level review
of the whole feature is the backstop.

## Findings and dispositions (Claude `/code-review`, high)

| # | Finding | Disposition |
|---|---------|-------------|
| 1 | `readiness._details` doesn't guard its up-front `engine.prime(...)`: with the work budget at 0 the list raises `TooLargeError`. | **Rejected for this MR, recorded.** Real, but on `main` too and a different failure from the shared budget in scope (it needs 200,000 loaded rows). Written into the plan's "Still open" with the fix shape (prime per product, as price history and margins do). |
| 2 | `_add_unit_costs` primes the `own_budget()` child, which shares caches by reference; a failed prime writes half-loaded rows into the parent. | **Fixed at the root.** `CostEngine.prime` marked each chunk's lots loaded (empty flows) *before* spending its work budget. It now marks them only after the budget held, so a prime that overflows leaves nothing half loaded. New AC5 test; mutation-checked (red on the old ordering). |
| 3 | `own_budget(reuse_loaded=True)` is the default and shares mutable dicts, so safety relied on callers passing `False` after a failed prime. `_materials` is copied by value, so a child may rebuild the org-wide material index. | Trap **fixed** (see 2); docstring now says rows are shared by reference and must be whole. The by-value `_materials` is pre-existing (the old `_own_budget` copied it the same way) and only matters past an overflow; rejected as out of scope. |
| 4 | No test that a failed prime's rows are discarded; flipping `reuse_loaded` would pass every assertion. | **Fixed** by AC5, which asserts the lot isn't marked loaded after a failed prime and still costs `actual` on a sharing engine. The `reuse_loaded=False` call sites stay, as they keep a bare engine bare. |
| 5 | After an overflow each later product re-costs its materials with no cache, repeating `engine.lot()` queries for a shared lot. | **Accepted, by design.** A cached success was costed under another product's budget, so reusing it could make a row read ready where that product's own page, on its own budget, would not. Only past 20,000 lots + batches. Stated in the MR. |
| 6 | `price_history` per-lot engines each rebuild the material index when `_materials` is `None`. | Same as 3 (pre-existing, scale-only): **rejected**. |
| 7 | `upsert_by_matchers` now always keeps the stored display, so a caller's corrected wording is dropped; it also still resets `auto_record` / `is_active` from the body. | **Accepted.** Its only callers are the two "Remember this" paths, which pass the purchase's casing; keeping the typed text is the requested behaviour. The `auto_record` / `is_active` reset is pre-existing and untouched. |
| 8 | The settings tests hard-code `== 2` / `== 1` reads and match the table name as a substring. | **Fixed** for margins (the comparison with the same request without an overflow is the proof; the hard-coded 2 is gone). The `== 1` claims are the stated contract ("read once") and stay. |
| 9 | `test_costing_the_list_out_of_budget_leaves_figures_out_not_readiness` patches `own_budget` globally and relies on the figures pass being its first caller. | **Fixed:** it now records every engine `own_budget` hands out and asserts there is exactly one. |

## Also found while testing

The full costing suite on the first run had one red test, `test_costing_the_list_out_of_budget_leaves_figures_out_not_readiness`.
It injected its over-budget figures engine by patching `readiness.CostEngine` and counting
constructions; the figures pass now gets its engine from `own_budget()`, so the injection no longer
fired. Behaviour was unchanged. The injection moved to the new seam; every assertion is kept (and
one added). Mutation-checked: removing the `except TooLargeError` around the figures prime turns it red.

VERDICT (Claude review, not Codex): pass after fixes.
