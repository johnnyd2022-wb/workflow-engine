## What this delivers

Roadmap **8.1h — Overheads into cost** (live-cogs spec Phase 4), **opt-in per org, off by default**. With it off, every cost figure, test and response is exactly what it was (the new payload keys exist only when an org has switched it on).

When an org ticks **Add overheads to what a batch costs** in Costs › *How costs are worked out*:

- **Overhead rates.** A name (Rent, Labour, Power), an amount, a basis — **per litre of finished product** or **per batch** — and an effective-from date, kept on a new **Overheads** section of the Costs page (bottom-sheet add/edit, remove). A batch finished on or after the date takes the rate; a later row with the same name replaces it; a $0 row ends it.
- **Batch overheads land in the batch pool** when it completes, at the step that makes finished product, and are split between that step's outputs by the same weights as the materials (cost share, quantity or litres). Worked example: a 200 L batch on $1,000 of materials with Rent $0.50/L + Labour $40/batch costs **$5.70/L** ($5.00 materials + $0.70 overheads).
- **Freight as landed cost.** A freight line on a purchase document (an overhead line saying freight/courier/postage…, or a Purchases card the user marks **It's freight**) spreads **by value** over the stock recorded from the **same** document. A $300 purchase of $250 stock + $50 freight prices the $150 lot at $180 and the $100 lot at $120.
- **The split is shown**: batch cost card (Materials, Overheads, per-bottle "$4.50 materials + $0.75 overheads", the lines the batch took), lot cost panel ("Includes … materials · … overheads per bottle") and the Margins page (cost, materials and overheads per month; summary "of it overheads").
- **The 8.1g bridge stays honest**: stock value rises by the overhead a batch or a freight line adds without a purchase behind it, so the roll-forward shows it as its own component, **Overheads added to stock** (a stored movement, so a closed month stays fixed), instead of a negative production loss or an "estimate change". The batch pool the stock value carries stays materials only; the Xero overhead total is untouched and sits beside `absorbed {batch, freight}`. Only for an org that opted in.
- **Readiness is untouched**: overheads never make a product "not ready".
- **Unknown is never $0**: a per-litre rate on bottles whose pack size isn't known is not applied and not guessed — the batch reads *partial* with the reason on the card.
- **No Xero needed**: rates are typed; a batch's overheads need nothing else. Freight can also be a card marked by hand.

Spec: `.agents/specs/live-cogs-overheads.md` (worked examples, ACs OV1–OV20) and the "8.1h build contract" appended to `.agents/specs/live-cogs.md`. Migration `costing_overheads_001` (one head, off `costing_stock_001`; reversible; also widens 8.1g's movement-kind check; downgrade refuses while rates, freight marks or `overhead_absorbed` movements exist).

## Acceptance criteria → tests

| AC | Test |
| --- | --- |
| OV1 off by default, nothing changes (byte-for-byte) | `test_ac_ov01_off_by_default_and_rates_change_nothing` |
| OV2 the switch | `test_ac_ov02_setting_round_trip_and_validation` |
| OV3 rates CRUD and validation | `test_ac_ov03_rates_crud_and_validation` |
| OV4 worked example, no Xero | `test_ac_ov04_worked_example_200_litre_batch_without_xero` |
| OV5 effective dates | `test_ac_ov05_effective_dates` |
| OV6 running batch | `test_ac_ov06_running_batch_has_no_overheads_yet` |
| OV7 once, on finished product | `test_ac_ov07_overheads_land_once_on_finished_product` |
| OV8 bottles, Library stock, unknown pack size | `test_ac_ov08_bottle_litres_library_and_unknown_pack_size` |
| OV9 joint outputs | `test_ac_ov09_overheads_follow_the_cost_share` |
| OV10 carried into a later batch | `test_ac_ov10_overhead_carries_into_a_later_batch` |
| OV11 freight by value | `test_ac_ov11_freight_spreads_by_value_within_the_purchase` |
| OV12 freight boundaries | `test_ac_ov12_freight_boundaries` |
| OV13 mark a line as freight | `test_ac_ov13_mark_a_line_as_freight` |
| OV14 readiness unaffected | `test_ac_ov14_readiness_is_unaffected` |
| OV15 margins split | `test_ac_ov15_margins_show_the_split` |
| OV16 isolation and permissions | `test_ac_ov16_tenant_isolation_and_permissions` |
| OV17 migration | `test_ac_ov17_migration_shape` (+ upgrade/downgrade/upgrade run on the private DB) |
| OV20 absorbed overhead is its own bridge component; off = 8.1g's | `test_ac_ov20_*` (`tests/test_costing_overheads_bridge.py`, 3 tests) |
| OV19 no query per batch | `test_ac_ov19_primed_costs_do_not_query_per_batch` |
| OV18 browser | `tests/e2e/test_costing_overheads_browser.py` (3 tests, run locally) |

The failing tests were committed first (17 red; the OV20 bridge tests were committed red separately), then the implementation (all green).

## Assumptions (each can be overturned in review)

- **H1** Per litre = litres of finished-product **volume**, not LAL (rent has nothing to do with strength). LAL could be a third basis later.
- **H2** Overheads attach to the batch that makes finished product, taken when it completes; a WIP-only batch takes none (no double counting through a chain); a running batch has none yet.
- **H3** Freight spreads over one document's *recorded* stock by value; it re-spreads as more of that document is recorded; a freight line on another document is never matched by guess.
- **H4** Freight counts as overhead in the split; its lot's status is unchanged.
- **H5** An unmeasurable per-litre rate makes the batch partial rather than being skipped silently.
- **H6** Absorbed overhead is its own roll-forward component (above), not a production loss or an estimate change.
- Rates are in force by the **NZ calendar date** the batch completed.

## Follow-ups (not in this MR)

- A Costs-list row for a product whose latest batch has unmeasurable litres still says "Full cost" (readiness is about materials, by design) with no per-unit figure.
- Freight lines Xero codes to an account without freight wording on a non-stock treatment can't be marked from the Purchases page (it lists stock lines only); change the account treatment or its wording.

## Review findings

Advisory Claude review (Codex is out of quota); full table in `.agents/reports/live-cogs/build-review-h.md`.
Fixed: readiness ignores an overhead-only partial; the batch card's Materials excludes carried freight/overhead; the "In use" copy matches the fall-back-to-earlier-rate behaviour; a freight line can't be skipped; NZ-date, skip and readiness tests added; bridge integration (OV20).
Accepted: a bulk batch typed final product that is then bottled would take overheads twice (intermediates are WIP in Core); per-litre amounts are shared over a step's outputs by the normal weights; rate writes send no idempotency key from the UI (409 on duplicates).

## Screenshots

Desktop, laptop and phone, light and dark (Costs + Overheads section, settings and rate sheets, batch card incl. running / unknown-litres states, lot panel, margins, Purchases freight) were shot with `scripts/ui_shots.py` and read; none left to fix. Browser tests: `tests/e2e/test_costing_overheads_browser.py`.
