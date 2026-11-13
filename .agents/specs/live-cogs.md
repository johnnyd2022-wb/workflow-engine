# SPEC: live-cogs
status: v4 (round 2 engine gaps resolved; 8.1a is the first build)
name: Live batch & bottle cost
slug: live-cogs
blueprint: new slice `app/features/costing/`, attached through `register_routes(core_bp)`;
Xero fetch/sync additions stay in `app/features/crm/`
url_prefix: `/api/core/costing/*` (JSON), pages under `/core/costing/*`
roadmap: `docs/source-to-sale-plan.md` 8.1 (Phase 8); this build is 8.1a–e
source: `.agents/plans/live-cogs-context-pack.md` (2026-11-10, `origin/main` @ `1181748b`)

## Description

Give every lot, batch and bottle a real cost, live, with no mandatory setup. This is a Biz-E
product feature for any NZ alcohol producer, however they buy: card spend with no detail, bills
with line items, bought-in finished goods, or receipts with no Xero record at all. Whistlebird
is the first tenant and the worked example, not the design target.

1. Biz-E pulls spending from Xero (card/bank "spend money" transactions and bills) and decides
   from the Xero account each line is coded to whether it is a stock purchase.
2. Each stock purchase appears as a card on the **Purchases** page. Recording it creates (or
   links) inventory lots with quantity, supplier batch number and expiry, and the purchase
   amount becomes the cost of those lots. This is also the reminder to load stock at all.
3. Cost flows through production automatically: what a batch consumed, at each lot's unit cost,
   spread over what the batch produced. Cost per bottle is visible while the batch is still
   running and final when it's bottled.
4. Sales already matched to batches (`crm_sales_fifo_allocations`) pick up that batch's cost, plus
   excise duty from the compliance module, giving margin per product over time.
5. A bridge report explains the difference between Biz-E's cost of goods sold and Xero's
   cost-of-sales accounts, and gives the accountant a closing stock value.

## Why this wins

Production systems generally make costing depend on setup done first: an item master, purchase
orders, goods receipts, standard costs. Small producers don't do that work, so their costs stay
in a spreadsheet. (General market knowledge — run `competitor-watch` on Distillx5, CraftedERP
and Orchestrated before using any comparison in marketing.) This design competes on five things:

1. **Starts from the bank feed, not from data entry.** The purchase is already in Xero; Biz-E
   brings it to the user as a card to confirm, the way Xero's own bank reconciliation does.
2. **Receiving stock and costing it are one action.** Recording a purchase captures quantity,
   batch number and expiry — the traceability record — and the cost comes free.
3. **It learns.** A supplier that always sells the same thing becomes a one-tap confirm with
   only batch number and expiry to type.
4. **Honest numbers.** A cost is either complete or says exactly which inputs are missing and
   links to fixing them. It is never silently wrong.
5. **Duty and the accountant are covered.** Margin includes excise as lodged, and the stock
   value and Xero bridge answer the accountant's questions without a spreadsheet.

Three rules hold everywhere:

- **Unknown is never $0.** Every cost carries a status: `actual`, `estimated`, `partial`
  (a floor — some input has no cost) or `unknown`.
- **Cost is derived, not journalled.** Purchases, manual entries and production records are the
  facts; lot and batch costs are a cache rebuilt from them whenever a fact changes.
- **Accounting changes never delete stock.** If Xero edits or deletes a purchase, the lots stay
  and the cost is flagged for review.

## Decisions on the ten design questions

### Q1. Costing method — actual lot cost, with averages as a view
Each lot carries its own actual unit cost, traced through real lineage (specific
identification). Sales cost uses the existing FIFO sale→lot allocations. Reasons: lineage and
FIFO matching already exist at lot level, so anything coarser throws information away; batch
cost per bottle is the founder's headline number and only lot costing gives it.

"Average over time" is a report view, not the stored method: per material, a weighted average
purchase cost by month; per product, cost per unit by batch with a rolling average (Phase 2).

A lot that receives stock more than once (quantity added to an existing lot) is a small
weighted pool: unit cost = Σ priced inflow amounts ÷ Σ priced inflow quantities, over its
lifetime; an inflow with no price of its own takes the pool's price and makes the lot
`estimated` (see the roll-up).

### Q2. Purchase → lot link — rules pre-fill a card; the user confirms
See "Deciding what is a stock purchase" and "The Purchases page" below. In short: the Xero
account decides whether a purchase is stock; purchase rules pre-fill what it is (material,
quantity, split); the user confirms on a card, which creates lots or links lots already entered
by hand. One amount across several lots is split by amounts typed from the receipt, pre-filled
where Biz-E knows the price, with any remainder explicitly marked "not stock".

Recording with no user involvement is off by default: card transactions carry no quantity or
item, so a silent match would be a guess presented as fact. A rule can opt in to auto-record
(Phase 2) only where nothing needs asking.

### Q3. Late or changed costs — recompute downstream
Costs are recomputed, not snapshotted with adjustment entries. When a purchase is linked late,
edited or deleted, the affected lots and everything made from them are recalculated. Reasons:
the business is small and the graph shallow, so recompute is cheap; a late receipt should fix
last month's batch cost, not create a mystery adjustment this month.

The price is that past-period figures can move. Phase 3 adds month-end snapshots so a closed
month's reported figures stay fixed and later changes show as "changes since close".

### Q4. Joint outputs and yield — cost follows the step, split by quantity unless told otherwise
Cost is pooled per execution and handed to output lots step by step (algorithm below). The
exact split rule (`split_weights`) is in "Cost roll-up"; in short: a cost share configured on
the step's output definition (`cost_share`: a percentage, or `byproduct`) is honoured first;
outputs without one share the rest by quantity when their units are compatible, otherwise it
all goes to the primary output with `split_assumed = true`. Library stock remainders take no
share in Phase 1 (ASSUMPTION A9). Splitting by litres of finished product (bottles × size) is a
Phase 2 option.

