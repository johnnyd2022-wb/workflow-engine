# SPEC: live-cogs
status: draft v3 (round 1 spec-critic gaps resolved; awaiting round 2)
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
Cost is pooled per execution and handed to output lots step by step (algorithm below). When a
step produces several lots, the pool is split by, in order:

1. a cost share configured on the process step's output (`cost_share`: a percentage, or
   `byproduct` — takes no cost); opt-in, never required. Configured percentages are scaled to
   sum to 100 over the outputs actually produced; byproducts get 0;
2. quantity, when every output's unit converts to one common unit (`are_units_compatible`);
3. otherwise everything goes to the primary output — `final_product` before
   `work_in_progress` before `raw_material`, then largest quantity, then earliest created —
   and `execution_costs.split_assumed = true` ("split assumed — confirm" on the card).

Splitting by litres of finished product (bottles × size) is a Phase 2 option.

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
All migrations are additive and reversible (downgrade drops only the new tables/columns).
Nothing is added to `inventory_items`.

Facts vs caches. **Facts** (`purchase_*`, `lot_cost_entries`, `cost_flows`) are written by
user actions, sync and Core hooks, and are never derived from each other. **Caches**
(`inventory_lot_costs`, `execution_costs`) are derived from facts only and can be dropped and
rebuilt at any time.

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
`id`, `inventory_item_id`, `cost_flow_id` (the inflow it prices; null = the whole lot), `kind`
(`manual` \| `free`), `amount`, `quantity`, `note`, `is_active`, `created_by_user_id`,
`created_at`. `free` requires `amount = 0`. At most one active entry per `(lot, cost_flow_id)`.

### `cost_flows` (every quantity into or out of a lot that cost cares about)
| Column | Notes |
| --- | --- |
| `inventory_item_id` | composite FK |
| `direction` | `in` \| `out` |
| `kind` | in: `created` \| `added` \| `produced` \| `transfer_in` \| `reconciled_in` · out: `consumed` |
| `quantity` | positive, in the lot's unit |
| `execution_id`, `execution_step_id`, `step_number` | set for `produced`, `reconciled_in` and `consumed` |
| `source_output_id` | the step output definition matched by name at write time (produced only) |
| `write_reason` | the `InventoryQuantityWriteReason` of the write that caused it |
| `reconstructed` | bool — true for rows made by the backfill rather than at the time |
| `created_at` | |

Indexes: `(org_id, inventory_item_id, direction)`, `(org_id, execution_id, step_number)`.

Written in the **same transaction** as the stock write, from three places only:

1. `InventoryRepository.create_inventory_item` → one `in` row (`created`, or `produced` when
   `source_execution_step_id` is set, or `transfer_in` when `transfer_receipt_id` is set) for
   the created quantity. Every lot creation goes through this method (checked: the only
   `InventoryItem(` constructor outside models).
2. `InventoryRepository.add_quantity_to_inventory_item` → one `in` row (`added`).
3. `complete_step` in `execution_routes.py` → one `out` row (`consumed`) per aggregated input
   lot; and for an output reconciled into an untracked lot
   (`reconcile_output_to_untracked_reduce_only`), one `in` row (`reconciled_in`) on that
   untracked lot for the reconciled amount, because that output creates no lot of its own (only
   the surplus does).

These are plain inserts with no cost logic, so they cannot fail independently of the stock
write; there is no "costing off" path that skips them. Whether costing is enabled affects only
whether costs are computed and shown.

**Backfill** (migration data step, re-runnable as a command): for every existing lot, an `in`
row for its original quantity (`created`/`produced`/`transfer_in` by the same rules), where
original = current quantity + Σ consumed (from `actual_inputs`) + Σ sales FIFO allocations +
Σ wastage + Σ other recorded decreases − Σ recorded additions, floored at the current quantity;
`out` rows from every completed step's `actual_inputs`. All marked `reconstructed = true`.

