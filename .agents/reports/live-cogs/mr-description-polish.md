## What this delivers

Three of the four "Still open" engine/rules items (plus one engine hardening found in review) from `.agents/plans/live-cogs-polish.md`, each
with a test that failed on `main` first. The fourth (credit-note tax backfill) is a decision, not
a change. No templates, CSS or JS changed, so there are no screenshots; every response shape is
unchanged.

- **Readiness no longer shares one engine budget across products.** When the shared budget runs
  out, the product that overflowed and every later one is costed on `engine.own_budget()`, as the
  cost-per-unit figures already were (!705). A material row that ran out of budget is never kept
  for the next product. A list row now reads as its own `/readiness/<key>` page does; before, any
  product costed after the overflow could read "not ready" with every price in place.
- **"Remember this" keeps the typed payee.** `upsert_by_matchers` (used by "Remember this" and
  "Not stock") overwrote an existing rule's `payee_display` / `description_display` with the
  purchase's casing. It now keeps the rule's own; a rule saved before the typed form existed (no
  display) takes the purchase's casing. Matching never changed.
- **Costing settings are read once per request.** `CostEngine.own_budget(reuse_loaded=…)` is now
  the one way to get an engine with budgets of its own: it passes on the settings and alcohol
  profiles the first engine read (the two private `_own_budget` copies in `readiness.py` and
  `price_history.py` are gone). `price_history` (history, picker) and `margins` build their
  replacement engines through it, so an overflowed request used to read `costing_settings` 3 to
  10 times and now reads it once.
- **`CostEngine.prime` is atomic about what it marks loaded.** It set each lot's flow list to `[]`
  *before* spending its work budget, so a prime that ran out part-way left lots that looked loaded
  with no flows (a priced lot costing as unknown), and `own_budget` shares those rows by reference.
  They are now marked loaded only after the budget held. Found by the review of this MR; AC5.
- **Credit-note tax backfill: left as is, on purpose.** The cap is 500 notes a sync, which is 13
  Xero requests (batches of 40). Raising it only spends more of the Xero allowance on every sync;
  the other fix, splitting a note's GST across its lines, is the guess the "untracked rather than
  guessed" rule exists to avoid. It converges by itself (oldest first; notes Xero no longer returns
  are marked and never retried). Recorded in the plan with when to revisit.

Not touched, as asked: the multipack pack-size hint and "Paid for by".

## AC → test (`tests/test_costing_polish_followups.py`, all failed on `main`)

| AC | What | Test |
|----|------|------|
| AC1 | After an overflow each listed product reads as its own page (MAX_NODES 2, 3, 4; five products, two sharing a material) | `test_ac1_after_an_overflow_each_product_reads_as_its_own_page_does[2,3,4]` |
| AC2 | A too-large material row is never put in the cross-product cache | `test_ac2_a_material_that_ran_out_of_budget_is_not_kept_for_the_next_product` |
| AC3 | "Remember this" on an existing rule keeps the typed payee (HTTP, one rule updated) | `test_ac3_remember_on_an_existing_rule_keeps_the_payee_as_typed` |
| AC3 | Upsert keeps typed payee and description; a legacy rule takes the new casing | `test_ac3_an_upsert_keeps_both_typed_forms_and_gives_a_legacy_rule_the_new_casing` |
| AC4 | Readiness list overflows and reads `costing_settings` once (was 4) | `test_ac4_readiness_reads_costing_settings_once_however_often_it_overflows` |
| AC4 | Material history, per-lot overflow, reads once (was 4) | `test_ac4_a_materials_history_reads_costing_settings_once_after_an_overflow` |
| AC4 | Materials picker with nothing fitting reads once (was 10) | `test_ac4_the_materials_picker_reads_costing_settings_once_when_nothing_fits` |
| AC4 | Margins report adds no settings read on overflow (was +1) | `test_ac4_a_margins_report_adds_no_settings_read_when_its_lineage_is_too_big` |
| AC5 | A prime that overflows leaves the lot unmarked, and a sharing engine still costs it `actual` | `test_ac5_a_prime_that_runs_out_of_budget_leaves_nothing_half_loaded` |
| AC4 | `own_budget` copies settings and loaded rows without a query; `reuse_loaded=False` starts bare | `test_ac4_an_engine_on_its_own_budget_copies_what_the_first_one_read` |

## Assumptions

- A rule with no stored display (saved before the typed form) takes the purchase's casing on the
  next "Remember this": it is the only typed-looking text available, and it is what the rule read
  as before this change.
- After an overflow readiness does not share material rows across products (no cache), so each
  product reads exactly as its own page does. That repeats `engine.lot()` for a shared material
  once per product, but only past the 20,000-node budget, a scale no tenant is near.
- One existing test changed: `test_costing_the_list_out_of_budget_leaves_figures_out_not_readiness`
  injected its over-budget figures engine by patching `readiness.CostEngine`; that engine now comes
  from `own_budget()`, so the injection moved there. Same assertions, plus one that only the figures
  pass asked for an engine. Mutation-checked red.
- Reports and plan updated in this MR: `.agents/plans/live-cogs-polish.md` (Done / Still open),
  roadmap 8.1f polish line in `docs/source-to-sale-plan.md`.

## Verification

- `tests/test_costing_*.py` on a private migrated DB (no migration in this MR): 575 passed (`env -u ENVIRONMENT PYTEST_XDIST_WORKER=lcpolish uv run pytest tests/test_costing_*.py`), after the first run's one red test was fixed (below).
- `ruff check` / `ruff format` clean on the touched files.
- Costing with no Xero connected is unaffected: every changed path is engine-only or rules-only.

## Codex review (advisory)

**Codex's report could not be read.** `build-review` was launched on this diff (herdr pane
`w29:p3Q`) and exited, but this session is not permitted to read `~/.codex/sessions` or the herdr
pane, so I could not retrieve it. **Codex's verdict is still owed.** In its place I ran Claude's
`/code-review` (high) over the same diff. Full table with dispositions:
`.agents/reports/live-cogs/build-review-polish.md`.

Fixed:
- A failed `CostEngine.prime` left lots marked loaded with no flows, and `own_budget` shares those
  rows by reference (found by review; fixed at the root in `prime`; AC5, mutation-checked red).
- The margins settings test hard-coded a read count; it now compares with the same request without
  an overflow. The figures-pass test now asserts it is the only caller of `own_budget`.

Rejected, with reasons (all in the report):
- Readiness's up-front `prime` can still overflow and 500 the list: on `main` too, a different
  failure, now written into the plan's "Still open".
- `_materials` is copied by value into `own_budget` engines, so a per-lot engine may rebuild the
  material index: the old private helpers did the same; only past an overflow.
- Re-costing a shared material per product after an overflow: deliberate, so a list row reads as
  its own page does.
- `upsert_by_matchers` resets `auto_record` / `is_active` from the body: pre-existing, untouched.

An existing test also went red on the first full run
(`test_costing_the_list_out_of_budget_leaves_figures_out_not_readiness`): it injected the
over-budget engine through `readiness.CostEngine`, a seam that no longer exists. Fixed at the seam;
assertions kept.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