Normal losses (angel's share, spillage inside a step) are absorbed automatically, because the
whole pool is spread over what actually came out. Cost consumed after a batch's last output
(or by a batch that never produces one) stays in `cost_so_far` — shown live while the batch
runs, and as a production loss once the batch is complete — never silently dropped.

### Q5. Missing data — a cost is complete or it says what's missing
A batch or product cost is shown as **the** cost only when every input has a cost. Until then
it is shown as **Incomplete**: "5 of 7 inputs costed", the subtotal so far labelled as such,
and the missing inputs listed by name, each with a link to find its purchase or enter a price.
Margins are shown only for products whose cost is complete.

A **cost readiness** view lists every final product (distinct normalised names of
`final_product` lots) and, for each, the materials it needs and whether each has a cost, so an
owner starting from scratch can see exactly what's left to map. For a product, the materials
are the raw-material and bought-in inputs reached by walking back through `cost_flows` from its
most recent batch (the latest execution that produced a lot of that name), through any
work-in-progress, to lots with no production inflow. A material is costed when the lot that
batch actually consumed has status `actual` or `estimated`. A product with no batch yet uses
the material names declared in its process's step inputs, each costed if any lot of that
material has an actual cost. The product is ready when every material is costed.

How an input gets a cost:

- **Actual**: a purchase recorded or linked to the lot, or a price typed on the lot.
- **Last known price** (status `estimated`): the lot has no purchase of its own, but the same
  material (same normalised name, compatible unit) has been costed — use the most recent price
  on or before this lot's date, else the earliest after. This is what makes "new purchases going
  forward" work: once each material has been bought once, older stock of it is costed too. It
  is an org setting, on by default (ASSUMPTION A3); with it off, only actual costs count as complete.
- **Free**: the user marks a lot as costing nothing (gift, foraged). An actual cost of zero.
- **Customer-owned** material (`contract_customer_id` set) is zero, automatically.
- **Unknown**: none of the above. Makes everything made from it incomplete.

Every figure carries its status, the dollar split between actual and last-known-price, and the
missing inputs.

### Q6. Duty — included in margin, taken from the excise module, kept out of lot cost
Excise is charged on removal, so it is a cost of the **sale**, not of the batch. Lot cost is
production cost only (materials and packaging). The margin report adds duty per sale line from
the nz_alcohol module's own removal calculation, so the figure equals what gets lodged. In
Phase 2 the batch cost card also shows "duty if sold today" from the same module, so the owner
sees a landed cost per bottle before selling. Phase 1 shows no duty.

Spending coded to the Xero duty account is classified `duty`: never offered as stock, used only
as a check line in the bridge. If the compliance module is off for an org, duty shows as "not
tracked" rather than being guessed.

### Q7. Reconciliation to Xero — a bridge, not a match
Xero expenses purchases when bought; Biz-E costs them when sold. The report shows the walk
between the two for a period (see "Xero bridge"). Biz-E also produces a stock-on-hand value by
category that the accountant can use as Closing Stock. Biz-E does **not** post journals to Xero
(ASSUMPTION A5).

### Q8. Reports and where they live
No new top-level tab (Home / Production / Compliance stay).

| Surface | Where | Phase |
| --- | --- | --- |
| Purchases page (reconcile-style cards, historical runs) | Production › Purchases, plus a Home card and a notification | 1 |
| Purchase rules (mapping settings) | beside the existing Xero product mappings | 1 |
| Cost readiness per product | Production › Costs page, linked from every Incomplete figure | 1 |
| Lot cost panel (unit cost, source, edit) | Inventory lot detail | 1 |
| Batch cost card (inputs, cost so far, cost per unit, Incomplete + missing inputs) | Production › batch detail | 1 |
| Product margins over time | Sales area, beside existing revenue reports | 2 |
| Material price history; duty if sold today on the batch card | Production › Costs page | 2 |
| Stock value now / at month end | Production › Costs page | 3 |
| Xero bridge | Production › Costs page | 3 |

Page layout goes through `page-design`; this spec fixes content, not styling.

### Q9. Rollout
Per-org feature subscription `costing_enabled` (existing `FeatureSubscription` pattern). Manual
lot costs and the roll-up work without Xero; the purchases page needs Xero connected with the
new scopes. Not in production, so scopes are simply added and orgs reconnect.

On switching on, the owner picks one of two starts, and can change their mind at any time:

- **New purchases from today** (default). Only purchases from now on are presented.
- **Load history from a date.** Opens a historical run from that date (see "Historical runs").

### Q10. MVP cut
Phase 1 is bank-transaction sync, default account rules, the purchases page with rules and
historical runs, manual cost, last-known price, the roll-up, readiness and the batch cost card. Full phasing is at the end.

## Data model

All tables: `TenantScoped`, `org_id` not null, `UniqueConstraint(org_id, id)`, composite
`(org_id, …)` foreign keys in the style of `inventory_items`. Money is `NUMERIC(18,4)` in the
org's base currency, **excluding GST** (ASSUMPTION A2); unit costs are `NUMERIC(18,6)`.
All migrations are additive and reversible (downgrade drops only the new tables/columns, and
refuses while typed prices exist, since those are user data with no other copy — repo convention).
Nothing is added to `inventory_items`.

Facts only. **Facts** (`purchase_*`, `lot_cost_entries`, `cost_flows`) are written by user
actions, sync and Core hooks, and are never derived from each other. Every cost is a pure
function of facts, computed on read (see "Recompute"). There are **no cost cache tables in
Phase 1**; a cache can be added later (Phase 3 stock value) as a pure optimisation without
changing any figure.

### `xero_accounts` (crm slice — chart of accounts cache)
`id`, `xero_account_id`, `code`, `name`, `type` (Xero type, e.g. `DIRECTCOSTS`, `EXPENSE`),
`account_class`, `status`, `last_synced_at`. Unique `(org_id, xero_account_id)`.

### `purchase_documents` (costing slice — source-agnostic header)
| Column | Notes |
| --- | --- |
| `source` | `xero_bank` \| `xero_bill` \| `xero_bill_credit` \| `manual` |
| `external_id` | Xero BankTransactionID / InvoiceID; unique `(org_id, source, external_id)` — the upsert key |
| `kind` | `spend` (money out) \| `refund` (money in on an expense account) \| `bill` \| `credit` |
| `payee_name`, `xero_contact_id` | |
| `document_date` | date; period boundaries use this in the org's timezone |
| `reference` | |
| `currency_code`, `currency_rate` | amounts are converted to base currency on sync |
| `status` | `active` \| `voided` (Xero DELETED / VOIDED) |
| `total_ex_tax`, `total_tax` | |
| `external_updated_at`, `last_synced_at` | |

Bills are stored here, **not** in `xero_invoices`, because every existing reader of
`xero_invoices` assumes sales.

### `purchase_lines`
| Column | Notes |
| --- | --- |
| `document_id` | composite FK, cascade |
| `line_key` | Xero LineItemID when present, else `pos:<n>` (1-based position). Unique `(org_id, document_id, line_key)` — the upsert key |
| `description`, `item_code`, `quantity`, `unit_amount` | quantity is usually null on card spend |
| `account_code`, `account_name` | as coded in Xero |
| `amount_ex_tax`, `tax_amount` | base currency; **negative** for `refund` / `credit` |
| `treatment` | `stock` \| `not_stock` \| `duty` \| `overhead` — from rules; one vocabulary everywhere |
| `treatment_rule_id` | rule that decided; null = account default |
| `treatment_override` | set when a user decides this line by hand (`not_stock` action) |
| `state` | `open` \| `partly_recorded` \| `recorded` \| `skipped` \| `not_stock` |
| `not_stock_amount` | part of the line the user said is not stock (same sign as amount) |
| `review_reason` | null, or `amount_changed` \| `recoded` \| `deleted_in_xero` |
| `superseded_at` | set when a sync no longer returns this `line_key`; the line is then treated like a deleted one |

Arithmetic, enforced in the service under a row lock on the line:
`open_amount = amount_ex_tax − Σ active allocations.amount − not_stock_amount`;
`|Σ allocations| + |not_stock_amount| ≤ |amount_ex_tax|` with all three the same sign.
State is derived on every write: `recorded` when `open_amount = 0` and something was allocated,
`not_stock` when `not_stock_amount = amount_ex_tax`, `partly_recorded` when something was
allocated and `open_amount ≠ 0`, else `open` (or `skipped`, which only the skip action sets and
any later action clears).

### `purchase_rules` (the mapping settings — mirror of `ProductMapping`)
| Column | Notes |
| --- | --- |
| `account_code`, `payee_pattern`, `description_pattern` | matchers, each nullable; at least one set (check constraint) |
| `match_type` | `exact` \| `contains`, case-insensitive after normalising whitespace |
| `treatment` | `stock` \| `not_stock` \| `duty` \| `overhead` |
| `template` | JSONB, `stock` only: rows of `{material_name, inventory_type, unit, quantity_mode, quantity, unit_price, share, location_id, ask_batch_number, ask_expiry}` |
| `auto_record` | bool, default false (Phase 2 — Phase 1 stores it, never acts on it) |
| `is_active`, `created_by_user_id`, timestamps | |

`quantity_mode`: `fixed` (always `quantity`), `from_price` (line amount ÷ `unit_price`, rounded
to 4 dp) or `ask`. `share`: a percentage of the line amount, or `"rest"` (at most one row).
`inventory_type` may be `final_product` (bought-in finished goods). Unique on
`(org_id, account_code, payee_pattern, description_pattern, match_type)` with nulls treated as
equal (`NULLS NOT DISTINCT`, Postgres 15+; V10).

### `purchase_allocations` (purchase line → lot)
`id`, `purchase_line_id`, `inventory_item_id` (`ondelete=RESTRICT`), `amount` (signed as the
line), `quantity` (quantity bought, in the lot's unit; may be 0 for a refund that returns no
stock), `cost_flow_id` (the inflow this purchase paid for; null for refunds), `status`
(`active` \| `orphaned`), `created_by_user_id`, `created_at`.
Unique `(org_id, purchase_line_id, inventory_item_id)`.

### `lot_cost_entries` (costs with no purchase behind them)
`id`, `inventory_item_id` (composite FK, `ondelete=CASCADE`), `cost_flow_id` (the inflow it
prices; null = **whole-lot price**), `kind` (`manual` \| `free`), `amount` (≥ 0), `quantity`
(> 0, in the lot's unit), `note`, `is_active`, `created_by_user_id`, `created_at`,
`deactivated_at`. `free` requires `amount = 0`. Partial unique index: at most one active entry
per `(org_id, inventory_item_id, cost_flow_id)` with nulls equal (two indexes: one on
`(org_id, inventory_item_id, cost_flow_id) WHERE is_active AND cost_flow_id IS NOT NULL`, one on
`(org_id, inventory_item_id) WHERE is_active AND cost_flow_id IS NULL` — portable, no
`NULLS NOT DISTINCT`).

**Price facts.** A lot's price facts are its active `lot_cost_entries` plus (8.1c) its active
or orphaned `purchase_allocations`. Both have the same meaning:

- A **flow price** (`cost_flow_id` set) prices `quantity` units of that one `created`/`added`
  inflow for `amount`. Invariant, enforced at write under a row lock on the lot:
  `Σ quantity of positive flow prices on a flow ≤ flow.quantity` (400 otherwise). The flow's
  unpriced **residual** is `flow.quantity − Σ quantity`.
- A **whole-lot price** (`cost_flow_id` null; amount ≥ 0, zero only for `kind = free`) sets the unit price
  `p = amount / quantity` for every unpriced unit of the lot's `created`/`added` inflows,
  including residuals. Its `quantity` is only the basis of that price (what the receipt said).
- Each unit of inflow is priced exactly once: flow prices first, the whole-lot price for what's
  left. So a whole-lot manual price and a later flow-specific purchase never double count.
- **Refunds** (8.1c: negative-amount allocations, quantity 0, `cost_flow_id` null) are applied
  once, after pricing, to the lot's priced amount; a refund larger than the priced amount
  floors the lot's amount at 0 and adds the warning `refund_exceeds_cost`; a refund on a lot
  with nothing priced is ignored for cost and adds the warning `refund_without_cost`.
- Price facts can only be written on a lot whose inflows are all `created`/`added` (a lot made
  by production, transfer or reconciliation gets its cost from its source; 400 otherwise),
  and never on a customer-owned lot (always 0; 400).

### `cost_flows` (every quantity into or out of a lot that cost cares about)
| Column | Notes |
| --- | --- |
| `inventory_item_id` | composite FK, `ondelete=CASCADE` |
| `direction` | `in` \| `out` |
| `kind` | in: `created` \| `added` \| `produced` \| `transfer_in` \| `reconciled_in` · out: `consumed` |
| `quantity` | positive, in the lot's unit |
| `execution_id`, `execution_step_id`, `step_number` | set for `produced`, `reconciled_in` and `consumed`; composite FKs, `ondelete=CASCADE` |
| `source_output_id` | the step output **definition id** (`steps.outputs[].id`), resolved as below; null when it can't be resolved |
| `source_key` | stable identity of the stock write that caused the row; unique `(org_id, source_key)`. Live hooks and the backfill use the **same** keys, so neither can duplicate the other |
| `write_reason` | the `InventoryQuantityWriteReason` of the write that caused it |
| `reconstructed` | bool — true for rows made by the backfill rather than at the time |
| `created_at` | |

`source_key` values: `create:<item_id>`, `add:<event_id>` (the `inventory_item.quantity_adjusted`
entity event the add emits), `consume:<execution_step_id>:<item_id>`,
`reconcile:<execution_step_id>:<untracked_item_id>:<output row position>` (two rows reconciling into
one lot are two movements). A live write whose key already exists is a bug and fails the stock
write (`FlowConflictError`); only the backfill skips existing keys.

Indexes: `(org_id, inventory_item_id, direction)`, `(org_id, execution_id, step_number)`.

Written in the **same transaction** as the stock write, from three places only:

1. `InventoryRepository.create_inventory_item` → one `in` row for the created quantity, kind by
   precedence: `transfer_in` when `transfer_receipt_id` is set (a transfer destination copies
   the source's production provenance, so this check comes first); else `produced` when
   `source_execution_step_id` is set; else `created`. Every lot creation goes through this
   method (checked: the only `InventoryItem(` constructor outside models).
2. `InventoryRepository.add_quantity_to_inventory_item` → one `in` row (`added`) when the
   quantity actually increases.
3. `complete_step` in `execution_routes.py` → one `out` row (`consumed`) per aggregated input
   lot, in that lot's unit; and for an output reconciled into an untracked lot
   (`reconcile_output_to_untracked_reduce_only`), one `in` row (`reconciled_in`) on that
   untracked lot for the reconciled amount (converted to the untracked lot's unit), because
   that output creates no lot of its own (only the surplus does).

**Output identity.** `complete_step` resolves each output's definition id and passes it to
`create_inventory_item(source_output_id=…)` (which already validates it belongs to the step):
the output's `output_id` when the client sends one that the step declares (an `output_id` the
step doesn't declare rejects the completion, 400); else the one declared output for which
`declared.name.strip() == output.name.strip()` (case-sensitive), **only if exactly one**
matches; else null (no `cost_share` applies; the split falls back to quantity/primary). Library
stock lines carry `source_output_id = null` and `extra_data.library_stock = true`.
`reconciled_in` rows carry the same resolved id as the output they came from.

These are plain inserts with no cost logic, so they cannot fail independently of the stock
write; there is no "costing off" path that skips them. Whether costing is enabled affects only
whether costs are computed and shown.

**Backfill** (`uv run workflow costing backfill-flows --org-id <id> | --all`; idempotent; not a
migration step). Sources, all marked `reconstructed = true`, all keyed as above so a rerun or a
later live write inserts nothing twice:

- `in` per existing lot, kind by the same precedence, `source_key create:<item_id>`; quantity =
  the `quantity` in the lot's earliest `inventory_item.created` entity event, else current
  quantity + Σ its `consumed` quantity from `actual_inputs` (a floor: sales, wastage and
  stocktake decreases before flows existed aren't recoverable; this only weights pricing).
- `in` (`added`) per `inventory_item.quantity_adjusted` event emitted by
  `add_quantity_to_inventory_item` where the quantity rose, `source_key add:<event_id>`.
- `out` (`consumed`) per completed step × input lot from `actual_inputs`, summed per lot and
  converted to the lot's unit, `source_key consume:<execution_step_id>:<item_id>`; an input
  whose lot no longer exists, or whose unit can't convert, is skipped and counted in the
  command's output.
- Reconstructed rows have `write_reason = "backfill"` and `created_at` = the time the backfill
  ran (they sort after live rows; ordering ties break on `id`).
- Historical reconciliations are **not** reconstructed: their untracked lots stay unknown and
  are listed as missing inputs, which is honest and fixable by entering a price.

Worked examples (each is a test): create-only (one `created` row); create, add 3, consume 2
(rows `created`, `added 3`, `consumed 2`); a produced lot (one `produced` row with its step);
a transfer destination (`transfer_in`, even though it also has `source_execution_step_id`);
backfill run twice (second run inserts 0 rows); a lot created after the backfill (live hook
row only, backfill rerun inserts nothing).

### `costing_settings` (one row per org)
8.1a: `use_last_known_price` (bool, default true), `created_at`, `updated_at`; created on first
write, read as defaults when absent. 8.1c adds `start_date`, `last_history_from`,
`last_history_to`.

### Existing tables touched
- `xero_sync_jobs`: add `purchases_synced INTEGER NOT NULL DEFAULT 0`; `sync_type` gains
  `purchases` and `purchases_history`.
- Process step output definitions (`steps.outputs[]` JSONB): optional `cost_share` key
  (`{"mode": "percent", "value": 80}` or `{"mode": "byproduct"}`). No schema migration.
- `app/core/security/access_policy.py`: two permissions (see Users & permissions).

### Phase 3 (not built in Phase 1): `stock_value_snapshots` / `_lines`
Header `as_of_date`, `kind`, category totals; lines `inventory_item_id`, `quantity`,
`unit_cost`, `value`, `status`. Historical on-hand can't be reconstructed exactly before
`cost_flows` existed, so the bridge is offered only for periods that start at or after the
first snapshot. Phase 1's `cost_flows` are what make later periods reconstructable.

## Cost roll-up

Costing uses its own memoised walk over `cost_flows` — not `TemporalDagTracer` (event-sourced,
as-of-a-time, capped at depth 5). It reads facts only and writes nothing.

**Values.** Every computed cost carries: `known` (the dollar amount of the inputs that have a
cost — a floor when anything is missing), `status`, `missing` (the set of lots with no cost
that this figure depends on, by id and name) and `warnings`. Status order, worst last:
`actual` < `estimated` < `partial` < `unknown`. A lot's `unit_known` is `known ÷ quantity`.
The public `unit_cost` equals `unit_known` when status is `actual` or `estimated`, and is
**null** when `partial` or `unknown`; `known_unit_cost` always carries the floor (null only when
`unknown`). Internally, the floor is what propagates, so a partial WIP lot still passes its
known cost on and its missing inputs ride along to every downstream output.

```
lot_cost(lot):                                   # memoised per request
    if lot.contract_customer_id: return (unit_known=0, actual, source=customer_owned)
    if lot in visiting: return (None, unknown, missing={lot}, warnings={cycle})
    parts = []                                    # (quantity, known, status, missing)
    unpriced_ca = 0                                # unpriced created/added quantity
    unpriced_other = 0                             # transfer_in whose source is unknown
    for f in in_flows(lot):
        if f.kind == transfer_in:
            src = transfer_source_lot(lot)         # transfer_receipt_id -> transfer -> source_item_id
            c = lot_cost(src) if src else UNKNOWN
            if c.status == unknown: unpriced_other += f.quantity; missing |= c.missing
            else: parts += (f.quantity, f.quantity * convert(c.unit_known, src.unit -> lot.unit), c.status, c.missing)
        elif f.kind in (produced, reconciled_in):
            a = cost_execution(f.execution).allocation[f]
            parts += (f.quantity, a.known, a.status, a.missing)
        else:                                     # created / added
            fp = positive flow prices on f        # invariant: sum(fp.quantity) <= f.quantity
            q = sum(fp.quantity)
            if q > 0: parts += (q, sum(fp.amount), facts_status(fp), {})
            unpriced_ca += f.quantity - q
    wl = whole_lot_price(lot)                     # at most one; p = amount / quantity
    if wl:
        if unpriced_ca > 0: parts += (unpriced_ca, unpriced_ca * wl.p, facts_status(wl), {}); unpriced_ca = 0
        elif no in_flows(lot): return (wl.p, facts_status(wl), source=manual)   # lot predates flows
    refunds = sum of negative price facts         # 8.1c; applied once, here
    if parts:
        Q = sum(quantity); K = sum(known) + refunds
        if K < 0: K = 0; warn refund_exceeds_cost
        status = worst(part statuses)
        if unpriced_ca or unpriced_other: status = worst(status, estimated)   # takes the lot's own price
        return (K / Q, status, missing = union(part missing) | missing)
    if refunds: warn refund_without_cost
    if settings.use_last_known_price and (e := material_estimate(lot)):
        return (e.unit, estimated, source=estimate, estimate_from=e.lot)
    return (None, unknown, missing = {lot} | missing)

facts_status(facts) = estimated if any is an orphaned allocation (8.1c) else actual

cost_execution(execution):                       # memoised; runs for in-progress batches too
    pool = (known=0, status=actual, missing={})
    for step in execution steps ordered by step_number:
        if step is completed and its actual_inputs name lots but it has no consumed flows:
            pool.missing |= those lots; pool.status = partial; warn no_flow_history
        for c in consumed flows of step:
            u = lot_cost(c.lot)
            if u.status == unknown: pool.status = worst(pool.status, partial)
            else: pool.known += c.quantity * u.unit_known; pool.status = worst(pool.status, u.status)
            pool.missing |= u.missing; pool.warnings |= u.warnings
        outs = produced and reconciled_in flows of step
        if outs:
            weights, assumed = split_weights(step, outs); split_assumed |= assumed
            for o in outs:
                allocation[o] = (known = pool.known * weights[o], status = pool.status, missing = pool.missing)
            # money quantised to 4 dp; the rounding remainder goes to the largest weight (ties: earliest flow)
            # an output with weight 0 gets known 0, status actual, missing {} — it carries no cost by design
            pool = (0, actual, {})
    cost_so_far = pool       # live cost while running; a production loss if it never reaches an output
```

A partial pool's `status` is `partial` even if every *costed* input is actual. Execution status
= worst of every consumed lot's status (unknown counts as partial) and of `cost_so_far`.

**`split_weights(step, outs)`** — returns a weight per output summing to 1, and `assumed`:

1. Library stock lots (`extra_data.library_stock`) get weight 0 (ASSUMPTION A9), unless they
   are the only outputs, in which case they are treated as ordinary outputs.
2. For each remaining output, `cfg` = the `cost_share` on the step output definition whose
   `id` equals the flow's `source_output_id`. Valid values: `{"mode": "percent", "value": v}`
   with `0 < v ≤ 100`, or `{"mode": "byproduct"}`; anything else is ignored (treated as no
   config) and logged.
3. Groups: `percent` (valid percent), `byp` (byproduct), `free` (no config).
4. If `percent` and `free` are both empty (every output is a byproduct): move `byp` into
   `free`, `assumed = true`.
5. `P = Σ percent values`. If `P > 100`, or `free` is empty, scale the percents to sum to 100
   (`P > 0`) and `free` gets 0. Otherwise `free` shares `R = 100 − P`:
   one output takes all of `R`; several share it by quantity when every unit in `free`
   converts to the first's unit (`are_units_compatible`); otherwise all of `R` goes to the
   primary output of `free` and `assumed = true`.
6. `byp` gets 0.

Primary output, by the destination lots' actual `inventory_type`: `final_product` before
`work_in_progress` before `raw_material`, then largest quantity, then earliest flow. "Earliest
flow" everywhere means ordered by `(created_at, id)` ascending. (Ordinary outputs of one
step share a type; differing types arise when an output is reconciled into an existing lot.)

Precision: unit costs to 6 dp, money to 4 dp, rounding half-up, applied only at the API
boundary and to allocations; internal arithmetic uses unrounded `Decimal`. Displayed to cents.

**Same material** (for last known price and readiness): two lots are the same material when
`normalise(name)` matches and their units are compatible, where `normalise` lower-cases, trims,
collapses whitespace and strips a trailing `" - library stock"`.

**`material_estimate(lot)`**: candidates are other lots of the same material in the org, not
customer-owned, that are **directly priced** — their own price facts give them status `actual`
with no produced/transfer/reconciled inflow (estimates never chain, and production costs are
never used as a material's price). A candidate's date is its `purchase_date`, else its
`created_at` date. Pick the latest candidate dated on or before this lot's date (ties: latest
`created_at`, then id), else the earliest dated after (ties: earliest `created_at`). The unit
cost is converted to this lot's unit (`price × candidate units per one lot unit`).

### Recompute

Compute on read, nothing stored. Every lot/execution read builds the figure from facts, memoised
for that request, so a late price, a changed setting or a newly costed material is reflected on
the very next read — there is no stale state to invalidate. A single computation visits at most
20,000 nodes (lots + executions); beyond that the API returns status `unknown` with warning
`too_large` (not expected at any current tenant's size; the Phase 3 cache is the fix if it ever
is). AC33 (rebuild equals incremental) is retired with the caches.

### What each stock write means for cost

| Write | Cost rule |
| --- | --- |
| Step consumption | value moves into the batch pool at the lot's unit cost |
| Step output | lot receives its share of the pool |
| Output reconciled into an untracked lot | that lot receives the reconciled part's share as a `reconciled_in` flow |
| Purchase recorded / quantity added | inflow at the allocated or entered amount |
| Sales FIFO consumption | cost of sale = quantity × lot unit cost (Phase 2 report) |
| Wastage, tasting, stocktake loss | quantity × unit cost, reported by kind (Phase 3); unit cost unchanged |
| Site transfer | destination lot carries the source lot's unit cost |
| Customer-owned material | zero |
| Library stock remainder | takes no share of the batch cost in Phase 1 (ASSUMPTION A9) |

## Deciding what is a stock purchase

Two layers, so it works with nothing configured and bends to any org.

**Layer 1 — account defaults.** On first sync Biz-E reads the chart of accounts:

| Xero account | Default treatment |
| --- | --- |
| Type `DIRECTCOSTS`, name contains "excise" or "duty" | `duty` |
| Type `DIRECTCOSTS`, name contains rent, wages, salaries, power, light, heating, fuel, vehicle, freight, courier, postage | `overhead` |
| Type `DIRECTCOSTS`, anything else (Purchases, Ingredients, Packaging, Consumables, Materials…) | `stock` |
| Any other expense account | `not_stock` |
| Non-expense accounts (assets, liabilities, transfers) | not stored |

Lines on every expense-class account are stored, whatever their treatment, so changing a
treatment later needs no re-sync. Only `stock` lines are ever shown on the Purchases page.

An org that codes stock purchases to an ordinary expense account changes that account's
treatment once, in the rules settings.

**Layer 2 — purchase rules.** `purchase_rules` override the defaults and carry the mapping.
The most specific active rule wins: payee + account, then payee or description alone, then
account alone, then the account default. A rule can say:

- **Ignore this seller** (`not_stock`) — its purchases are never presented.
- **This seller / description is always this material** — the card arrives pre-filled with
  material, unit, quantity and amount split; the user types batch number and expiry if the
  material needs them, edits anything that differs, and confirms.
- **This account is / isn't stock.**

Rules are managed on a settings page laid out like the existing Xero product mappings, but
users rarely need to open it: after recording a purchase, the card offers "Remember this for
<payee>", which saves what they just did as a rule. Every pre-filled value stays editable.
Rule changes re-classify only lines not yet recorded.

## The Purchases page

A reconcile-style page: one card per purchase line. Left side is what Xero says (payee, date,
amount, account, description). Right side is what Biz-E proposes to do with it.

**Tabs:** To record (`open`, `partly_recorded`, or any `review_reason`) · Recorded · Skipped ·
Not stock. A date filter applies to all tabs. Only `stock` lines appear in any tab.

**Card actions:**

1. **Record stock.** One row per thing bought: material (existing name or new), inventory type
   (raw material default; final product allowed), quantity, unit, supplier batch number,
   expiry, location, amount.
   - Pre-filled from the matching rule's template; failing that, from the rows recorded last
     time for this payee (suggestion, not a rule); failing that, one empty row with the whole
     amount. Bill lines (Phase 2) pre-fill description, item code and quantity.
   - With several rows, each row's amount is typed; rows with a last known price are
     pre-filled with price × quantity; one row may be left blank and takes the remainder.
   - Rows may total less than the open amount; the user then picks "rest is not stock"
     (`not_stock_amount += rest`) or "more to record later" (`partly_recorded`). They can never
     total more (400, nothing written).
   - A card whose rule pre-fills every value and asks for nothing shows a single **OK**.
   - Saving, in one transaction under an idempotency key: each row creates a lot through
     `InventoryRepository.create_inventory_item` (supplier = payee, purchase date = document
     date, supplier batch number, expiry, location), which writes its `created` flow; then an
     allocation per row with `cost_flow_id` = that flow.
   - After saving, "Remember this for <payee>" creates a `stock` rule matching payee + account
     whose template reproduces the rows (material, type, unit, quantity as `fixed`, share as a
     percentage of the amount, ask flags set for any field the user filled).
2. **Already in stock.** Link to lots entered by hand. Candidates: raw-material or
   final-product lots with no active allocation or cost entry, whose `purchase_date` (else
   `created_at` date) is from 3 days before to 14 days after the document date, ranked by
   normalised supplier = normalised payee, then by date distance. For each chosen lot the user
   confirms the quantity bought (default: the lot's `created` flow quantity) and amount. Each
   allocation's `cost_flow_id` is the lot's `created` flow. Any active manual entry on that
   flow is deactivated (a purchase replaces a typed price; no double counting).
3. **Not stock.** `not_stock_amount` = the open amount; optional "always for this payee"
   creates a `not_stock` rule for payee + account.
4. **Skip.** Sets state `skipped`. Hidden from To record; shown under Skipped and in any
   historical run covering its date. Any other action on the line clears it.
5. **Refunds** (`kind = refund`, negative amount, e.g. goods returned): actions are **Reduce
   the cost of** (pick lots; negative allocations with quantity 0, which lower those lots' unit
   cost) or **Not stock**.
6. **Review** (any `review_reason`): shows the Xero change and offers **Keep** (clear the
   reason), **Edit amounts** (reopen the record dialog on the existing allocations) or
   **Unlink** (delete the allocations; lots stay; their cost falls back to estimate/unknown).

Bulk actions on selected cards: **Skip**, **Not stock**, **Apply rule** (re-run rule matching
and open the first card pre-filled). Bulk actions write each line independently and report
per-line results.

### Historical runs

**Run historical costs** asks for a date range (any start date; default end today), stores it
in `costing_settings.last_history_from/to`, and opens the page filtered to that range with
historical mode on. If the range starts before the earliest document already synced, it first
runs a `purchases_history` sync job for that range (Xero filtered by transaction date, not
modified date), synchronously like the existing sync, and reports the count fetched.

Historical mode lists every `stock` line in the range whose state is `open`, `partly_recorded`
or `skipped`, plus `not_stock` lines collapsed with **Undo**. It ignores the start date.
There is no run object to persist: progress is the state of the lines ("38 of 112 done"), and
**Resume** reopens the stored range.

Day-to-day (not historical) To record shows lines dated on or after `start_date`.

### Notifications

No durable per-user notification service exists; in-app notifications are derived system
findings. So the notice is a **derived finding**: while the org has any To record line, the
notifications list shows "N purchases to record" (with the newest document date) linking to
the Purchases page, and the Home dashboard shows a card with the same count. It disappears when
the count is zero. Ignored and not-stock lines never count. Visible to users with
`costs.manage`.

### Manual cost without Xero

The lot cost panel lets a `costs.manage` user enter "total paid" for a lot (a
`lot_cost_entries` row for its `created` flow, or the whole lot), or mark it free. The Add
Inventory form gains an optional "total paid" field, shown only to `costs.manage`, which writes
the same entry for the new lot's `created` flow in the create transaction.

The page and every dialog must work at phone width (375px) — it is used at the bench.

### When Xero changes later

| Change in Xero | Nothing recorded yet | Already recorded |
| --- | --- | --- |
| Amount changed | line amount updates | each active allocation and `not_stock_amount` is rescaled by new ÷ old (rounded to 4 dp, remainder to the largest allocation); quantities unchanged; `review_reason = amount_changed` |
| Recoded to a non-stock account | line leaves the page | allocations and lots kept; `review_reason = recoded`; still shown under Recorded with a badge |
| Recoded into a stock account | line appears | — |
| Deleted / voided | line leaves the page | lots kept; allocations `orphaned` — still priced, status `estimated`; `review_reason = deleted_in_xero` |
| A `line_key` no longer returned | `superseded_at` set; treated as deleted | as deleted; a new line with a new key appears as a new card |

## Xero sync changes (`app/features/crm/`)

- **Scopes** added to `XERO_SCOPES`: `accounting.banktransactions.read` and
  `accounting.settings.read` (Phase 1); `accounting.reports.profitandloss.read` (Phase 3).
  Names confirmed by spec-critic against Xero's scope table; re-check at build. Existing
  connections reconnect (not in production). The existing `accounting.invoices` covers bills.
- **`XeroApiClient`** gains, all paginated and using the existing retry and rate limiter:
  `get_accounts()`; `get_bank_transactions(modified_after)` for types `SPEND` and `RECEIVE`,
  including `DELETED` status; `get_bills(modified_after)` for `Type=="ACCPAY"` (Phase 2);
  `get_bill_credit_notes(modified_after)` for `ACCPAYCREDIT` (Phase 2);
  `get_profit_and_loss(from, to)` (Phase 3).
- **`XeroSyncService`** gains `_sync_accounts` and `_sync_purchases`, run as part of `full` and
  as `sync_type="purchases"`, incremental by modified-since like invoices. It upserts through a
  `purchase_sources` module in the costing slice (the mirror of `sales_sources.py`), which
  normalises to `purchase_documents` / `purchase_lines` (upsert on `external_id` and
  `line_key`), converts currency at the document's rate, converts amounts to ex-tax
  (`LineAmountTypes`: `Exclusive` → as is; `Inclusive` → line amount − tax amount; `NoTax` → as
  is), sets `kind`/sign (`SPEND` positive, `RECEIVE` on an expense account negative), applies
  treatments, applies the "When Xero changes later" rules. Costs are computed on read, so nothing needs
  rebuilding afterwards.
- The purchases sync runs inside the existing synchronous sync job; its counts go to
  `purchases_synced`. A failure in it marks the job `partial` and leaves sales sync results
  intact.
- Bill statuses: `DRAFT` and `SUBMITTED` are skipped; `AUTHORISED` and `PAID` are `active`;
  `VOIDED` and `DELETED` are `voided`.
- Only lines on expense-class accounts are stored. Transfers and balance-sheet lines are not.

## Margins (Phase 2)

For each sale line from `sales_sources.sale_lines()`:

- revenue = Xero line amount ex GST, shared across the line's lot allocations by quantity;
- production cost = allocated quantity × the lot's unit cost, carrying the lot's status;
- duty = the nz_alcohol module's duty for that removal, through one new function in that module
  (it owns the calculation; costing never recomputes rates);
- units with no lot (sold before go-live, or not yet matched) are costed at the product's
  average unit cost and flagged `estimated`;
- credit notes and returns reverse revenue and cost through the existing reversal path.

Report: per product per month — units, revenue, production cost, duty, gross margin in dollars
and percent, average cost per unit — with drill-down to invoice line → batch → inputs. Pending
review allocations are included and marked.

## Xero bridge and stock value (Phase 3)

For a period between two snapshots:

```
  Xero cost-of-sales, stock accounts (from Xero P&L)              A
− purchases Biz-E has recorded into stock in the period           B
= spending in stock accounts not recorded as stock                A − B   (listed line by line)

  Opening stock value                                             S0
+ purchases recorded into stock                                   B
− closing stock value                                             S1
= cost that left stock                                            = COGS of sales
                                                                  + wastage + samples
                                                                  + stock variance + unabsorbed
                                                                  ± estimate changes
```

Shown beside it: Xero's Excise Duty account against Biz-E's computed duty for the period, and
Xero's overhead direct costs, untouched. Any gap between the Xero P&L account totals and the
lines Biz-E synced is shown as "other entries in Xero (journals)".

Stock value = on-hand quantity × unit cost per lot, plus the unabsorbed pool of in-progress
batches ("in production"), grouped raw / in production / work-in-progress / finished, with the
actual / estimated / unknown split. A month-end snapshot is taken automatically on the first
sync after the month ends (org timezone) and can be taken manually. Export as CSV for the
accountant's Closing Stock entry.

## Users & permissions

Two permissions added to `PERMISSIONS` in `app/core/security/access_policy.py`:

- `costs.view` — "See costs, cost per unit, stock value and margins".
- `costs.manage` — "Record purchases, enter costs and change purchase rules and costing settings".

Role defaults (ASSUMPTION A6): `ADMIN` gets both (it has everything); `MEMBER` ("Staff",
everything except admin-only) gets both, by the existing `_ALL − ADMIN_ONLY` rule; `PRODUCTION`,
`COMPLIANCE`, `SALES` and `AUDITOR` get neither. Both are grantable to custom roles. Margin
figures (Phase 2) need `costs.view` **and** `sales.view` (there is no `sales.revenue`).

Enforcement: `access_policy.POLICY` gets `("costing.*", _READ, "costs.view")` and
`("costing.*", None, "costs.manage")` (the costing blueprint is named `costing`). A tuple in
that table means *any of*, so where an action needs **two** permissions the route also carries
the existing `@requires_permission("inventory.adjust")` decorator
(`app/core/security/permissions.py`), which is an *and* on top of the table.

| Endpoint | Method | Table | Extra decorator | MR |
| --- | --- | --- | --- | --- |
| `/lots/<id>/cost`, `/executions/<id>/cost`, `/settings` | GET | `costs.view` | — | 8.1a |
| `/lots/<id>/cost` (manual / free entry) | PUT | `costs.manage` | — | 8.1a |
| `/lots/<id>/cost/<entry_id>` | DELETE | `costs.manage` | — | 8.1a |
| `/settings` | PUT | `costs.manage` | — | 8.1a |
| purchases list, candidates, readiness, rules, accounts | GET | `costs.view` | — | 8.1c–e |
| `/purchases/<id>/record`, `/purchases/<id>/link` (create or link stock) | POST | `costs.manage` | `inventory.adjust` | 8.1c |
| not-stock, skip, reopen, review, bulk, historical run | POST | `costs.manage` | — | 8.1c |
| rules, accounts | POST/PUT/DELETE | `costs.manage` | — | 8.1c |

Entering a price on a lot changes no stock, so it needs `costs.manage` only. Tests cover a
custom role with `costs.manage` but not `inventory.adjust` (record/link 403, everything else
allowed) and the inverse (every costing write 403).

Every costing endpoint is covered by the access-policy route table (default deny). API
responses from other slices that gain cost fields (lot detail, execution detail, Add Inventory)
**omit** those fields unless the user has `costs.view`. Every costing route also returns 404
when the org's `costing_enabled` subscription is off.

tenant_scoped: yes. Every query filters `org_id`; every cross-table link is a composite
`(org_id, …)` key; cost reads and the backfill never cross orgs.

## API (all under `/api/core/costing`, `@requires_auth` + org scope + permission per the matrix)

| Route | Purpose |
| --- | --- |
| `GET /purchases?tab=&from=&to=&historical=` | Purchases page list (cards with pre-fill) and per-tab counts |
| `GET /purchases/<line_id>/candidates` | lots that might already be this purchase |
| `POST /purchases/<line_id>/record` | create lots + allocations (`Idempotency-Key` header, existing `ApiIdempotencyKey`) |
| `POST /purchases/<line_id>/link` | allocate to existing lots (also refunds: negative, quantity 0) |
| `POST /purchases/<line_id>/not-stock`, `/skip`, `/reopen` | decide, hide, undo |
| `POST /purchases/<line_id>/review` | `{"action": "keep" \| "unlink"}`; edit amounts uses `/link` on the existing lots |
| `POST /purchases/bulk` | `{"line_ids": [...], "action": "skip" \| "not_stock" \| "apply_rule"}`; per-line results |
| `POST /purchases/historical-run` | `{from, to}`: store range, fetch from Xero if needed, return counts |
| `GET /readiness`, `GET /readiness/<product>` | cost readiness |
| `GET/PUT /lots/<item_id>/cost` | lot cost panel; manual / free entry |
| `GET /executions/<id>/cost` | batch cost card |
| `GET/POST/PUT/DELETE /rules` | purchase rules |
| `GET/PUT /accounts` | account treatments |
| `GET/PUT /settings` | start date, last known price |
| Phase 2: `GET /materials/<name>/history`, `GET /margins` · Phase 3: `GET /stock-value`, `POST /stock-value/snapshot`, `GET /bridge` | |

Lot cost payload (`GET /lots/<id>/cost`):
`{"inventory_item_id", "unit": "kg", "unit_cost": "45.000000" | null, "known_unit_cost": "45.000000" | null,
"status": "actual|estimated|partial|unknown", "source": "manual|free|purchase|production|transfer|estimate|customer_owned|mixed|none",
"estimate_from": {"inventory_item_id", "name"} | null, "priced_quantity": "2.0000", "unpriced_quantity": "0.0000",
"missing": [{"inventory_item_id", "name"}], "warnings": [...], "entries": [{"id", "kind", "amount", "quantity", "cost_flow_id", "note", "created_at"}],
"editable": true}` — `editable` is false for lots whose cost comes from production, transfer
or a customer.

`source`: the single source of every priced part — `manual`, `free`, `production`, `transfer` —
or `mixed` when parts come from more than one; `estimate` (last known price), `customer_owned`,
or `none` (unknown). `priced_quantity` = Σ quantity of priced parts (flow-priced and
whole-lot-priced direct inflows, produced / reconciled inflows, costed transfer inflows; the
whole-lot entry's own quantity for a lot with no flows; 0 for customer-owned and estimates);
`unpriced_quantity` = the rest of the lot's inflow quantity.

`PUT /lots/<id>/cost` body: `{"kind": "manual"|"free" (default manual), "amount", "quantity",
"cost_flow_id"?, "note"?}`; `manual` needs `amount ≥ 0` and `quantity > 0` (numbers or numeric
strings, ≤ 4 dp, < 10^14); `free` takes no amount (or 0) and `quantity` defaults to 1. Unknown
fields → 400. A PUT replaces the active entry in the same slot (same lot and `cost_flow_id`).
Returns 200 with the recalculated lot payload. `DELETE /lots/<id>/cost/<entry_id>` deactivates
an active entry and returns 200 with the lot payload; an unknown or already inactive entry is
404. `PUT /settings` body `{"use_last_known_price": true|false}` only; anything else 400.

Execution cost payload (`GET /executions/<id>/cost`):
`{"execution_id", "status", "known_input_cost": "95.0000", "cost_so_far": "0.0000",
"cost_so_far_status", "split_assumed": false, "missing": [...], "warnings": [...],
"inputs": [{"inventory_item_id", "name", "step_number", "quantity", "unit", "unit_cost", "known_amount", "status", "internal"}],
"outputs": [{"inventory_item_id", "flow_id", "kind": "produced|reconciled_in", "name", "step_number", "quantity", "unit",
"known_amount", "unit_cost", "known_unit_cost", "status", "missing": [...], "weight": "0.800000"}]}`.
`inputs` lists every consumed flow; `internal` is true when the lot was produced by this same
execution (a WIP passed between its steps). `known_input_cost` = Σ `known_amount` of inputs
that are not internal, so a WIP is never counted twice. There is no single batch-level unit cost: each output has its own; the batch card (8.1e)
chooses what to headline. Money is a string to 4 dp, unit costs to 6 dp.

CLI: `uv run workflow costing backfill-flows --org-id <id> | --all` (idempotent). Switching costing on
for an org is the existing `uv run workflow grant-feature --org-id <id> --feature costing` (and the
admin site, whose `KNOWN_FEATURES` gains `costing`); run the backfill after granting.

## External surfaces

- Xero API (read only): Accounts, BankTransactions (`SPEND`, `RECEIVE`, incl. `DELETED`),
  filtered by modified-since (incremental) or by date (historical). New OAuth scopes as above;
  every connected org must reconnect once.
- New pages: Production › Purchases, Production › Costs (readiness), purchase rules settings.
  Changed pages: inventory lot detail (cost panel), batch detail (cost card), Add Inventory
  (total paid), Home (card), notifications list (derived finding).
- New tables (10) and one column on `xero_sync_jobs`; one data backfill of `cost_flows`.
- Hooks in Core: `InventoryRepository.create_inventory_item`,
  `add_quantity_to_inventory_item`, and `complete_step` — inserts only, same transaction.
- New CLI commands (above). New permissions (two). New feature subscription
  (`costing_enabled`).
- No emails, no webhooks, nothing written to Xero.

## Acceptance criteria

Fixtures: one org with a fake Xero client returning canned Accounts/BankTransactions (the
existing CRM test pattern), and a second org for isolation tests. Money in assertions is
ex-GST.

Phase 1 — sync and classification
- AC1: With no rules, a `SPEND` bank transaction of $103.50 inc GST ($90.00 ex) coded to a
  `DIRECTCOSTS` account "Purchases - Ingredients" appears in `GET /purchases?tab=to_record`
  with payee, date, `amount_ex_tax = 90.0000`, state `open`.
- AC2: Transactions coded to `DIRECTCOSTS` "Excise Duty" (→ `duty`), `DIRECTCOSTS` "Direct
  Rent Costs" (→ `overhead`) and an `EXPENSE` account "Office Expense" (→ `not_stock`) are
  stored with those treatments and appear in no tab.
- AC3: Syncing the same transaction twice leaves one document and one line (upsert on
  `external_id` + `line_key`).
- AC4: A `RECEIVE` transaction of $20 ex coded to a stock account appears as a refund card with
  `amount_ex_tax = -20.0000`.

Phase 1 — recording
- AC5: Recording a $90.00 line as one row (2 kg "Juniper Berries") creates one raw lot of 2 kg
  with supplier = payee and purchase date = document date, one `created` flow of 2 kg, and one
  allocation of $90.00 pointing at that flow; the lot's cost is `unit_cost 45.000000`, status
  `actual`; the line is `recorded`.
- AC6: Recording a $100.00 line as rows of $60 and $25 with "rest is not stock" creates two lots,
  sets `not_stock_amount = 15.0000` and state `recorded`. With "more to record later" the state
  is `partly_recorded` and the card stays in To record with $15 open. Rows totalling $101
  return 400 and create no lot or allocation.
- AC7: Repeating a record request with the same `Idempotency-Key` returns the first response
  and creates nothing.
- AC8: Linking a line to an existing lot (created by hand with 2 kg and a manual entry of $80)
  creates an allocation of $90 on the lot's `created` flow, deactivates the manual entry, creates
  no lot, and the lot's unit cost becomes 45.000000 (not 85).
- AC9: Candidates for a line dated 10 Nov include an uncosted raw lot purchased 8 Nov from the
  same supplier, and exclude one purchased 1 Nov, one dated 25 Nov, and one that already has an
  allocation.
- AC10: Not stock sets `not_stock_amount` = open amount and moves the card to the Not stock tab;
  with "always for this payee" a `not_stock` rule exists and the payee's next purchase appears in
  no tab.
- AC11: Skip moves the card to Skipped; any later action on the line clears `skipped`.
- AC12: A refund linked to a 2 kg lot whose cost was $90 makes its unit cost $35.000000 (90 − 20
  over 2 kg) and leaves its quantity unchanged.
- AC13: Bulk skip on three lines, one of which another org owns, skips the two and reports the
  third as not found; nothing in the other org changes.

Phase 1 — rules
- AC14: With a rule "payee contains `Spirits Co`, template 20 L Neutral Spirit `fixed`, share
  `rest`, ask batch number", a new $400 purchase from "Spirits Co Ltd" is listed with that row
  pre-filled (20 L, $400) and `ask: ["batch_number"]`; recording with only `batch_number`
  creates a 20 L lot at 20.000000/L.
- AC15: A payee + account rule beats a payee-only rule, which beats an account-only rule, which
  beats the account default — one test per step.
- AC16: "Remember this for <payee>" after AC6's recording creates a rule whose template, applied
  to a new $200 purchase from the same payee, pre-fills the same two materials and quantities
  with amounts $120 and $50 (60% and 25%).
- AC17: Changing a rule re-classifies `open` and `skipped` lines only; `recorded` lines and their
  allocations are untouched.

Phase 1 — historical runs, start date, notice
- AC18: With `start_date` 1 Nov, a 15 Oct purchase is absent from To record; a historical run
  for 1–31 Oct lists it, and stores the range in settings.
- AC19: A skipped 15 Oct line appears in that historical run as actionable; a not-stock line
  appears collapsed with Undo, and Undo restores its open amount.
- AC20: A historical run for a range before the earliest synced document calls the Xero client
  with a date filter for that range, stores the new documents, and returns their count; a
  second identical run calls Xero again but creates no duplicate documents or lines.
- AC21: While the org has 3 To record lines, the system findings list for a `costs.manage` user
  contains one "3 purchases to record" item linking to the Purchases page and the dashboard
  summary contains a purchases card with count 3; with 0 lines neither is present; a user
  without `costs.manage` sees neither.

Phase 1 — cost roll-up (8.1a unless noted). Lots below are priced with manual entries unless
an AC says otherwise; "costed $X for Q" means a whole-lot manual entry of amount X, quantity Q.
- AC22: A raw lot with no cost, where an earlier lot of the same material (name differing only
  in case and spacing, unit g vs kg) is costed $45 for 1 kg, reports `unit_cost 0.045000` per g,
  status `estimated`, `estimate_from` naming the source lot. With no costed lot of that
  material, or `use_last_known_price` off, it reports `unit_cost: null`, status `unknown`, and
  itself in `missing`. A produced lot of the same name is never used as the source.
- AC23: A lot marked free reports `unit_cost 0.000000`, status `actual`, source `free`; a lot
  with `contract_customer_id` reports `0.000000`, `actual`, source `customer_owned`, and a PUT of
  a manual cost on it returns 400.
- AC24: A 2 kg lot with a flow price of $90 on its `created` flow, which then has 3 kg added
  with a flow price of $120 on the `added` flow, reports 42.000000/kg `actual`; if the added 3 kg
  has no price, it reports 45.000000/kg `estimated` with `unpriced_quantity 3.0000`.
- AC25: A batch whose step 1 consumes 1 kg of a 45/kg lot and 10 L of a 5/L lot and whose final
  step produces 20 units reports `cost_so_far 0.0000`, `known_input_cost 95.0000`, the output at
  4.750000/unit, `actual`.
- AC26: Before any output is recorded, that batch reports `cost_so_far 95.0000` and no outputs.
- AC27: Splits, one test each: (a) outputs 8 L and 2 L, no config → 80/20; (b) 2 L configured
  `byproduct` → 8 L takes 100%, 2 L `known_amount 0.0000`; (c) outputs in kg and units → the
  `final_product` takes 100%, `split_assumed true`; (d) 8 L configured 30% and 2 L unconfigured
  → 30/70; (e) two outputs configured 60% and 60% → 50/50; (f) both outputs `byproduct` → split
  by quantity, `split_assumed true`; (g) an invalid `cost_share` (`value: 0`, `value: 150`,
  unknown mode) is ignored → quantity split; (h) the allocated amounts always sum exactly to the
  pool, e.g. $100 over three equal outputs → 33.3334 + 33.3333 + 33.3333.
- AC28: A batch that consumed one `unknown` lot (plus a 45/kg lot) reports status `partial`,
  `missing` naming the unknown lot, `known_input_cost` excluding it, and on its output
  `unit_cost null`, `known_unit_cost` = the known floor; after a manual cost is entered on the
  unknown lot, the next read returns a complete `unit_cost` and `actual`.
- AC29: In a two-step batch where step 1 produces a WIP lot that step 2 fully consumes, the
  final output's cost equals the step-1 inputs plus step-2 inputs, each counted once. With one
  step-1 input unknown, the WIP is `partial`, step 2's output is `partial` with that same lot in
  `missing`, and its `known_unit_cost` = (step-1 known + step-2 inputs) ÷ quantity.
- AC30 (8.1c): Linking a purchase to a raw lot after a batch consumed it changes that batch's
  output unit cost on the next `GET /executions/<id>/cost` and the output lot's
  `GET /lots/<id>/cost`.
- AC31: An output reconciled into an untracked lot writes a `reconciled_in` flow for the
  reconciled amount (in the untracked lot's unit) on that lot, which then carries its share of
  the batch cost; the batch's `outputs` lists it with `kind reconciled_in`.
- AC32: A site transfer's destination lot reports the source lot's unit cost, source
  `transfer`, `editable false`; its in-flow is `transfer_in` even though it carries the source's
  `source_execution_step_id`. (Transfers copy the source unit today; the engine converts if they
  ever differ.) The backfill reconstructs that lot's flow as `transfer_in` too.

Phase 1 — Xero changes later
- AC34: A recorded line whose Xero amount changes from $90 to $99 has its allocation rescaled
  to $99 (quantity unchanged), `review_reason = amount_changed`, and the lot's next read is
  49.500000/kg.
- AC35: A recorded line deleted in Xero keeps its lot and quantity; the allocation is
  `orphaned`; the lot reports the same unit cost with status `estimated`; the line shows in To
  record with `review_reason = deleted_in_xero`. Review `keep` clears the reason; `unlink`
  removes the allocation and the lot reverts to estimate/unknown.

Phase 1 — Core hooks, surfaces, access
- AC36: Creating a lot through the Add Inventory API, completing a step with outputs, and adding
  quantity each write exactly one `in` flow of the written quantity with the kind and
  `source_key` the spec gives, in the same transaction (a forced rollback of the stock write
  leaves no flow). Completing a step writes one `consumed` flow per input lot, summed when the
  same lot is used by two inputs, in the lot's unit (an input of 500 g from a kg lot writes
  0.5000).
- AC37: The backfill, on an org with lots and completed steps made with the hooks disabled,
  writes the worked-example rows exactly (create-only; create + add 3 + consume 2; produced;
  transfer destination), all `reconstructed = true`; a second run inserts 0 rows; a lot created
  after the backfill gets only its live row, and a rerun still inserts 0.
- AC38: Add Inventory with "total paid $50" for 5 kg creates the lot and a manual entry; the lot
  reports 10.000000/kg `actual`. The field is absent from the form for a user without
  `costs.manage` and ignored by the API if sent.
- AC39: `GET /readiness/<product>` for a product whose latest batch consumed a costed and an
  uncosted raw material (via a WIP lot) lists both raw materials with `costed: true/false` and
  `ready: false`; once the second is costed, `ready: true`. A product with no batch lists its
  process's declared step inputs.
- AC40: A `PRODUCTION` user (neither costing permission) gets 403 on every 8.1a costing route;
  a custom role with `costs.view` only gets 200 on every GET and 403 on every PUT/DELETE; an
  `ADMIN` and a `MEMBER` get 200 on all. (8.1c adds the `inventory.adjust` pair tests.)
- AC41: With the `costing` feature not granted, every costing route returns 404 for an admin,
  and step completion and stock writes still write `cost_flows`.
- AC42: For every 8.1a costing route, a request naming another org's lot, execution or cost
  entry returns 404 and changes nothing; a lot's cost never includes another org's lots, even
  when a `cost_flows` row is forged pointing at one (the walk filters `org_id` on every query).
- AC43: E2E at a 375×800 viewport: the Purchases page and record dialog render with
  `document.documentElement.scrollWidth <= 375`, and a purchase can be recorded end to end by
  tapping and typing only.

Phase 2
- AC44: An `AUTHORISED` bill line with quantity 10 and an item code pre-fills a row with
  quantity 10; `DRAFT` and `SUBMITTED` bills are not synced.
- AC45: A sale line of 12 units at $480 ex GST, allocated to a lot costing 4.75/unit, with the
  excise module reporting $110.40 duty for that removal, reports revenue 480, production cost
  57, duty 110.40, margin 312.60.
- AC46: Sale units with no lot are costed at the product's average and flagged `estimated`; a
  product whose cost is incomplete shows revenue and "cost incomplete", with no margin.
- AC47: The margin report returns 403 without both `costs.view` and `sales.view`.
- AC48: With the compliance module off, duty is null ("not tracked"), not 0.

Phase 3
- AC49: A stock value snapshot's total equals Σ on-hand × unit cost over lots plus in-progress
  `cost_so_far`, with the actual / estimated / unknown split.
- AC50: For a period between two snapshots, opening + recorded purchases − closing equals COGS
  + wastage + samples + variance + production losses ± estimate changes, to the cent.
- AC51: The bridge lists every stock-account purchase line in the period not recorded as stock.

8.1a — engine rules that close round-2 review gaps
- AC52 (output identity): completing a step whose output carries `output_id` stores that id
  as `source_output_id` on the lot and its flow; without `output_id`, a name matching exactly one
  declared output resolves to its id; a name matching two declared outputs resolves to null and
  that step's `cost_share` config is not applied; a renamed output definition keeps working
  when the client sends `output_id`; an `output_id` the step doesn't declare is rejected (400).
- AC53 (Library stock): bottling 78 bottles plus 350 mL Library stock from a $390 pool puts
  $390 on the bottles (5.000000/bottle) and `known_amount 0.0000` on the Library stock lot,
  whose lot cost is `0.000000`, status `actual`. Core can't currently produce a step whose only
  output is Library stock (it is always a remainder line beside counted output); the engine
  still gives such a step's Library stock the whole pool, proved on constructed flows.
- AC54 (flow price bounds): a flow price whose quantity exceeds the flow's quantity returns
  400; a 5 kg lot with a flow price of $20 for 2 kg reports `priced_quantity 2.0000`,
  `unpriced_quantity 3.0000`, `unit_cost 10.000000`, status `estimated` (not `actual`); a
  second PUT on the same flow of $50 for 5 kg **replaces** the first (which becomes inactive
  with `deactivated_at` set) and makes it `actual` at 10.000000. Entries in one slot never
  accumulate; several prices on one flow only arise from purchase allocations (8.1c).
- AC55 (no double count): a lot with a whole-lot price of $80 for 2 kg that then gets a flow
  price of $90 for its 2 kg `created` flow reports 45.000000 (the whole-lot price applies to
  nothing); with a 2 kg created flow priced $90 and 3 kg added unpriced plus a whole-lot price
  of $60 for 3 kg, it reports (90 + 60) ÷ 5 = 30.000000 `actual`.
- AC56 (one whole-lot price): a second PUT of a whole-lot price deactivates the first; at most
  one active whole-lot entry exists per lot (database-enforced: a direct second insert fails).
- AC57 (editable lots only): a PUT on a lot whose in-flow is `produced`, `transfer_in` or
  `reconciled_in` returns 400, and its `editable` is false.
- AC58 (last known price choice): with costed lots of the same material dated 1 Oct ($40/kg)
  and 1 Nov ($50/kg), an uncosted lot dated 15 Oct uses $40, one dated 5 Nov uses $50, and one
  dated 1 Sep uses $40 (earliest after); a newly costed lot dated 10 Oct changes the 15 Oct
  lot's estimate to its price on the next read; turning `use_last_known_price` off makes all
  three `unknown`.
- AC59 (estimates don't chain): lot B estimated from lot A; lot C, the same material dated after
  B, uses A's price (B is not a source).
- AC60 (cycle): a lot that is both consumed by and produced from the same execution reports a
  `cycle` warning and status `partial`, and the read returns 200 (no recursion error).
- AC61 (no flow history): an execution completed before flows existed (actual_inputs set, no
  `consumed` flows) reports status `partial`, warning `no_flow_history`, and its input lots in
  `missing`; after the backfill it reports normally.
- AC62 (settings): `GET /settings` returns `use_last_known_price true` for an org with no row;
  `PUT` stores it; a `PUT` with a non-boolean returns 400.
- AC63 (delete entry): `DELETE /lots/<id>/cost/<entry_id>` deactivates the entry (kept for
  audit, `deactivated_at` set); the lot then falls back to its estimate or `unknown`.

## Phasing

| Phase | Delivers | Outcome |
| --- | --- | --- |
| 1 | Scopes; accounts + bank-transaction sync; account defaults; purchase rules with pre-fill and "remember this"; Purchases page (record / already in stock / not stock / skip / refunds / review / bulk); historical runs; derived notice + Home card; manual and free cost; last known price; `cost_flows` hooks + backfill; roll-up computed on read; cost readiness; lot cost panel; batch cost card; Add Inventory total paid; permissions; feature flag | Any producer gets a real cost per bottle, complete as soon as each material has been costed once. No setup required. |
| 2 | Bills and supplier credits (credits are negative allocations, like refunds); margins with duty; duty if sold today; litres split option; material price history; auto-record rules; "paid for by" on Add Inventory | Profit per product over time. |
| 3 | Stock value and month-end snapshots; Xero P&L fetch; bridge (periods from the first snapshot on); closing stock export; closed-month figures held fixed | Accountant-ready stock figure and an explained tie-back to Xero. |
| 4 (opt-in) | Overheads into batch cost (rent, freight, labour as a configured rate per litre or per batch); freight added to a purchase's landed cost | Full absorption costing for those who want it. |

Phases 1–3 are the product. Phase 4 stays opt-in per org and is never needed for a cost per
bottle.

### Phase 1 as MRs (roadmap 8.1a–e), each shippable on its own

| MR | Contents | ACs |
| --- | --- | --- |
| 8.1a Cost engine | slice skeleton, permissions, `costing` feature, `costing_settings`, `cost_flows` + hooks + output identity + backfill, `lot_cost_entries` (manual / free), roll-up computed on read, lot and execution cost API | AC22–AC29, AC31–AC32, AC36–AC37, AC40–AC42 (8.1a routes), AC52–AC63. Migration owns `cost_flows`, `lot_cost_entries`, `costing_settings` |
| 8.1b Xero purchases in | scopes, `xero_accounts`, `purchase_documents/lines`, account defaults, sync | AC1–AC4. Migration owns those three tables |
| 8.1c Rules and actions | `purchase_rules`, `purchase_allocations`, record/link/not-stock/skip/refund/review/bulk/historical APIs, changes-later rules | AC5–AC20, AC30, AC34–AC35. Migration owns `purchase_rules`, `purchase_allocations`, the `costing_settings` 8.1c columns |
| 8.1d Purchases page | page, dialog, tabs, bulk, historical UI, derived notice, Home card | AC21, AC43 |
| 8.1e Cost where people look | lot cost panel, batch cost card, readiness API + page, Add Inventory total paid | AC38–AC39 |

Whistlebird as the worked example: switch on, reconnect Xero, run history from 2026-04-01,
work through the cards using "already in stock" where lots exist, and save a rule for each
regular supplier. From then on new purchases arrive pre-filled.

## Assumptions (defaults chosen; the founder can overturn any in review)

- ASSUMPTION A1: Roadmap ID is 8.1 (new Phase 8), sub-items a–h. Rejected: folding into Phase 3.
- ASSUMPTION A2: Costs are stored and shown excluding GST (every target customer is GST
  registered). Rejected: a per-org inc-GST basis — dropped from Phase 1 to keep one money basis.
- ASSUMPTION A3: Last known price is on by default. Rejected: off (a forward-only org would see
  no complete cost until all old stock is used).
- ASSUMPTION A4: With no `cost_share` set, joint outputs split by quantity; heads/tails/feints
  take cost unless the producer marks them `byproduct`. Rejected: auto-detecting by-products by
  name.
- ASSUMPTION A5: Closing stock is an export only; nothing is posted to Xero. Rejected: manual
  journals (needs write scope and an accountant's sign-off).
- ASSUMPTION A6: `costs.view` and `costs.manage` go to Admin and Staff (MEMBER) by default, and
  are grantable to custom roles. Rejected: admin-only (blocks the person who does the buying).
- ASSUMPTION A7: Costing sits behind its own feature subscription; whether it is a paid add-on
  is a pricing decision for plan item 6.3, not this build.
- ASSUMPTION A8: "Cost per bottle" in Phases 1–3 is materials + packaging (+ duty at sale from
  Phase 2); overheads only via opt-in Phase 4.
- ASSUMPTION A9: Library stock remainders take no share of a batch's cost in Phase 1, so the
  bottles carry it all (slightly overstating bottle cost; reused Library stock enters a later
  batch at 0). Rejected: a per-mL share, because bottle volume isn't recorded yet. Revisit with
  the Phase 2 litres split.
- ASSUMPTION A11: Xero's `CurrencyRate` direction is unverified, so Phase 1 stores foreign-currency
  purchases with `fx_status = needs_rate` and no base amount. Verify against one real multi-currency
  transaction, then convert (Whistlebird is NZD only, so nothing it buys is affected).
- ASSUMPTION A10: Phase 1 stores no cost caches; every figure is computed on read. Rejected:
  stale-flag caches (the invalidation rules were the main source of review gaps, and current
  tenants are small).

## Resolved during spec review (code facts)

- R1 (was V1): output lots are created in `complete_step` via `create_inventory_item` with
  `source_execution_step_id` but no `source_output_id`; produced quantity is the created
  quantity → captured as a `produced` flow at creation; backfill reconstructs it.
- R2 (V2): no path reopens a completed step. No hook needed.
- R3 (V3): `reconcile_output_to_untracked_reduce_only` creates no output lot; only the surplus
  becomes one → `reconciled_in` flow on the untracked lot.
- R4 (V4): transfer destination → `transfer_receipt_id → transfer → source_item_id`.
- R5 (V5): permissions and role defaults live in `app/core/security/access_policy.py`
  (`PERMISSIONS`, `ROLE_PERMISSIONS`, route table); there is no `sales.revenue`.
- R6 (V6): Xero sync jobs are synchronous bookkeeping, not a queue → no caches, compute on
  read.
- R7 (V7): scopes `accounting.banktransactions.read`, `accounting.settings.read`,
  `accounting.reports.profitandloss.read`. LineItemID stability after an edit in Xero's UI is
  undocumented → `superseded_at` handles a vanished key.
- R8 (V8): excise joins FIFO allocations to invoices; tasting sales are excluded (earlier
  removals); no per-sale-line duty API yet → Phase 2 adds one in the nz_alcohol module.
- R9 (V9): in-app notifications are derived system findings → the purchases notice is one.
- R10: every lot creation goes through `InventoryRepository.create_inventory_item` (the only
  `InventoryItem(` constructor outside models).

## To verify at build

- V10. 8.1a uses two partial unique indexes instead of `NULLS NOT DISTINCT`; 8.1c's
  `purchase_rules` uniqueness does the same (resolved: portable whatever the production version).
- V11. How a dashboard summary card and a derived system finding are registered (the
  `core.get_dashboard_summary` sections and `compliance_checks/system_status.py`).
- V12. Resolved: the backfill reads `inventory_item.created` / `quantity_adjusted` entity events
  and `actual_inputs`; other decreases don't affect unit cost and aren't reconstructed.

## 8.1b build contract — Xero purchases in

This section is the definitive contract for MR 8.1b (v2, after spec-critic). Where "Data model"
and "Xero sync changes" above say more, the rest arrives in 8.1c (rules, allocations, line
state, review reasons) and Phase 2 (bills). 8.1b stores purchases and classifies them; nothing
is shown to users yet and nothing is linked to stock.

**Tables (migration `costing_purchases_001`).**

- `xero_accounts` (crm slice): `id`, `org_id`, `xero_account_id` (unique per org), `code`, `name`,
  `type`, `account_class`, `status`, `default_treatment` (Layer 1, recomputed every sync; null
  for non-expense accounts), `treatment_override` (nullable; set only through the accounts API,
  never by sync), `last_synced_at`. Effective account treatment = override, else default.
- `purchase_documents` (costing slice): as in "Data model", with `source` = `xero_bank` only,
  `kind` = `spend` | `refund`, plus `xero_tenant_id`, `fx_status` (`ok` | `needs_rate`),
  `bank_account_name`, `is_reconciled`. Unique `(org_id, source, external_id)` (Xero ids are
  GUIDs). Totals are null when any live line's amount is null.
- `purchase_lines`: `document_id` (composite FK, cascade), `account_id` (composite FK to
  `xero_accounts (org_id, id)`; the line's account by Xero `AccountID`), `line_key`, `position`
  (1-based), `fingerprint`, `description`, `item_code`, `quantity`, `source_unit_amount` (Xero's
  `UnitAmount` as sent: document currency, the document's `LineAmountTypes`, unsigned as Xero
  sends it), `account_code` / `account_name` (snapshots), `amount_ex_tax`, `tax_amount` (base
  currency, 4 dp, signed — see Amounts; null when the document `needs_rate`), `treatment`,
  `superseded_at`, timestamps. **Partial** unique index `(org_id, document_id, line_key) WHERE
  superseded_at IS NULL`. 8.1c adds `treatment_rule_id`, `treatment_override`, `state`,
  `not_stock_amount`, `review_reason`.
- `costing_settings` gains `start_date` (date), `purchases_cursor` (timestamptz),
  `purchases_tenant_id` (the Xero tenant the cursor belongs to), `base_currency` (3 letters,
  from Xero's Organisation, refreshed every purchases sync).
- `xero_sync_jobs` gains `purchases_synced INTEGER NOT NULL DEFAULT 0` and `purchases_status`
  (`synced` | `not_enabled` | `needs_reconnect` | `failed`, nullable).

**SDK mapping (xero_python 4.x, tested with real model objects).** `Account.account_id`, `.code`,
`.name`, `.type.value`, `._class` (a string), `.status`; `Organisation.base_currency.value`;
`BankTransaction.bank_transaction_id`, `.type` (string), `.status` (string), `.contact.name` /
`.contact_id`, `.date`, `.reference`, `.currency_code.value`, `.currency_rate`,
`.line_amount_types.value`, `.bank_account.name`, `.is_reconciled`, `.updated_date_utc`,
`.line_items`; `LineItem.line_item_id`, `.account_id`, `.account_code`, `.description`,
`.item_code`, `.quantity`, `.unit_amount`, `.line_amount`, `.tax_amount`. Enums are read
through `.value`, never `str()`.

**What is fetched.** First the Organisation (base currency) and the full chart of accounts.
Then `BankTransactions` with `where=(Type=="SPEND" OR Type=="RECEIVE")`, all statuses, every page
(100 per page). **Bootstrap** (no cursor, or the connected tenant isn't `purchases_tenant_id`):
also `AND Date >= DateTime(start_date)`, no modified-since. **Incremental**: modified-since =
`purchases_cursor` only, no date predicate; locally, a transaction is accepted if its
`external_id` is already stored (whatever its date now) or its date is on/after `start_date`.
So a stored transaction edited to an earlier date is still updated. Overpayments, prepayments
and transfers are never stored.

**Which lines are stored.** A line's account is the cached account whose `xero_account_id` =
`LineItem.AccountID`; if the line has no `AccountID`, the one cached account with that
`AccountCode` (none or several → unknown). A line is stored only when that account has
`account_class = EXPENSE`; other and unknown accounts are skipped (logged). A transaction with no
storable line is not stored; an already-stored one is kept and its live lines are superseded.
Status `AUTHORISED` → `active`; `DELETED` / `VOIDED` → `voided`: a stored document's lines
are kept exactly as they were, whatever lines Xero sends with the void (often none); a voided
transaction never stored before is not stored. An account that stops being an expense account
has its live lines superseded (`retire_account_lines`, the seam 8.1c extends for recorded lines).

**Amounts.** Per line, ex-tax in the document currency: `LineAmountTypes` `Exclusive` →
`LineAmount`; `Inclusive` → `LineAmount − TaxAmount`; `NoTax` → `LineAmount`, tax 0. Base
currency: a document in the org's `base_currency` is taken as is (its rate is ignored). A
**foreign-currency document is stored with `fx_status = needs_rate` and null base amounts** in
Phase 1: the direction of Xero's `CurrencyRate` is unverified (ASSUMPTION A11), and a wrong
guess would misprice stock silently. Signs: stored = `sign × source`, `sign = +1` for `SPEND`,
`−1` for `RECEIVE` (refund); a negative source line (a discount) therefore stays negative on a
spend. Round half-up to 4 dp. A missing or malformed `LineAmount` (or, for `Inclusive`, a missing
`TaxAmount`) leaves the amount **null**, never 0; such a line makes the document totals null.
`source_unit_amount` is NUMERIC(18,6).

**Line identity.** Two branches. **With a `LineItemID`**: `line_key` = that id; a later sync
updates the row in place whatever changed. **Without**: `line_key = pos:<n>`; the `fingerprint`
= SHA-256 of canonical JSON (sorted keys, no spaces) of `{description, account_id, item_code,
quantity, source_unit_amount, amount_ex_tax, tax_amount}`, where text is Unicode-NFC,
whitespace-collapsed and stripped (null stays JSON null, distinct from ""), and decimals are
canonical strings (`Decimal.normalize()`, so `10` and `10.00` match). Same key and same
fingerprint → the row is kept; same key, different fingerprint → the old row is superseded and
a new row inserted; a live key not returned → superseded. Example: A, B then A, X, B keeps
`pos:1` (A), supersedes the old `pos:2` (B), inserts new `pos:2` (X) and `pos:3` (B).

**Treatment.** One seam, `classify_line(line, account)` in `purchase_sources.py`: in 8.1b it
returns the account's effective treatment; 8.1c extends it with rule and manual precedence.
Sync, account PUT and account-default changes all go through it; nothing bulk-writes a
treatment.

**Account default keywords (Layer 1, exact).** Name is casefolded and split into words on
anything that isn't a letter or digit. Checked in order: a word starting with `excise` or `duty`
→ `duty`; a word starting with `rent`, `wage`, `salar`, `power`, `light`, `heating`, `fuel`,
`vehicle`, `freight`, `courier`, `postage` → `overhead`; otherwise `DIRECTCOSTS` → `stock`, any
other `EXPENSE` account → `not_stock`. ("Current" does not match `rent`: no word starts with it.)

**Unit of work and failure.**
1. If the org lacks the `costing` feature: `purchases_status = not_enabled`; nothing else.
2. `start_date` is set with the sync job row (same commit, before any sales or purchases work),
   the first time a costing org syncs: today in NZ time. It is the activation anchor and never
   moves on its own.
3. Scopes: only a **non-blank** stored scope list that lacks `accounting.banktransactions.read`
   or `accounting.settings.read` is rejected up front (`needs_reconnect`); a blank or null list
   is unknown, so the calls are attempted and an insufficient-scope answer from Xero also gives
   `needs_reconnect`. Neither adds an error.
4. The organisation, accounts, documents, lines and the new `purchases_cursor` /
   `purchases_tenant_id` / `base_currency` are written in **one savepoint**. Helpers never
   commit. Any other failure rolls back only that savepoint (account-cache changes included),
   adds an error and sets `purchases_status = failed`.
5. An expired token during the purchases phase is recorded as `failed` with an error, not
   raised, so the job is still finalised. The job is finalised once, with its purchases
   fields, in the sync's own commit. A sync
   whose sales phases succeeded (even with zero rows) and whose purchases phase failed is
   `partial`. The sales cursor only advances on a fully successful sync, as today; re-fetching
   sales is idempotent.
6. On success `purchases_cursor = started_at − RESUME_OVERLAP`.

`purchases_synced` = remote transactions processed this run that have at least one stored line
(an unchanged retry counts again). Skipped lines and documents are logged, not stored.

**API.** `GET /api/core/costing/accounts` (expense accounts with `default_treatment`,
`treatment_override`, effective `treatment`, live line count) — `costs.view`;
`PUT /api/core/costing/accounts/<xero_account_id>` `{"treatment": "stock"|"not_stock"|"duty"|
"overhead"|null}` exactly (null clears the override) — `costs.manage`; returns the account row;
404 for another org's or a non-expense account. Downgrade of `costing_purchases_001` refuses
while any `treatment_override` exists.

**ACs (8.1b).** AC1–AC4 above (read through the service, not a tab, until 8.1c), and:
- AC64: every Layer-1 keyword maps as listed (one case each), near-misses don't ("Current account
  fees" → `stock`); non-expense and unknown accounts, and `SPEND-TRANSFER` / `SPEND-OVERPAYMENT`
  / `RECEIVE-PREPAYMENT`, are not stored; a mixed transaction keeps only its expense lines.
- AC65: `Inclusive` $103.50 with $13.50 tax → 90.0000; `Exclusive` 90 → 90.0000; `NoTax` 90 →
  90.0000, tax 0; a negative discount line on a spend stays negative.
- AC66: a base-currency document ignores its rate; a foreign document is `needs_rate` with null
  amounts and null totals; base currency comes from Xero's Organisation.
- AC67: positional A, B → unchanged resync keeps both rows; B, A supersedes both and inserts two;
  A, X, B as in the example; `10` vs `10.00`, `None` vs `""`, a `|` in a description, and a
  tax-only change behave as the fingerprint rule says.
- AC68: a line with a `LineItemID` is updated in place whatever changes; a dropped id is
  superseded.
- AC69: `DELETED` voids the document and keeps its lines.
- AC70: an account override survives the next accounts sync, re-classifies that account's live
  lines (through `classify_line`), and `null` reverts; a renamed account code keeps its lines
  (matched by `AccountID`) and the override still applies; validation 400s; `costs.view` only →
  403; another org's account → 404 and its lines untouched.
- AC71: without the feature no Xero call and `not_enabled`; a non-blank scope list lacking a
  scope → `needs_reconnect`, job `completed`; a blank list → calls attempted; insufficient-scope
  from Xero → `needs_reconnect`; a purchases exception after accounts were written → job
  `partial`, account cache unchanged, `purchases_cursor` unchanged, sales phases ran.
- AC72: the first run sets `start_date` (kept even if that run fails) and fetches with the date
  predicate and no modified-since; the next uses modified-since only; a stored transaction edited
  to before `start_date` is still updated; a new one dated before it is ignored; a different
  connected tenant bootstraps again; `purchases_synced` counts as defined.
- AC73: two orgs with the same Xero transaction and account ids store separate rows; a line can't
  reference another org's account (composite FK).

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

Rescaling never crosses zero: a new amount of 0 or with the other sign orphans the allocations instead
(amounts kept as they were), sets `review_reason = amount_changed` and clears `not_stock_amount`.
`GET /purchases` returns `{tab, counts: {to_record, recorded, skipped, not_stock}, cards: [...]}`.

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

## 8.1c-2 build contract — purchase rules, pre-fill, bulk, historical runs

**Tables (migration `costing_rules_001`).** `purchase_rules` as in "Data model", with:
`payee_pattern` / `description_pattern` stored normalised (casefold, whitespace collapsed,
stripped); `account_code` exact; `match_type` applies to the two patterns; at least one matcher
(check); uniqueness via one unique index on `(org_id, coalesce(account_code,''),
coalesce(payee_pattern,''), coalesce(description_pattern,''), match_type)` (portable, V10).
`purchase_lines` gains `treatment_rule_id` (composite FK to the rule, `ON DELETE SET NULL
(treatment_rule_id)`). `costing_settings` gains `last_history_from`, `last_history_to`.

**Matching (round-2 gap 13).** A rule matches a line when every matcher it sets matches: the
line's `account_code` equals `account_code`; the document payee, normalised, equals
(`exact`) or contains (`contains`) `payee_pattern`; the line description, normalised, likewise
for `description_pattern`. Among active matching rules the winner is, in order: more matchers
set (3 > 2 > 1); then `exact` over `contains`; then a payee matcher over a description-only
one; then the most recently updated; then the smaller id. So payee + account beats payee only,
which beats account only, which beats the account default (AC15).

**Treatment.** `classify_line(line, account, rule)` returns the winning rule's treatment, else
the account's effective treatment, and sets `treatment_rule_id`. Creating, changing,
deactivating or deleting a rule re-classifies live lines whose state is `open` or `skipped`
and that have no allocations (AC17); other lines keep their treatment. The sync classifies
every line it writes with the current rules.

**Pre-fill.** Every To record card gains `prefill: {source: "rule"|"last_time"|"none", rule_id,
rows: [{name, inventory_type, unit, quantity, amount, ask: [...]}]}` for a spend line:
- from the winning `stock` rule's template: `amount` = open × share ÷ 100 (4 dp, half-up) for
  percentage rows; the one `"rest"` row takes open − the others (never below 0). Quantity:
  `fixed` → `quantity`; `from_price` → amount ÷ `unit_price` (4 dp); `ask` → null and `quantity`
  in `ask`. `ask` also lists `batch_number` / `expiry` where the row's flags are set.
- else from the most recent recorded line of the same normalised payee: its allocations' lots
  (name, type, unit, quantity) with amounts in the same proportion of this line's open amount
  (`source = last_time`, suggestion only);
- else one empty row with the whole open amount (`source = none`).

**Rules API** (`/api/core/costing/rules`, GET `costs.view`; POST/PUT/DELETE `costs.manage`):
body `{account_code?, payee_pattern?, description_pattern?, match_type, treatment, template?,
is_active?}`; a template only on `stock`; template validation: 1–20 rows, each with name, unit,
`inventory_type` raw_material|final_product, `quantity_mode` fixed (quantity > 0) | from_price
(unit_price > 0) | ask, `share` a number in (0, 100] or `"rest"`; at most one `"rest"`; Σ
percentages ≤ 100. A duplicate matcher set → 409. 404 across orgs.

**Remember this** — `POST /purchases/<line_id>/remember` on a `recorded` or `partly_recorded`
spend line (`costs.manage`): creates (or updates, if one with the same matchers exists) a
`stock` rule matching payee (exact, normalised) + account, whose template has one row per
active allocation (lot name, type, unit, quantity `fixed`, share = allocation ÷ line amount ×
100 to 4 dp, `ask_batch_number` / `ask_expiry` set when the lot has one). No `"rest"` row.

**Not-stock rule** — `POST /purchases/<line_id>/not-stock` accepts `{"always": true}`, which
also creates (or updates) a `not_stock` rule for payee (exact) + account (AC10).

**Bulk** — `POST /purchases/bulk {line_ids: [...] (≤ 200, unique), action: skip|not_stock|
apply_rule}` (`costs.manage`): each line in its own savepoint; result `{results: [{line_id,
ok, error?}]}`; a line of another org is `{ok: false, error: "not found"}` and nothing else
happens (AC13). `apply_rule` re-classifies the line with current rules and returns its card.

**Historical runs (round-2 gap 10)** — `POST /purchases/historical-run {from, to}`
(`costs.manage`; `from` ≤ `to`, both required, `to` ≤ today, range ≤ 3 years): stores
`last_history_from/to`, and **always** fetches Xero for that range
(`Date >= DateTime(from) AND Date <= DateTime(to)`, no modified-since) and upserts with the
start-date filter lifted for that call, inside the same savepoint rules as the sync; returns
`{documents, lines}`. A second identical run fetches again and creates no duplicates (the upsert
keys). `GET /purchases?historical=1&from=&to=` lists, in that range, ignoring `start_date`:
To record also includes `skipped` lines (actionable), and Not stock lines carry `undo: true`
(Undo = `reopen`). Needs the purchases scopes; without them → 409 `needs_reconnect`.

**ACs (8.1c-2).** AC10, AC13–AC20 above, plus:
- AC81: precedence — every tiebreak row of "Matching", one test each.
- AC82: template validation 400s (two rest rows; shares > 100; bad mode; template on a
  non-stock rule); duplicate matchers → 409.
- AC83: pre-fill from `last_time` and `none`; `from_price` quantity; rest never negative.
- AC84: deleting a rule re-classifies open lines back to the account default and leaves
  recorded ones; `treatment_rule_id` is nulled.
- AC85: historical run validation (from > to, future to, > 3 years) → 400; no scopes → 409.
- AC86: bulk with > 200 or duplicate ids → 400.

## 8.1e-1 build contract — readiness and "total paid" (backend)

8.1e is split: **8.1e-1** (this) = the readiness API, Add Inventory "total paid", cost fields
on existing detail APIs; **8.1e-2** = the lot cost panel, batch cost card and readiness page
(UI, through `page-design`). No migration.

**Products (round-2 gap 15).** A product is keyed by its step output definition: key
`output:<source_output_id>` for `final_product` lots that carry one (from production flows),
and for terminal-step output definitions with an id in any process; plus one legacy key per
normalised name, `name:<normalised>`, for `final_product` lots without a `source_output_id`.
Display name = the output definition's name (else the lot name). Two definitions with the same
name are two products.

**`GET /api/core/costing/readiness`** (`costs.view`) → `{products: [{key, name, ready,
materials_total, materials_costed}]}` sorted by name. **`GET /readiness/<key>`** →
`{key, name, basis: "latest_batch"|"declared_inputs", execution_id, ready, materials: [{name,
inventory_item_id|null, costed, status}]}`; unknown key → 404.
- `latest_batch`: the execution that most recently produced a lot of the product (latest
  `produced` flow by `(created_at, id)`). Materials = every lot consumed by that execution that
  isn't produced by it; a consumed lot produced by **another** execution is walked into that
  execution the same way (iteratively, each execution once). A material lot is `costed` when
  its lot cost status is `actual` or `estimated`. One row per lot, sorted by name.
- `declared_inputs` (no batch yet): the declared `inputs` names of every step of the process
  that declares the output; a material is costed when any directly priced lot of that
  normalised name has an `actual` cost (the last-known-price rule). `inventory_item_id` null.
- `ready` = every material costed (and at least one material).

**Add Inventory "total paid".** `POST /api/core/inventory` accepts optional `total_paid`
(money ≥ 0, ≤ 4 dp). When the user has `costs.manage` and the org has the `costing` feature, the
lot and a flow price entry on its `created` flow (amount = total_paid, quantity = the lot's
quantity) are written in **one transaction**; an invalid value → 400 and no lot. Otherwise the
field is ignored. Not applied when the request adds quantity to an existing barcode lot.

**Cost fields on detail APIs.** Not in this MR (each existing detail payload is owned by
another slice); the 8.1e-2 UI reads the costing endpoints directly. AC40's "detail APIs omit
cost fields" is satisfied trivially and stays pinned by a test that no existing inventory or
execution payload contains `unit_cost`.

**ACs (8.1e-1).** AC38, AC39, plus:
- AC87: two output definitions both named "Gin" are two products; a lot without
  `source_output_id` lands in `name:gin`.
- AC88: a batch whose input WIP came from a different, earlier batch lists that batch's raw
  materials too; each execution is walked once (a loop terminates).
- AC89: `total_paid` without `costs.manage`, or without the feature, creates the lot and no
  entry; `total_paid` "-1" or "abc" → 400 and no lot.
- AC90: readiness is org-scoped (another org's key → 404; lists never cross orgs);
  `costs.view` needed (PRODUCTION → 403).

## Open for 8.1b–e (round-2 review gaps not on the engine's path)

Each must be resolved in this spec, with ACs, before its MR is built:

- Gap 4: "Already in stock" candidates must include lots with a manual whole-lot price (AC8);
  the flow price then takes precedence (AC55) and the manual entry is deactivated. (8.1c)
- Gap 9: positional `pos:<n>` line keys need a content fingerprint so a reordered or inserted
  Xero line supersedes instead of silently moving allocations. (8.1b)
- Gap 10: historical runs always refetch their range idempotently; align AC20. (8.1c)
- Gap 12: system-finding alerts need a generic `required_permission` filter and a provider
  seam so Core holds no costing check id. (8.1d)
- Gap 13: complete, deterministic rule precedence and where account overrides persist. (8.1c)
- Gap 14: tab placement for every review reason. (8.1c/d)
- Gap 15: readiness keyed by `source_output_id`, with a legacy name-only bucket. (8.1e)
- Gap 18: ACs for every Phase 1 UI promise (rules UI, cost panel, batch card, readiness page,
  history UI, phone width). (8.1d/e)
- Minor: foreign-currency formula and rounding (8.1b); list-route isolation in AC42 (8.1c–e);
  Phase 3 immutable valued movements before the first snapshot (Phase 3).

## Out of scope

- Posting anything to Xero.
- A material/item master table (materials are identified by normalised lot name).
- Purchase orders, supplier price lists, reorder suggestions.
- Accounting sources other than Xero (the `purchase_sources` seam leaves room).
- Time tracking (Phase 4 absorbs labour as a configured rate, not tracked hours).

## 8.1f-2 build contract — margins with duty (API)

Spec "Margins (Phase 2)", built as an API in this MR (`GET /api/core/costing/margins`); the page
in Sales follows in its own MR.

**Revenue.** `SaleLine` gains `revenue` (ex GST, base currency): the Xero line amount, less its
tax when the invoice's lines are tax-inclusive (inferred: Σ line amounts = invoice total →
inclusive; = sub-total → exclusive; otherwise the line amount as is). A foreign-currency invoice
has `revenue = None` (shown as not tracked, never converted here). Shared across the line's batch
allocations by units.

**Cost.** Per allocation: units × the lot's unit cost (`CostEngine.lot`), carrying its status.
Units with no lot are costed at the product's average unit cost (the mean of its costed lots'
unit costs, weighted by units) and flagged `estimated`; with no costed lot at all they are
`unknown` and their cost is left out (and the row says so).

**Duty.** From the excise module's `measure(session, org, [(lot, units)], sold_on)` per
allocation: costing never computes rates. Unallocated units use any lot of that product as the
measure. Duty is `null` ("not tracked") when the org's NZ Alcohol module is off (AC48) or a lot
can't be measured.

**Returns.** Credit notes (ACCRECCREDIT, `AUTHORISED`/`PAID`) on mapped lines reduce revenue in
their month by the line amount; returned units reduce cost at that month's average unit cost
(`estimated`) unless the line was marked "not returned to stock".

**Report.** `GET /margins?from=YYYY-MM&to=YYYY-MM` (default: the last 6 months). Per product
per month: units, revenue, production cost, cost status, duty (or null), gross margin $ (revenue
− cost − duty when tracked, else revenue − cost) and %, average cost per unit; `lines` drill-down:
invoice reference, date, units, revenue, batches (lot id, name, units, unit cost, status).
Needs `costs.view` **and** `sales.view` (AC47).

**ACs (8.1f-2).** AC45 (as written: 12 units at $480 ex GST on a lot at 4.75/unit → cost $57,
duty from the module, margin = 480 − 57 − duty), AC46, AC47, AC48, plus:
- AC102: a tax-inclusive invoice's revenue is its line amounts less tax.
- AC103: a credit note line reduces that month's revenue and units; the cost it reverses is
  `estimated`.
- AC104: margins never cross orgs.

## 8.1f-1 build contract — bills and supplier credits in

Phase 2 starts with what the founder asked for at the outset: purchases that arrive as **bills**
(and supplier credits) come in beside card spend, through the same pipeline, page and rules.

**Fetch.** `XeroAPIClient.get_bills(modified_after, from_date, to_date)`: invoices with
`Type=="ACCPAY"`, every status, all pages. `get_bill_credit_notes(modified_after, from_date,
to_date)`: credit notes with `Type=="ACCPAYCREDIT"`. Same scopes as sales (`accounting.invoices`
covers both); same cursor, bootstrap from `start_date`, and historical ranges as bank
transactions. A failure in either rolls back the whole purchases phase, like today.

**Store.** One upsert path for every source (refactor of `upsert_bank_transactions`): a source
adapter turns a Xero object into a header (external id, payee, date, reference, currency, rate,
line-amount types, lines, status) and the shared code does lines, keys, fingerprints, tax,
currency, voids, restores, amount changes and rules exactly as for bank transactions.
- Bills: `source = xero_bill`, `kind = spend`; reference = "Bill <number>" plus Xero's reference.
- Supplier credits: `source = xero_bill_credit`, `kind = refund` (negative amounts, recorded
  with the existing refund action against lots).
- Status: `AUTHORISED`, `PAID` → active; `VOIDED`, `DELETED` → voided. `DRAFT`, `SUBMITTED` are
  not stored; a stored bill that goes back to draft is treated as voided (it isn't a bill now).
- Decision (deviates from the data-model table): `kind` stays `spend` / `refund` for bills and
  credits, and `source` says where it came from. Every money rule already keys off `kind`, so
  bills behave identically by construction; the page labels them from `source`.

**Migration** `costing_bills_001`: widen `ck_purchase_documents_source` to
`xero_bank | xero_bill | xero_bill_credit`. Downgrade refuses while any bill or credit is stored.

**Pre-fill.** With no rule and no last time, a line that came with a quantity (bills do)
pre-fills one row: name = the line's description (else item code), quantity = the bill's
quantity, amount = the open amount. A rule or last time still wins.

**Page.** Cards say "Bill" or "Supplier credit" (from `document.source`), and the reference.

**ACs (8.1f-1).**
- AC44 (as written): an `AUTHORISED` bill line with quantity 10 and an item code pre-fills a row
  with quantity 10; `DRAFT` and `SUBMITTED` bills are not synced.
- AC98: a `PAID` bill and an `AUTHORISED` supplier credit sync as `xero_bill` / `xero_bill_credit`
  documents, the credit's lines negative; a bank transaction and a bill with the same Xero id
  never collide.
- AC99: a bill voided in Xero after it was recorded sends its allocations to review
  (`deleted_in_xero`), as for bank transactions; a bill moved back to draft does the same.
- AC100: the purchases phase fetches bills and credits with the bank-transaction cursor rules
  (bootstrap from `start_date`, then modified-since) and historical runs fetch them for the range.
- AC101: a bill line's quantity and item code are stored on the line; the card says "Bill".

## 8.1f-3c build contract — auto-record rules

A stock rule whose template leaves nothing to ask can record matching purchases itself (spec Q2).

- `auto_record: true` is accepted only for a `stock` rule with a template whose rows are all `fixed` or
  `from_price`, ask for no batch number or expiry, and cover the whole line (shares total 100 or a
  `rest` row). Anything else is 400.
- After each purchases upsert (sync, historical run; bank transactions and bills), each line created
  in that upsert that is open, active, base-currency priced, a spend, and won by an auto rule is recorded
  through `actions.prefill` + `actions.record` as the system (no user), one savepoint per line. A failure
  is logged and leaves the line open; the sync still succeeds. Stats count `auto_recorded`.
- Cards carry `auto_recorded: true` when every active allocation has no user. Undo is the existing
  review / unlink path.

| AC | Behaviour | Test |
|---|---|---|
| AC110 | Validation accepts a full template, refuses ask / gaps / non-stock | `test_auto_record_rule_validation` |
| AC111 | A new matching line is recorded with the template's lots, amounts and quantities; re-sync never doubles | `test_new_matching_spend_is_recorded_from_rule_template` |
| AC112 | Lines from before the rule, refunds and needs-rate lines are untouched | `test_rule_does_not_touch_existing_open_line_and_excludes_refunds_and_needs_rate` |
| AC113 | A failing record leaves the line open and the sync green | `test_auto_record_failure_isolated_and_sync_succeeds` |
| AC114 | Historical runs auto-record too and report the count | `test_historical_upsert_auto_records_and_reports_count` |

## 8.1e-2 build contract — cost where people look, and cost without Xero

Added 12 Nov 2026 at the founder's request: **costing must work for an org with no Xero bank
feed** (other accounting software, or none). Xero is one way to price stock, never the only
one. Every place stock is added can carry what it cost, and every costing screen has a
designed "no accounting connected" state that points at those places instead of at Xero.

**Who sees cost.** Cost fields and panels show only to users with `costs.view` in an org with
the `costing` feature; inputs only with `costs.manage`. Without either, every page renders
exactly as before (no empty cost slots). The server tells the page: `GET /api/core/costing/me`
→ `{"enabled", "can_view", "can_manage", "xero_connected", "purchases_to_record"}`; it never
403s (a user without `costs.view` gets `enabled`/`can_*` false and no counts).

**Total paid on every Add Inventory path** (writes the same price facts as the lot cost panel):
- Manual form: an optional "Total paid (ex GST)" money field under quantity, for raw materials
  and bought-in finished goods. Shows "= $X.XX per <unit>" live as quantity or total changes.
- Barcode scan: the same field on the confirm step, for a new barcode **and** for adding
  quantity to an existing barcode lot. On add-quantity the price is a flow entry on the new
  `added` flow (amount = total paid, quantity = the quantity added), in the same transaction
  as the add; the existing lot's earlier prices are untouched. This replaces 8.1e-1's "not
  applied when the request adds quantity to an existing barcode lot".
- CSV upload: an optional `Total Paid` column (template gains it after Quantity). csv-validate
  flags a bad value on its row (negative, not a number, more than 4 dp) like any other
  problem; csv-commit writes one created-flow entry per row with a value, in the batch's one
  transaction. Ignored (not an error) for users without `costs.manage` or orgs without the
  feature; the validate response then carries `"total_paid_ignored": true` so the page says so.
- All paths: `total_paid` 0 is allowed and means "cost $0" (a manual $0 entry, not "free").

**Lot cost panel** (inventory lot detail, `costs.view`): unit cost and status in words
("$12.40 per kg", "Estimated from <lot> — $11.90 per kg", "Not costed yet"), the source
("Recorded from a purchase on 3 Oct", "Entered by hand", "Free", "From batch <name>",
"Moved from <site>"), quantity priced vs not, and for `costs.manage` on an editable lot:
"Enter total paid" / "Mark as free" / remove a hand entry. A lot whose cost comes from a batch
or a transfer explains that and links to it; it offers no input.

**Batch cost card** (batch detail, `costs.view`): cost so far, cost per unit of each output,
status in words; when Incomplete, the missing inputs by name with a link to each lot's cost
panel (`costs.manage` can price it there); "split assumed" explained in one line.

**Costs page** (Production › Costs, `/core/costing/costs`, `costs.view`): readiness per product
(name, "Ready" or "3 of 5 materials costed"), sorted not-ready first; a product opens its
materials, each linking to its lot. Empty state for an org with no products. When there are
uncosted materials and no Xero connected, the page says how to cost them (Add Inventory total
paid, or the lot's cost panel) — never "connect Xero" as the only way.

**Purchases page without Xero:** a designed empty state ("Biz-E can read purchases from Xero.
Not using Xero? Enter what you paid when you add stock.") with a link to Add Inventory and, for
admins, to the Xero connection. No error, no empty tabs.

**Home card and notification** (8.1d leftovers): "N purchases to record" with the newest
document date, linking to Purchases; hidden at zero, hidden without `costs.manage`, absent
without Xero. Through the generic system-finding provider seam (Gap 12): Core holds no costing
check id.

**Purchase rules settings** (`/core/costing/rules`, `costs.view` reads, `costs.manage` edits):
list rules (matcher in words: "Payee is Moore Wilson", "Account 310 and description contains
juniper"), treatment, template rows; add, edit, switch off, delete; conflicts (409) shown on the
field. Reached from the Purchases page and from Settings beside the Xero product mappings.

**Historical run UI** (on the Purchases page): "Load earlier purchases" opens a from/to picker
(max 3 calendar years, not in the future); runs, then shows the range in historical mode with
a clear "Back to new purchases" exit. 409 needs-reconnect shown as a reconnect prompt.

**ACs (8.1e-2).**
- AC91: barcode add-quantity with `total_paid` 30 for 3 more kg writes one manual entry on the
  new `added` flow (amount 30, quantity 3); the lot's earlier entry is unchanged; a pricing
  failure leaves neither the added quantity nor the entry.
- AC92: CSV with a `Total Paid` column creates each row's lot priced; a row with "-5" or "abc"
  is reported by csv-validate on that row; without `costs.manage` the column is ignored, rows
  commit unpriced and validate says `total_paid_ignored`.
- AC93: `GET /costing/me` for a user without `costs.view` → 200 with `enabled` false-y
  permissions and no counts; with no Xero tenant → `xero_connected` false.
- AC94: in an org with no Xero connection, a lot added with total paid gives a batch made from
  it an `actual` cost per unit; the Costs page shows the product Ready; nothing on any page
  asks for Xero as the only way to cost.
- AC95: Home card shows the to-record count to `costs.manage` only, links to Purchases, is
  hidden at zero and absent without Xero; Core contains no costing check id.
- AC96: every new panel, card, page and dialog works at 375px with no sideways scroll, in
  dark theme, and on arrival by boosted navigation (script bound to the page root).
- AC97: without `costs.view` (or without the feature) the inventory detail, batch detail,
  Add Inventory and Home pages render no cost element and make no costing write.

## 8.1f-3a build contract — material price history

Answers "what am I paying for juniper, and is it going up?". A material is every non-contract lot
sharing a normalised name. Read-only; computed on read.

- `GET /api/core/costing/materials/<name>/history?from=YYYY-MM&to=YYYY-MM` — default the twelve NZ
  months ending this one, at most 36. Per month: weighted average unit cost paid (Σ priced amount ÷
  Σ priced quantity), quantity priced, purchase count, min and max unit price, and `unconverted` (prices
  in a unit the engine cannot convert to the material's most common unit). Plus `latest` (unit price,
  date, source) and `lots` (each lot's engine cost and status).
- `GET /api/core/costing/materials` — materials with at least one price, sorted by name, for a picker.
- Needs `costs.view`; 404 for another org's material or an unknown name.

| AC | Behaviour | Test |
|---|---|---|
| AC105 | Two purchases in a month average by quantity | `test_ac105_weighted_average_across_two_purchases` |
| AC106 | A refund lowers the month's amount, not its quantity; manual and free entries are prices | `test_ac106_*` |
| AC107 | g and kg convert; an unconvertible unit is counted, not averaged | `test_ac107_converts_compatible_units_and_counts_unconvertible` |
| AC108 | Malformed, reversed or over-36-month ranges are 400; unknown material 404 | `test_ac108_month_bounds_and_unknown_material` |
| AC109 | Org isolation, production role refused, picker lists priced materials | `test_ac109_org_isolation_production_role_and_material_picker` |

## 8.1f-3b build contract — duty if sold today

**What it answers:** What duty would apply if each produced lot were sold today, and what its landed unit cost would be when production cost is known. Duty rates remain in the NZ Alcohol excise module.

**Response shape:**

```json
{
  "duty_today": {
    "tracked": true,
    "on": "YYYY-MM-DD",
    "per_unit": "money|null",
    "total": "money|null",
    "landed_per_unit": "money|null"
  },
  "outputs": [
    {
      "...": "existing output fields",
      "duty_today": {
        "tracked": true,
        "on": "YYYY-MM-DD",
        "per_unit": "money|null",
        "total": "money|null",
        "landed_per_unit": "money|null",
        "missing": "optional reason"
      }
    }
  ]
}
```

For multiple outputs, the top-level `total` summarizes duty across them; per-unit and landed values are lot-specific and remain null there. Each output carries its own values.

**Acceptance criteria and tests:**

- AC115 — Gin duty and landed cost match `excise.measure`: `test_ac115_gin_duty_per_unit_and_landed_cost_match_excise_measure`
- AC116 — NZ Alcohol disabled returns untracked duty: `test_ac116_nz_alcohol_off_is_not_tracked`
- AC117 — Missing profile returns tracked duty with a reason: `test_ac117_missing_alcohol_profile_is_tracked_with_reason`
- AC118 — Duty uses produced quantity after stock is consumed: `test_ac118_duty_uses_produced_quantity_not_remaining_stock`
- AC119 — Query count stays flat for two versus five outputs: `test_ac119_measure_query_count_is_constant_for_two_and_five_outputs`
- AC126 — Excise measurement runs once for all output lots: `test_ac126_excise_measure_runs_once_for_all_output_lots`
- AC127 — Execution duty remains org-isolated: `test_ac127_execution_duty_remains_org_isolated`
- AC128 — Batch card reads `duty_today`: `test_ac128_batch_card_reads_duty_today`

## 8.1f-3d build contract — litres split

Opt-in per org: `costing_settings.split_basis` is `quantity` (default; every existing result unchanged) or `litres`. Under litres, a step's outputs without a configured `cost_share` are weighted by litres — from an L/ml unit, or a count unit × the matching alcohol profile's pack volume — and Library stock takes its litres share (A9 revisited). If any free output's litres can't be worked out, that step falls back to the quantity rule with `split_assumed`. Percent and byproduct shares behave as before. `GET/PUT /settings` carry `split_basis` (`costs.manage` to change).

- **AC120:** Quantity basis keeps Library stock at zero share — `test_ac120_quantity_basis_keeps_library_remainder_at_zero_share`.
- **AC121:** Litres basis splits 10 × 700 ml bottles and 2 L Library stock as 7:2, with the pool allocated exactly — `test_ac121_litres_basis_splits_bottles_and_library_stock_exactly`.
- **AC122:** Missing pack volume falls back to quantity and sets `split_assumed` — `test_ac122_missing_pack_volume_falls_back_to_quantity_and_marks_assumed`.
- **AC123:** Percent cost share remains honored under litres basis — `test_ac123_percent_cost_share_is_preserved_under_litres_basis`.
- **AC124:** Settings GET/PUT, invalid value rejection, and org isolation — `test_ac124_settings_get_put_validation_and_tenant_isolation`.
- **AC125:** Migration column default and constraint — `test_ac125_split_basis_migration_has_default_and_check_constraint`; upgrade/downgrade round-trip also passed on the private `cogsl` DB.