### `inventory_lot_costs` (cache, one row per lot)
`inventory_item_id` (unique per org), `quantity_in` (Σ in flows), `costed_quantity`,
`cost_actual`, `cost_estimated`, `unit_cost` (nullable), `status`, `unknown_inputs` (int),
`source` (`purchase` \| `manual` \| `production` \| `estimate` \| `customer_owned` \| `transfer`
\| `mixed`), `breakdown` JSONB, `stale` (bool), `computed_at`.

### `execution_costs` (cache, one row per execution)
`execution_id` (unique per org), `input_cost_actual`, `input_cost_estimated`, `cost_so_far`
(unabsorbed pool), `status`, `unknown_inputs`, `split_assumed` (bool), `breakdown` JSONB (per
consumed lot: quantity, unit cost, amount, status; per produced flow: allocated amount and
status — the `allocated_cost` of the algorithm lives here, not on `cost_flows`), `stale`,
`computed_at`.

### `costing_settings` (one row per org)
`start_date` (date, default the day costing is switched on), `use_last_known_price` (bool,
default true), `last_history_from`, `last_history_to` (the last historical run's range, for
"resume"), `created_at`, `updated_at`.

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

Costing uses its own uncapped, memoised walk over `cost_flows` — not `TemporalDagTracer`
(event-sourced, as-of-a-time, capped at depth 5).

```
lot_cost(lot):                                  # memoised per computation
    if lot.contract_customer_id:  return Cost(unit=0, status=actual, source=customer_owned)

    priced, unpriced = [], []                   # (quantity, amount, status) / quantity
    for f in in_flows(lot):
        if f.kind == transfer_in:
            src = transfer_source_lot(lot)      # transfer_receipt_id → transfer → source_item_id
            c = lot_cost(src); priced_or_unpriced(f.quantity, c)
        elif f.kind in (produced, reconciled_in):
            ensure cost_execution(f.execution) has run
            priced += (f.quantity, allocated_cost[f], status[f])
        else:                                   # created / added
            a = allocations (active or orphaned) + active cost entries paying for f (by cost_flow_id)
            if a: priced += (Σ a.quantity, Σ a.amount, estimated if any orphaned else actual)
            else: unpriced += f.quantity
    whole_lot = allocations/entries with cost_flow_id null  # "this purchase paid for this lot"
    if whole_lot: priced += (Σ quantity, Σ amount, actual); unpriced = []
    refunds = Σ negative allocations             # reduce amount, never quantity

    if priced:
        unit = (Σ priced.amount + refunds) / Σ priced.quantity
        status = worst(priced.status); if unpriced: status = worst(status, estimated)
        return Cost(unit, status)                # unpriced quantity takes the lot's own price
    est = material_estimate(lot) if settings.use_last_known_price
    return Cost(unit=est, status=estimated) if est is not None else Cost(status=unknown)

cost_execution(execution):                      # runs for in-progress batches too
    pool = Cost.zero()
    for step in execution.steps ordered by step_number:
        for c in out_flows(step, kind=consumed):
            u = lot_cost(c.lot)
            if u.status == unknown:  pool.note_unknown(c.lot)       # pool becomes partial
            else:                    pool.add(c.quantity * u.unit, u.status)
        outs = in_flows(step, kind in (produced, reconciled_in))
        if outs:
            weights = split_weights(step, outs)                     # Q4 precedence
            for o in outs: allocated_cost[o] = pool * weights[o]    # rounding remainder → largest
            pool = Cost.zero()
    execution_costs.cost_so_far = pool          # live cost while running; production loss if it never reaches an output
```

Status order (worst last): `actual` < `estimated` < `partial` < `unknown`. A batch with any
unknown input is `partial`: its `cost_so_far` and `unit_cost` exclude that input and the API
returns `unit_cost: null` alongside `cost_so_far` (shown as Incomplete).

Precision: unit costs to 6 dp, money to 4 dp, rounding half-up; displayed to cents.

