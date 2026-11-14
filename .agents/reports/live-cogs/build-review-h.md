# Build review — 8.1h overheads into cost (advisory)

Codex is out of quota, so this is a Claude review (subagent; the `code-review` skill itself hit a
rate limit, so it was a hand-run targeted hunt over `git diff origin/main...HEAD`). No tenant
isolation holes found (every query in `overheads.py`, the engine's new loads and the routes filters
`org_id`; permissions come from the `costing.*` policy). Off-state payloads unchanged.

| # | Finding | Verdict |
| --- | --- | --- |
| 1 | An overhead-only `partial` on a finished lot could flip a downstream product to "not ready" if that lot is read as a material | **Fixed.** Readiness treats a lot whose only gap is `overhead_litres_unknown` (no missing lots) as costed. Test `test_ac_ov14b_…` (passes with and without — readiness walks through produced lots — but pins it) |
| 2 | Batch card "Materials" included freight and carried overhead beside an "Overheads" figure for this batch only | **Fixed.** On a finished batch, Materials = Σ outputs' known − Σ outputs' overhead |
| 3 | Rate sheet "In use: off … stops it being added" was wrong: an inactive row falls back to the earlier rate | **Fixed (copy).** Now says batches use the earlier rate and to add a $0 rate to stop one |
| 4 | Bulk-then-bottle chain typed `final_product` at both stages takes overhead twice | **Accepted, documented** in the spec (H2): overheads assume intermediates are WIP (what Core produces on non-terminal steps) |
| 5 | A per-litre amount is shared over all of the step's outputs (by-products, litres-split Library stock), so one output's overhead/L can differ from the rate | **Accepted, by design** (same weights as materials; spec says so) |
| 6 | Bridge/stock value ignore absorbed overhead | **Fixed** in this MR (AC-OV20, `tests/test_costing_overheads_bridge.py`): absorbed overhead is its own roll-forward component |
| 7 | Test gaps: NZ-date boundary, skip on a freight line, migration round trip | **Fixed** (`test_ac_ov05b_…`, `test_ac_ov13b_…`); round trip run by hand (upgrade → downgrade → upgrade on the private DB) |
| 8 | Skipping a freight-marked line left the freight flag on | **Fixed.** Skip refuses a freight line; Undo first |
| 9 | Small off-state differences (settings error text, margins phone CSS, card alignment, one settings query on the Purchases page) | **Accepted**: no figure or JSON body changes |
| 10 | Rate writes send no Idempotency-Key from the UI; focus lost after Remove; "starts" label uses the browser date | **Accepted** (the unique index returns 409 and the form locks while saving; low severity) |
