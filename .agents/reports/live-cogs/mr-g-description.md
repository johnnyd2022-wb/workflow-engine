## What it delivers (live-cogs 8.1g, spec Phase 3)

Production › Costs now answers "what is my stock worth, and how does that tie to Xero?".

- **Stock value now**: on-hand × unit cost per lot, plus the unabsorbed pool of batches still running; grouped raw / in production / work in progress / finished, with actual / estimated / partly-costed dollars. Uncosted lots are listed with **no value** and counted; the total then reads "At least $X". Never $0 for unknown.
- **Snapshots** (`stock_value_snapshots` / `_lines` / `_movements`, migration `costing_stock_001`): a month-end snapshot is taken automatically on the first Xero sync after a month ends (NZ time), or on the first costing read for an org with no Xero; a manual "Take a snapshot" button (`costs.manage`, 20 a day). Figures are held fixed; later cost changes show as "changes since close".
- **As at the cutoff**: a late snapshot reverses later sales / wastage / corrections / new lots out of today's quantities (same arithmetic as the stock-integrity check), so a snapshot taken on the 3rd still reads the 31st.
- **Xero bridge** (`GET /api/core/costing/bridge`): P&L fetch (`accounting.reports.profitandloss.read` added to `XERO_SCOPES`); tie-out of Xero's stock accounts against recorded purchases, listing every stock-account line not recorded as stock plus "other entries in Xero (journals)"; stock roll-forward `opening + purchases − closing = cost that left stock` split into sold, wasted, samples, corrections, lost in production, estimate changes, other — from movements stored when the later snapshot was taken, so it sums exactly. Duty and overhead shown beside it. With no Xero the roll-forward still shows and the page says Xero isn't connected.
- **CSV** for the accountant's Closing Stock entry (unknown cost cells blank, formula-injection escaped).
- Roadmap 8.1g ticked in `docs/source-to-sale-plan.md`; spec section "8.1g build contract" added first.

## AC → test

| AC | Test |
|---|---|
| AC129 (=AC49) stock value, world W | `test_ac129_stock_value_now_for_world_w` |
| AC130 unknown never $0; partial floor | `test_ac130_unknown_cost_is_never_zero_and_partial_is_a_floor` |
| AC131 empty/finished-batch/customer-owned excluded | `test_ac131_empty_lots_and_finished_batch_leftovers_are_not_stock`, `test_ac131_customer_owned_material_is_left_out` |
| AC132 snapshot held fixed | `test_ac132_manual_snapshot_freezes_the_figures` |
| AC133 automatic month end (read / sync / failure) | `test_ac133_*` (3) |
| AC134 as-at reconstruction | `test_ac134_later_movements_are_reversed_out_of_a_late_snapshot` |
| AC135 missed months, no empty first | `test_ac135_two_missed_months_…` |
| AC136 permissions, isolation, cap | `test_ac136_view_manage_isolation_feature_and_daily_cap` |
| AC137 CSV | `test_ac137_csv_export_…` |
| AC138 scope + P&L parse + client | `test_ac138_*` (2) |
| AC139 (=AC51) tie-out | `test_ac139_*` (2) |
| AC140 (=AC50) roll-forward to the cent | `test_ac140_opening_plus_purchases_minus_closing_is_what_left_stock` |
| AC141 production loss | `test_ac141_…` |
| AC142 estimate change | `test_ac142_…` |
| AC143 closed month fixed, changes since close | `test_ac143_…` |
| AC144 needs two snapshots; no Xero | `test_ac144_…` |
| AC145 permissions, needs_reconnect, failed, duty | `test_ac145_*` (2) |
| AC146 migration | `test_ac146_*` (2); upgrade → downgrade → upgrade also run on the private `lcg` DB |
| AC147 page (phone + desktop, managers only) | `tests/e2e/test_costing_stock_value_browser.py`, `test_ac147_…` |

Run: costing + Xero + access-policy suites on the private DB: 697 passed (plus the new e2e / owned tests).

## Assumptions

- "Org timezone" is NZ (orgs have no timezone setting; costing already uses NZ).
- B (purchases) is by Xero document date; stock added by hand, at an estimated cost, or bought in another period lands in `estimate_changes` (`added_other`).
- Manual snapshots are cut by timestamp but compared with Xero by date; two snapshots on the same day report `same_day` instead of a Xero comparison.
- A snapshot's costs are those known when it is taken; sale / sample / wastage kinds come from the entity-event and wastage ledgers, and any decrease they don't explain is `variance`. `rounding` closes the identity and is surfaced if over a cent.
- Existing Xero connections must reconnect to grant the new P&L scope (`needs_reconnect` until then).
- Snapshots can't be slotted before an earlier one; a manual snapshot first closes any ended month.

## Codex review (advisory)

Not run: Codex hit its usage limit (retry 17 Nov). Prompt and a note are in `.agents/reports/live-cogs/build-review-g.{prompt.md,md}`; no findings fixed or rejected.

## Screenshots (desktop, laptop, phone; light and dark)

![desktop-stock](/uploads/ed386276a61dc7fa8811fba2e1787064/desktop-stock.png)
![desktop-bridge](/uploads/e7becb8a9956df4dde5accca3a0bb287/desktop-bridge.png)
![laptop-stock](/uploads/a31119fa766c48c31f7275c2ef9f972c/laptop-stock.png)
![phone-stock](/uploads/9e51117e7f376128f8fce7f7b932e045/phone-stock.png)
![phone-dark-stock](/uploads/20d5a27ac5910d9dc634797f876d2aeb/phone-dark-stock.png)
![desktop-dark-stock](/uploads/ae3e9b93638497e353d18ab1a6b1c1db/desktop-dark-stock.png)

Seeded UI org lives in the private `lcg` DB (not the shared one).

🤖 Generated with [Claude Code](https://claude.com/claude-code)