**Same material** (for last known price and readiness): two lots are the same material when
`normalise(name)` matches and their units are compatible (`are_units_compatible`), where
`normalise` lower-cases, trims, collapses whitespace and strips a trailing
`" - Library stock"`. The estimate is the unit cost (converted to this lot's unit) of the most
recent lot of that material with an actual cost dated on or before this lot's
`purchase_date` (else `created_at`); failing that, the earliest one after. Estimates never chain
from other estimates.

A cycle (a lot fed by a batch that consumed that same lot) is broken at the back edge using
the lot's cost excluding that inflow; the lot is marked `partial` and a warning is logged.

### Recompute

No job queue exists (Xero sync jobs run synchronously), so recompute is **mark stale, compute
on read**:

```
mark_stale(lot_ids):                            # same transaction as the fact change
    walk forward: each lot → executions that consumed it (out_flows) → lots those executions
    produced from that step onward → …; plus lots whose last-known-price source is in the set
    set stale = true on those inventory_lot_costs and execution_costs rows (insert if missing)

read(lot | execution):
    if row missing or stale: recompute that node and its stale ancestors, in dependency order;
    upsert; stale = false
```

Triggers for `mark_stale`: allocation created/changed/orphaned; `lot_cost_entries` change; a
purchase line amount change on sync; any `cost_flows` insert; a `cost_share` change on a
process (all its executions); `use_last_known_price` toggled (whole org).

A read recomputes at most 500 nodes; beyond that it returns the stale cached figure with
`"updating": true` and the remainder is finished by the next read or by
`uv run workflow costing rebuild --org <id>` (also run at the end of every Xero purchases
sync). The rebuild drops and recomputes both caches for the org; for the same facts it must
produce the same values as incremental reads (AC18).

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
| Library stock remainder | an ordinary output lot; takes its share under Q4 |

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
     allocation per row with `cost_flow_id` = that flow. Then `mark_stale`.
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
| Amount changed | line amount updates | each active allocation and `not_stock_amount` is rescaled by new ÷ old (rounded to 4 dp, remainder to the largest allocation); quantities unchanged; `review_reason = amount_changed`; `mark_stale` |
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
  treatments, applies the "When Xero changes later" rules, and calls `mark_stale` for lots whose
  allocations moved. It ends by running the org's costing rebuild.
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

| Endpoint | Method | Permission |
| --- | --- | --- |
| purchases list, candidates, readiness, lot cost, execution cost, settings, rules (read) | GET | `costs.view` |
| record, link, not-stock, skip, reopen, review actions, bulk, historical run | POST | `costs.manage` + `inventory.adjust` (record creates stock) |
| lot cost entry | PUT | `costs.manage` |
| rules, accounts, settings | POST/PUT/DELETE | `costs.manage` |

Every costing endpoint is registered in the access-policy route table (default deny). API
responses from other slices that gain cost fields (lot detail, execution detail, Add Inventory)
**omit** those fields unless the user has `costs.view`. Every costing route also returns 404
when the org's `costing_enabled` subscription is off.

tenant_scoped: yes. Every query filters `org_id`; every cross-table link is a composite
`(org_id, …)` key; `mark_stale`, reads and rebuild never cross orgs.

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

Cost payload, everywhere a cost is returned:
`{"unit_cost": "4.750000" | null, "cost_so_far": "95.0000", "status": "actual|estimated|partial|unknown",
"actual": "90.0000", "estimated": "5.0000", "missing": [{"inventory_item_id", "name"}],
"split_assumed": false, "updating": false}`.

CLI: `uv run workflow costing rebuild --org <id> [--all]` and
`uv run workflow costing backfill-flows --org <id>` (idempotent).

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

Phase 1 — cost roll-up
- AC22: A raw lot with no cost, where an earlier lot of the same material (name differing only
  in case and spacing, unit g vs kg) has an actual $45/kg, reports 45.000000/kg `estimated`.
  With no costed lot of that material, or `use_last_known_price` off, it reports
  `unit_cost: null`, status `unknown`.
- AC23: A lot marked free reports `unit_cost 0.000000`, status `actual`; a lot with
  `contract_customer_id` reports `0.000000`, `actual`, source `customer_owned`.
- AC24: A 2 kg lot costed $90 that later has 3 kg added with a $120 allocation reports
  42.000000/kg `actual`; if the added 3 kg has no cost, it reports 45.000000/kg `estimated`.
- AC25: A batch whose step 1 consumes 1 kg of a 45/kg lot and 10 L of a 5/L lot and whose final
  step produces 20 units reports `cost_so_far 0`, each output 4.750000/unit, `actual`.
- AC26: Before any output is recorded, that batch's cost reports `cost_so_far 95.0000` and
  `unit_cost null`.
- AC27: A step producing 8 L and 2 L splits its pool 80/20; with the 2 L output configured
  `byproduct`, the 8 L output takes 100%; with outputs in kg and units (incompatible), the
  `final_product` output takes 100% and `split_assumed` is true.
- AC28: A batch that consumed one `unknown` lot reports status `partial`, `missing` naming it,
  `cost_so_far`/allocation excluding it, and `unit_cost null` on its output; after a manual
  cost is entered on that lot, the next read returns a complete `unit_cost`.
- AC29: In a two-step batch where step 1 produces a WIP lot that step 2 fully consumes, the
  final output's cost equals the step-1 inputs plus step-2 inputs, each counted once.
- AC30: Linking a purchase to a raw lot after a batch consumed it changes that batch's output
  unit cost on the next `GET /executions/<id>/cost` and the output lot's `GET /lots/<id>/cost`.
- AC31: An output reconciled into an untracked lot writes a `reconciled_in` flow for the
  reconciled amount on that lot, which then carries its share of the batch cost.
- AC32: A site transfer's destination lot reports the source lot's unit cost.
- AC33: For an org with 3 batches and mixed facts, deleting all cache rows and running
  `costing rebuild` yields `inventory_lot_costs` and `execution_costs` rows equal, column by
  column except `computed_at`, to those produced by reading every lot and execution
  incrementally after each fact was added.

Phase 1 — Xero changes later
- AC34: A recorded line whose Xero amount changes from $90 to $99 has its allocation rescaled
  to $99 (quantity unchanged), `review_reason = amount_changed`, and the lot's next read is
  49.500000/kg.
- AC35: A recorded line deleted in Xero keeps its lot and quantity; the allocation is
  `orphaned`; the lot reports the same unit cost with status `estimated`; the line shows in To
  record with `review_reason = deleted_in_xero`. Review `keep` clears the reason; `unlink`
  removes the allocation and the lot reverts to estimate/unknown.

Phase 1 — Core hooks, surfaces, access
- AC36: Creating a lot through Add Inventory, uploading inventory, completing a step with
  outputs, and adding quantity each write exactly one `in` flow of the written quantity, in the
  same transaction (a forced rollback of the stock write leaves no flow). Completing a step
  writes one `consumed` flow per input lot.
- AC37: The backfill on a DB with existing lots and completed steps writes `reconstructed`
  flows such that, for every lot, Σ in − Σ consumed − Σ other recorded decreases equals its
  current quantity; running it twice adds nothing.
- AC38: Add Inventory with "total paid $50" for 5 kg creates the lot and a manual entry; the lot
  reports 10.000000/kg `actual`. The field is absent from the form for a user without
  `costs.manage` and ignored by the API if sent.
- AC39: `GET /readiness/<product>` for a product whose latest batch consumed a costed and an
  uncosted raw material (via a WIP lot) lists both raw materials with `costed: true/false` and
  `ready: false`; once the second is costed, `ready: true`. A product with no batch lists its
  process's declared step inputs.
- AC40: A user with neither costing permission gets 403 on every costing route; a user with
  `costs.view` only gets 403 on every POST/PUT/DELETE; lot and execution detail APIs omit cost
  fields for users without `costs.view`.
- AC41: With `costing_enabled` off, every costing route returns 404, no cost fields appear,
  and step completion and stock writes still write `cost_flows`.
- AC42: For every costing route, a request naming another org's line, lot, execution or rule
  returns 404 and changes nothing (one cross-tenant test per route).
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

## Phasing

| Phase | Delivers | Outcome |
| --- | --- | --- |
| 1 | Scopes; accounts + bank-transaction sync; account defaults; purchase rules with pre-fill and "remember this"; Purchases page (record / already in stock / not stock / skip / refunds / review / bulk); historical runs; derived notice + Home card; manual and free cost; last known price; `cost_flows` hooks + backfill; roll-up with stale-on-change; cost readiness; lot cost panel; batch cost card; Add Inventory total paid; permissions; feature flag | Any producer gets a real cost per bottle, complete as soon as each material has been costed once. No setup required. |
| 2 | Bills and supplier credits (credits are negative allocations, like refunds); margins with duty; duty if sold today; litres split option; material price history; auto-record rules; "paid for by" on Add Inventory | Profit per product over time. |
| 3 | Stock value and month-end snapshots; Xero P&L fetch; bridge (periods from the first snapshot on); closing stock export; closed-month figures held fixed | Accountant-ready stock figure and an explained tie-back to Xero. |
| 4 (opt-in) | Overheads into batch cost (rent, freight, labour as a configured rate per litre or per batch); freight added to a purchase's landed cost | Full absorption costing for those who want it. |

Phases 1–3 are the product. Phase 4 stays opt-in per org and is never needed for a cost per
bottle.

### Phase 1 as MRs (roadmap 8.1a–e), each shippable on its own

| MR | Contents | ACs |
| --- | --- | --- |
| 8.1a Cost engine | slice skeleton, permissions, `costing_enabled`, `costing_settings`, `cost_flows` + hooks + backfill, `lot_cost_entries`, caches, roll-up, stale/rebuild, lot and execution cost API | AC22–AC33, AC36–AC37, AC40–AC42 (engine routes) |
| 8.1b Xero purchases in | scopes, `xero_accounts`, `purchase_documents/lines`, account defaults, sync, changes-later rules | AC1–AC4, AC34–AC35 (sync side) |
| 8.1c Rules and actions | `purchase_rules`, `purchase_allocations`, record/link/not-stock/skip/refund/review/bulk/historical APIs | AC5–AC20, AC35 (review) |
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
- R6 (V6): Xero sync jobs are synchronous bookkeeping, not a queue → stale-on-change, compute on
  read, rebuild at the end of each purchases sync.
- R7 (V7): scopes `accounting.banktransactions.read`, `accounting.settings.read`,
  `accounting.reports.profitandloss.read`. LineItemID stability after an edit in Xero's UI is
  undocumented → `superseded_at` handles a vanished key.
- R8 (V8): excise joins FIFO allocations to invoices; tasting sales are excluded (earlier
  removals); no per-sale-line duty API yet → Phase 2 adds one in the nz_alcohol module.
- R9 (V9): in-app notifications are derived system findings → the purchases notice is one.
- R10: every lot creation goes through `InventoryRepository.create_inventory_item` (the only
  `InventoryItem(` constructor outside models).

## To verify at build

- V10. Postgres version supports `NULLS NOT DISTINCT` (15+); otherwise a unique index on
  `coalesce(...)` expressions.
- V11. How a dashboard summary card and a derived system finding are registered (the
  `core.get_dashboard_summary` sections and `compliance_checks/system_status.py`).
- V12. Which recorded stock decreases the backfill can read (FIFO allocations, wastage,
  movements, tasting and contract dispatch) — any it can't read go into the floor rule.

## Out of scope

- Posting anything to Xero.
- A material/item master table (materials are identified by normalised lot name).
- Purchase orders, supplier price lists, reorder suggestions.
- Accounting sources other than Xero (the `purchase_sources` seam leaves room).
- Time tracking (Phase 4 absorbs labour as a configured rate, not tracked hours).
