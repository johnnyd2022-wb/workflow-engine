# Build review: multipacks (LIVE-COGS-PACKS)

Reviewer: `/code-review high` on `git diff origin/main...HEAD` (advisory). The Codex launcher was
unavailable: `agent_launch.py` refuses to run outside Herdr (`HERDR_ENV != 1`). The whole feature is
reviewed together at the end, so a Codex pass is still to come.

| # | Finding | Disposition |
| --- | --- | --- |
| 1 | Any counted unit (pallets, kegs) taken from a lot of cases was divided by the pack count | **Fixed.** Only single-item words (unit, each, bottle, can, jar, pc, piece) use the count path. Tests: `test_only_single_items_come_out_of_a_multipack_lot` |
| 2 | Clearing or breaking the pack left the Total paid hint stale | **Fixed.** `onChange` fires on every update. Browser: `test_clearing_the_pack_clears_the_cost_hint…` |
| 3 | A kg item named "… 25 kg bag" got a visible, submitted pack (hidden state depended on event order) | **Fixed.** Auto-fill happens only for counted units, before the hidden state is set. Same browser test |
| 4 | Client `parsePack` regex differed from the server's (`700ml x 6 pack`, `milliliters`) | **Fixed.** Lookahead and unit list now match `_PACK_RE`. Not separately tested beyond the existing hint table |
| 5 | Stocktake and sales availability treat counted units as whole numbers | **Rejected for this MR, documented.** Spec "Out of scope": raw cases aren't sold, and stocktake counts in bottles need their own UI. Follow-up |
| 6 | Costing engine `_unit_factor` / `_quantity_in` ignore packs | **Rejected.** They convert output flows and site transfers (lot unit to lot unit); output lots carry no pack. Consumption flows are written already converted into lot units, which is what the engine reads |
| 7 | `settle_take` could snap a zero take or a loose tolerance | **Fixed.** A take of 0 is left alone; tolerance tightened to 0.0001 × containers, capped at 0.05. Test: `test_settle_take_leaves_a_zero_take_alone` |
| 8 | "12 ounces", "3 gallons", "2 tonnes", "12 fl oz" read as a bare count | **Fixed.** Measure words matched by stem in Python and JS. Parametrised in `test_a_count_with_no_size_needs_more_than_one` |
| 9 | A pack count on a lot of bottles inverted conversion for "cases" | **Fixed** by #1 |
| 10 | Duplicate 8.1i entry in the plan | **Fixed** in the working tree (one entry); MR number filled in at MR time |

Found while fixing #2: blanking the field by hand re-filled it from the name, so a pack could never be
cleared; and a blank pack made the price hint fall back to the name. Both fixed (manual blank sticks;
blank means no pack) and pinned by the same browser test.
