## 8.1c-1 build contract — recording purchases into stock

8.1c is split so each MR stays small: **8.1c-1** (this) = line state, allocations, the record /
link / not-stock / skip / reopen / refund / review actions, the purchases list API, and what
happens when Xero changes a line that has been recorded. **8.1c-2** = purchase rules, "remember
this", apply-rule and bulk actions, historical runs. No UI (8.1d).

**Tables (migration `costing_allocations_001`).**

- `purchase_lines` gains `state` (`open` | `partly_recorded` | `recorded` | `skipped` |
  `not_stock`, default `open`), `not_stock_amount` (NUMERIC(18,4), default 0, same sign as the
  line), `review_reason` (null | `amount_changed` | `recoded` | `deleted_in_xero`).
- `purchase_allocations`: `id`, `org_id`, `purchase_line_id` (composite FK, RESTRICT),
  `inventory_item_id` (composite FK to `inventory_items`, RESTRICT — a lot with an allocation
  can't be deleted silently), `cost_flow_id` (composite FK to `cost_flows`, null only for a
  refund), `amount` (signed as the line), `quantity` (≥ 0, lot unit; 0 for a refund), `status`
  (`active` | `orphaned`), `created_by_user_id`, `created_at`, `updated_at`. Check: refund ⇔
  `amount < 0` ⇔ `cost_flow_id IS NULL` ⇔ `quantity = 0`. Unique `(org_id, purchase_line_id,
  inventory_item_id)`.

**Engine (8.1a) changes.** Price facts = active `lot_cost_entries` + active or orphaned
allocations. A flow's price = Σ its positive allocations and its active flow entry (quantity
and amount summed); invariant enforced at write under a lock on the lot: Σ quantity ≤ the
flow's quantity. Orphaned allocations make that part `estimated`. Negative allocations are
refunds, applied once as specified in "Price facts". Recording or linking a purchase to a lot
**deactivates every active manual entry on that lot** (flow and whole-lot): a purchase replaces
a typed price (round-2 gap 4).

**Line arithmetic** (under a row lock on the line): `open = amount_ex_tax − Σ active
allocations.amount − not_stock_amount`; all same sign; `|Σ allocations| + |not_stock| ≤
|amount|`. State is derived after every action: `recorded` when open = 0 and something was
allocated; `not_stock` when not_stock = amount; `partly_recorded` when something was allocated
and open ≠ 0; else `open` — except `skipped`, which only Skip sets and any later action clears.
A line whose document `needs_rate` (null amount) accepts no action (400).

**Tabs (round-2 gap 14) — one rule, first match wins:**
1. `review_reason` set → **To record** (whatever its treatment, state, document status or
   superseded flag).
2. Otherwise only live lines (`superseded_at` null) on active documents with `treatment =
   stock` and a non-null amount appear; then by state: `open` / `partly_recorded` and dated on
   or after `start_date` → **To record**; `recorded` → **Recorded**; `skipped` → **Skipped**;
   `not_stock` → **Not stock**.
Everything else appears in no tab.

**Actions (all `POST /api/core/costing/purchases/<line_id>/…`, JSON body, `Idempotency-Key`
via the existing `idempotent_write`).**

- `record` `{rows: [{name, inventory_type: raw_material|final_product, quantity, unit, amount,
  supplier_batch_number?, expiry_date?, location_id?, site_id?}], rest: "not_stock"|"later"}`:
  in one transaction, each row creates a lot through `create_inventory_item` (supplier = payee,
  purchase_date = document date) and an allocation on its `created` flow for the row's amount
  and quantity. Row amounts are ≥ 0 and their total ≤ open (400 otherwise, nothing written);
  any remainder becomes `not_stock_amount` (rest = not_stock) or stays open (later). Needs
  `costs.manage` **and** `inventory.adjust`.
- `link` `{lots: [{inventory_item_id, quantity?, amount}], rest}`: allocations to existing lots.
  A lot qualifies when it's this org's, `raw_material` or `final_product`, editable (only
  direct inflows, not customer-owned), and has no active allocation; quantity defaults to the
  lot's `created` flow quantity and must fit the flow. Deactivates the lot's manual entries.
  Needs `costs.manage` **and** `inventory.adjust`.
- `GET /purchases/<line_id>/candidates`: qualifying lots whose purchase date (else created_at
  date) is 3 days before to 14 days after the document date, ranked: supplier = payee
  (normalised) first, then date distance, then created_at. Includes lots with a manual price.
- `refund` (refund lines only) `{lots: [{inventory_item_id, amount}]}`: negative allocations,
  quantity 0, null flow, each amount < 0, total ≥ the line's open amount (it's negative).
- `not_stock`: `not_stock_amount += open`. `skip`: state `skipped`. `reopen`: clears
  `not_stock_amount` and `skipped` (allocations untouched). All `costs.manage`.
- `review` `{action: keep|unlink}`: `keep` clears `review_reason`; `unlink` deletes the line's
  allocations (lots stay) and clears it. `costs.manage` (+ `inventory.adjust` for unlink).
- `PUT /purchases/<line_id>/allocations` `{allocations: [{id, amount, quantity?}]}`: edit
  amounts on existing allocations (the review "edit amounts"); same arithmetic.

`GET /purchases?tab=to_record|recorded|skipped|not_stock&from=&to=` → cards `{line_id, document
{payee, date, reference, kind, status}, description, account, amount, open, state,
review_reason, allocations[]}` and per-tab counts. `costs.view`.

**When Xero changes a line later** (applied inside the 8.1b upsert, through one function
`apply_line_change(line, before)` in `costing/actions.py`):

| Change | Line with no allocations | Line with allocations |
| --- | --- | --- |
| amount changed (LineItemID line updated in place) | nothing extra | active allocations and `not_stock_amount` rescaled by new ÷ old (4 dp, remainder to the largest allocation); quantities unchanged; `review_reason = amount_changed` |
| treatment no longer `stock` | nothing (leaves the tabs) | `review_reason = recoded`; allocations kept |
| document voided | nothing | allocations → `orphaned`; `review_reason = deleted_in_xero` |
| line superseded (positional change or dropped) | nothing | allocations → `orphaned`; `review_reason = deleted_in_xero`; the replacement line is a new card |

Rescaling never crosses zero: a new amount of 0 or with the other sign orphans instead.

**ACs (8.1c-1).** AC5–AC9, AC11, AC12 (refund), AC30, AC34, AC35 above, adjusted: AC9's
candidates *include* a lot with a manual price; plus:
- AC74: record rows totalling more than open → 400, nothing written; `rest=later` leaves
  `partly_recorded` with the remainder open; `rest=not_stock` → `recorded`.
- AC75: a link whose quantity exceeds the flow → 400; linking deactivates both a flow entry and
  a whole-lot entry; the lot's cost becomes the purchase's.
- AC76: tab placement for every row of the tab rule, one test each (incl. review on a voided
  document and on a superseded line).
- AC77: amount change rescaling (two allocations $60/$30 on $90 → $99 gives $66/$33), and to 0
  → orphaned.
- AC78: `record` / `link` 403 for a custom role with `costs.manage` but not `inventory.adjust`;
  `skip` / `not_stock` allowed; `costs.view` only → 403 on every POST.
- AC79: every action on another org's line → 404, nothing changed; candidates never list
  another org's lots.
- AC80: replaying a `record` with the same Idempotency-Key creates nothing new; a line on a
  `needs_rate` document → 400.
