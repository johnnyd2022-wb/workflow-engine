# SPEC: live-cogs
status: draft v2 (design only — not yet through spec-critic)
name: Live batch & bottle cost
slug: live-cogs
blueprint: new slice `app/features/costing/`, attached through `register_routes(core_bp)`;
Xero fetch/sync additions stay in `app/features/crm/`
url_prefix: `/api/core/costing/*` (JSON), pages under `/core/costing/*`
roadmap: `docs/source-to-sale-plan.md` 8.1 (Phase 8, proposed — founder confirms the ID, F1)
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
purchase cost by month; per product, cost per unit by batch with a rolling average. The same
average doubles as the **estimate** for lots that have no cost (Q5).

A lot that receives stock more than once (quantity added to an existing lot) is costed as a
small weighted pool: unit cost = total cost in ÷ total quantity in, over its lifetime.

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

1. a cost share configured on the process step's output (a percentage, or "by-product — takes
   no cost"); opt-in, never required;
2. quantity, when all outputs are in compatible units;
3. litres, when the compliance module can give a volume for every output (bottle count × size);
4. otherwise everything goes to the primary output (final product before work-in-progress,
   largest first), and the batch cost card shows "split assumed — confirm".

Normal losses (angel's share, spillage inside a step) are absorbed automatically, because the
whole pool is spread over what actually came out. Cost consumed by a batch that never produces
an output lot is reported on the batch as **unabsorbed cost** (a production loss), never
silently dropped.

### Q5. Missing data — a cost is complete or it says what's missing
A batch or product cost is shown as **the** cost only when every input has a cost. Until then
it is shown as **Incomplete**: "5 of 7 inputs costed", the subtotal so far labelled as such,
and the missing inputs listed by name, each with a link to find its purchase or enter a price.
Margins are shown only for products whose cost is complete.

A **cost readiness** view per product lists every material its process uses and whether Biz-E
has a cost for it, so an owner starting from scratch can see exactly what's left to map.

How an input gets a cost:

- **Actual**: a purchase recorded or linked to the lot, or a price typed on the lot.
- **Last known price** (status `estimated`): the lot has no purchase of its own, but the same
  material (same normalised name, compatible unit) has been costed — use the most recent price
  on or before this lot's date, else the earliest after. This is what makes "new purchases going
  forward" work: once each material has been bought once, older stock of it is costed too. It
  is an org setting, on by default (F3); with it off, only actual costs count as complete.
- **Free**: the user marks a lot as costing nothing (gift, foraged). An actual cost of zero.
- **Customer-owned** material (`contract_customer_id` set) is zero, automatically.
- **Unknown**: none of the above. Makes everything made from it incomplete.

Every figure carries its status, the dollar split between actual and last-known-price, and the
missing inputs.

### Q6. Duty — included in margin, taken from the excise module, kept out of lot cost
Excise is charged on removal, so it is a cost of the **sale**, not of the batch. Lot cost is
production cost only (materials and packaging). The margin report adds duty per sale line from
the nz_alcohol module's own removal calculation, so the figure equals what gets lodged. The
batch cost card additionally shows "duty if sold today" (litres × ABV × current rate) so the
owner sees a full landed cost per bottle before selling.

Spending coded to the Xero duty account is classified `duty`: never offered as stock, used only
as a check line in the bridge. If the compliance module is off for an org, duty shows as "not
tracked" rather than being guessed.

### Q7. Reconciliation to Xero — a bridge, not a match
Xero expenses purchases when bought; Biz-E costs them when sold. The report shows the walk
between the two for a period (see "Xero bridge"). Biz-E also produces a stock-on-hand value by
category that the accountant can use as Closing Stock. Biz-E does **not** post journals to Xero
(F5).

### Q8. Reports and where they live
No new top-level tab (Home / Production / Compliance stay).

| Surface | Where | Phase |
| --- | --- | --- |
| Purchases page (reconcile-style cards, historical runs) | Production › Purchases, plus a Home card and a notification | 1 |
| Purchase rules (mapping settings) | beside the existing Xero product mappings | 1 |
| Cost readiness per product | Costs & margins page, linked from every incomplete figure | 1 |
| Lot cost panel (unit cost, source, edit) | Inventory lot detail | 1 |
| Batch cost card (inputs, cost per unit, vs average, duty if sold today) | Production › batch detail | 1 |
| Product margins over time | Sales area, beside existing revenue reports | 2 |
| Material price history | Costs & margins page | 2 |
| Stock value now / at month end | Costs & margins page | 3 |
| Xero bridge | Costs & margins page | 3 |

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
org's base currency, **excluding GST** by default (F2); unit costs are `NUMERIC(18,6)`.
All migrations are additive and reversible. Nothing is added to `inventory_items`.

### `xero_accounts` (crm slice — chart of accounts cache)
`id`, `xero_account_id`, `code`, `name`, `type` (Xero type, e.g. `DIRECTCOSTS`, `EXPENSE`),
`account_class`, `status`, `last_synced_at`. Unique `(org_id, xero_account_id)`.

### `purchase_documents` (costing slice — source-agnostic header)
| Column | Notes |
| --- | --- |
| `source` | `xero_bank` \| `xero_bill` \| `xero_bill_credit` \| `manual` |
| `external_id` | Xero BankTransactionID / InvoiceID; unique `(org_id, source, external_id)` |
| `kind` | `spend` \| `refund` \| `bill` \| `credit` |
| `payee_name`, `xero_contact_id` | |
| `document_date` | date; period boundaries use this in the org's timezone |
| `reference` | |
| `currency_code`, `currency_rate` | amounts are converted to base currency on sync |
| `status` | `active` \| `voided` (Xero DELETED / VOIDED) |
| `total_ex_tax`, `total_tax` | |
| `external_updated_at`, `last_synced_at` | |

Bills are stored here, **not** in `xero_invoices`. Reason: every existing reader of
`xero_invoices` assumes sales; mixing payables in risks bills leaking into revenue reports.

### `purchase_lines`
| Column | Notes |
| --- | --- |
| `document_id` | composite FK, cascade |
| `external_line_id` | Xero LineItemID when present |
| `description`, `item_code`, `quantity`, `unit_amount` | quantity is usually null on card spend |
| `account_code`, `account_name` | as coded in Xero |
| `amount_ex_tax`, `tax_amount` | base currency |
| `treatment` | `stock` \| `duty` \| `overhead` \| `ignore` \| `unclassified` — from rules |
| `treatment_rule_id` | which rule decided; null = built-in default |
| `treatment_override` | set when a user overrides for this line only |
| `state` | `open` \| `partly_recorded` \| `recorded` \| `skipped` \| `not_stock` |
| `not_stock_amount` | part of the line the user said is not stock |
| `review_reason` | null, or `amount_changed` \| `recoded` \| `deleted_in_xero` |

Check: `allocated + not_stock_amount <= amount_ex_tax` (enforced in the service, with a row
lock on the line).

### `purchase_rules` (the mapping settings — mirror of `ProductMapping`)
| Column | Notes |
| --- | --- |
| `account_code`, `payee_pattern`, `description_pattern` | matchers, each nullable; at least one set |
| `match_type` | `exact` \| `contains` (as `ProductMapping`) |
| `treatment` | `stock` \| `not_stock` \| `duty` \| `overhead` |
| `template` | JSONB, `stock` only: rows of `{material_name, inventory_type, unit, quantity_mode, quantity, unit_price, share, location_id, ask_batch_number, ask_expiry}` |
| `auto_record` | bool, default false (Phase 2) — record without a tap; refused if any row asks for batch number or expiry |
| `is_active`, `created_by_user_id`, timestamps | |

`quantity_mode` is `fixed` (always this quantity), `from_price` (amount ÷ `unit_price`, for
things sold by the litre or kilo at a known price) or `ask`. `share` is a percentage of the
purchase amount, or `rest`. `inventory_type` may be `final_product`, so bought-in finished goods
(contract-made spirit, merchandise) map straight to sellable stock. Unique on the matcher tuple
per org.

### `purchase_allocations` (purchase line → lot)
`id`, `purchase_line_id`, `inventory_item_id` (`ondelete=RESTRICT`), `amount`, `quantity`
(quantity bought, in the lot's unit — the lot's own `quantity` is mutable so it can't be used),
`status` (`active` \| `orphaned`), `created_by_user_id`, `created_at`.
Unique `(org_id, purchase_line_id, inventory_item_id)`.

### `lot_cost_entries` (costs with no purchase behind them)
`id`, `inventory_item_id`, `kind` (`manual` \| `opening` \| `free`), `amount`, `quantity`,
`note`, `created_by_user_id`. `free` requires `amount = 0`.

### `cost_step_flows` (normalised production edges)
`id`, `execution_id`, `execution_step_id`, `step_number`, `inventory_item_id`, `direction`
(`consumed` \| `produced`), `quantity` (in that lot's unit), `source_output_id` (produced only).
Indexes: `(org_id, inventory_item_id, direction)`, `(org_id, execution_id, step_number)`.

This table is a **derived index** of facts that already exist — `ExecutionStep.actual_inputs`
and the lots carrying `source_execution_step_id`. It is rebuilt per step by
`rebuild_step_flows(step)` (delete + insert), so it can never drift for long and can always be
regenerated. It exists because finding "which steps consumed lot X" from JSONB is slow and
because the lot's current quantity is not what was produced.

### `inventory_lot_costs` (cache, one row per lot)
`inventory_item_id` (unique per org), `quantity_in`, `cost_actual`, `cost_estimated`,
`unit_cost` (nullable), `status`, `unknown_inputs` (int), `source` (`purchase` \| `manual` \|
`production` \| `estimate` \| `customer_owned` \| `transfer` \| `mixed`), `breakdown` JSONB
(cost by category: ingredients / packaging / other, and the list of unknown inputs),
`computed_at`.

### `execution_costs` (cache, one row per execution)
`execution_id` (unique per org), `input_cost_actual`, `input_cost_estimated`, `unabsorbed_cost`,
`status`, `unknown_inputs`, `split_assumed` (bool), `breakdown` JSONB (per consumed lot:
quantity, unit cost, amount, status), `computed_at`.

### `costing_settings` (one row per org)
`start_date`, `cost_basis` (`ex_tax` \| `inc_tax`), `use_last_known_price` (bool, default
true), `created_at`, `updated_at`.

### Phase 3: `stock_value_snapshots` / `stock_value_snapshot_lines`
Header: `as_of_date`, `kind` (`month_end` \| `manual`), totals by category, `created_at`.
Lines: `inventory_item_id`, `quantity`, `unit_cost`, `value`, `status`. Unique
`(org_id, as_of_date, kind)`. Needed because historical on-hand cannot be reconstructed —
consumption is not in the movement ledger.

### Existing tables touched
- `xero_sync_jobs`: add `purchases_synced INTEGER NOT NULL DEFAULT 0`; `sync_type` gains
  `purchases`.
- Process step output definitions (`steps.outputs[]` JSONB): optional `cost_share` key
  (`{"mode": "percent", "value": 80}` or `{"mode": "byproduct"}`). No schema migration.

## Cost roll-up

Not built on `TemporalDagTracer`: that walker is event-sourced, as-of-a-time and capped at
depth 5. Costing uses its own uncapped, memoised walk over `cost_step_flows`.

```
lot_cost(lot):                                  # memoised per run
    if lot.contract_customer_id:        return Cost(unit=0, status=actual, source=customer_owned)
    if lot arrived by site transfer:    return lot_cost(source lot) carried at the same unit cost

    inflows = []                                # (quantity, amount, status)
    for a in purchase_allocations(lot):  inflows += (a.quantity, a.amount,
                                                     actual if a.status == active else estimated)
    for e in lot_cost_entries(lot):      inflows += (e.quantity, e.amount, actual)
    for f in produced_flows(lot):        ensure cost_execution(f.execution) has run
                                         inflows += (f.quantity, f.allocated_cost, f.status)
    if no inflows:
        est = material_estimate(lot)            # nearest costed lot of the same material, Q5
        return Cost(unit=est, status=estimated) if est is not None else Cost(status=unknown)

    unit = sum(amount) / sum(quantity)
    return Cost(unit, status=worst status among inflows, split actual/estimated kept)

cost_execution(execution):                      # also runs for in-progress batches
    pool = Cost.zero()
    for step in execution.steps ordered by step_number:
        for c in consumed_flows(step):
            u = lot_cost(c.lot)
            if u.status == unknown:  pool.note_unknown(c.lot)       # pool becomes `partial`
            else:                    pool.add(c.quantity * u.unit, u.status)
        outs = produced_flows(step)
        if outs:
            weights = split_weights(step, outs)                     # Q4 order of precedence
            for o in outs: o.allocated_cost = pool * weights[o]     # rounding remainder to largest
            pool = Cost.zero()
    execution.unabsorbed_cost = pool            # live "cost so far" while the batch is running
```

Work-in-progress made and consumed inside one execution needs no special case: the earlier
step's lot receives the pool, and the later step consumes that lot at its cost.

A cycle (a lot fed by a batch that consumed that same lot) is broken at the back edge using the
lot's cost excluding that inflow; the lot is marked `partial` and the event is logged.

### Recompute when a fact changes

```
on_change(lot_ids):                             # in the same transaction as the change
    dirty = set(lot_ids); queue = list(lot_ids)
    while queue:
        lot = queue.pop()
        for c in consumed_flows where lot == c.lot:
            for o in produced_flows(c.execution) where o.step_number >= c.step_number:
                if o.lot not in dirty: dirty.add(o.lot); queue.append(o.lot)
    also add: lots whose estimate is taken from any lot in dirty
    recompute executions and lots in dependency order; upsert both caches
```

Triggers: allocation created / changed / removed; `lot_cost_entries` change; a purchase line's
amount changing on sync; a step completing or being reopened (after `rebuild_step_flows`); a
`cost_share` change on a process (recompute that process's executions).

Up to 200 dirty lots are recomputed inline; beyond that the work is queued on the same
mechanism the Xero sync job uses and the caches show `computed_at` so the UI can say
"updating". A full rebuild is available as `uv run workflow costing rebuild --org <id>` and
must produce identical caches to the incremental path (tested).

### What each stock write means for cost

| Write reason | Cost rule |
| --- | --- |
| Execution step consumption | value moves into the batch pool at the lot's unit cost |
| Production output | lot receives its share of the pool |
| Purchase / add quantity | inflow at the allocated or entered amount |
| Sales FIFO consumption | cost of sale = quantity × lot unit cost; reversal undoes it |
| Wastage | quantity × unit cost reported as wastage cost; unit cost unchanged |
| Tasting / sample dispatch | quantity × unit cost reported as samples cost; unit cost unchanged |
| Stocktake gain or loss | valued at the lot's current unit cost, reported as stock variance |
| Site transfer | cost travels with the stock at the same unit cost |
| Contract dispatch of customer-owned stock | zero |
| Library stock remainder | an ordinary output lot; takes its share under Q4 |

## Deciding what is a stock purchase

Two layers, so it works with nothing configured and bends to any org.

**Layer 1 — account defaults.** On first sync Biz-E reads the chart of accounts:

| Xero account | Default treatment |
| --- | --- |
| Type `DIRECTCOSTS`, name contains "excise" or "duty" | `duty` |
| Type `DIRECTCOSTS`, name contains rent, wages, salaries, power, light, heating, fuel, vehicle, freight, courier, postage | `overhead` |
| Type `DIRECTCOSTS`, anything else (Purchases, Ingredients, Packaging, Consumables, Materials…) | `stock` |
| Any other expense account | `ignore` |
| Non-expense accounts (assets, liabilities, transfers) | not stored |

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

**Tabs:** To record (default) · Recorded · Skipped · Not stock. A date filter applies to all.

**Card actions:**

1. **Record stock.** One row per thing bought: material (existing or new, any inventory type),
   quantity, unit, supplier batch number, expiry, location, amount.
   - Pre-filled from the matching rule; failing that, suggested from what this payee sold
     before; failing that, empty. For bills, line description, item code and quantity pre-fill.
   - One row takes the whole amount. With several rows, amounts are typed from the receipt;
     rows with a known price are pre-filled and the last empty row takes the remainder.
   - Amounts may total less than the line — the user then picks "rest is not stock" or "more to
     record later" (`partly_recorded`). They can never total more.
   - A fully pre-filled card with nothing left to ask is a single **OK**.
   - Saving creates the lots through the existing inventory-create path (supplier = payee,
     purchase date = document date) and the allocations, in one transaction, under an
     idempotency key.
2. **Already in stock.** Link to lots entered by hand. Candidates are lots with no cost, dated
   from 3 days before to 14 days after the purchase, ranked by supplier-to-payee match. The
   user confirms quantity bought and amounts.
3. **Not stock.** A decision: this purchase isn't inventory. Optionally "always for this payee"
   (creates a rule).
4. **Skip.** Stop presenting this for now. No decision recorded.
5. **Review items.** A card with a `review_reason` shows what changed in Xero and offers
   "keep", "relink" or "edit amounts".

Bulk actions on selected cards: skip, not stock, apply a rule.

### Historical runs

**Run historical costs** asks for a date range (any start date, default end today) and opens
the page filtered to it. It fetches that range from Xero first if it predates what has been
synced. A historical run presents **every stock purchase in the range that isn't recorded**,
including ones skipped before — skipping only hides a card from the day-to-day list; it comes
back whenever a run covers its date. Purchases marked not stock are shown collapsed, with undo.
A run can be left and resumed at any time; progress is simply the state of the cards
("38 of 112 done").

The day-to-day "To record" tab shows open purchases dated on or after the org's start date.
Historical runs ignore the start date.

### Notifications

When a sync brings in new stock purchases, Biz-E raises **one** notification per sync ("3 new
purchases to record") linking to the page, and the Home card shows the open count. No
notification is raised for purchases a rule ignores or (Phase 2) auto-records. Uses the
existing in-app notification mechanism (V9); no `core_tasks` row per purchase.

### Manual cost without Xero

The lot cost panel lets a `costs.manage` user enter "total paid" for any lot, or mark it free.
The Add Inventory form gains an optional "total paid" field (Phase 1) and a "paid for by"
purchase picker (Phase 2).

The page and every dialog must work at phone width (375px) — it is used at the bench.

### When Xero changes later

| Change in Xero | Nothing recorded yet | Already recorded |
| --- | --- | --- |
| Amount changed | entry updates | allocations rescaled proportionally, costs recomputed, `review_reason = amount_changed` |
| Recoded to a non-stock account | entry leaves the page | lots and costs kept; `review_reason = recoded`; listed in the bridge |
| Recoded into a stock account | entry appears | — |
| Deleted / voided | entry disappears | lots kept; allocations become `orphaned` (cost kept but downgraded to `estimated`); `review_reason = deleted_in_xero` |
| Line items replaced | matched by LineItemID, else by account + amount + description | same, then the amount rule |

## Xero sync changes (`app/features/crm/`)

- **Scopes** added to `XERO_SCOPES`: read access to bank transactions, settings (accounts) and
  reports (profit and loss — Phase 3). Xero's granular scope names must be verified against
  current Xero docs at build time (V7); the existing `accounting.invoices` scope already covers
  bills.
- **`XeroApiClient`** gains, all paginated and using the existing retry and rate limiter:
  `get_accounts()`; `get_bank_transactions(modified_after)` for types `SPEND` and `RECEIVE`,
  including `DELETED` status; `get_bills(modified_after)` for `Type=="ACCPAY"` (Phase 2);
  `get_bill_credit_notes(modified_after)` for `ACCPAYCREDIT` (Phase 2);
  `get_profit_and_loss(from, to)` (Phase 3).
- **`XeroSyncService`** gains `_sync_accounts` and `_sync_purchases`, run as part of `full` and
  as `sync_type="purchases"`, incremental by modified-since like invoices. It upserts through a
  `purchase_sources` module in the costing slice (the mirror of `sales_sources.py`), which
  normalises to `purchase_documents` / `purchase_lines`, converts currency, normalises
  tax-inclusive line amounts to ex-tax, applies rules, and calls `on_change` for any lot whose
  allocation amount moved.
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

- New permissions: `costs.view` (see any cost, margin or stock value) and `costs.manage`
  (record purchases, edit lot costs, change rules and settings). Owner and admin roles get both.
- Margin figures need `costs.view` **and** `sales.revenue`.
- Recording a purchase also needs the existing permission to create inventory.
- Default deny, enforced on the server. API responses **omit** cost fields for users without
  `costs.view`; they are not sent and hidden.
- tenant_scoped: yes. Every query filters `org_id`; every cross-table link is a composite
  `(org_id, …)` key; `on_change` and the rebuild never cross orgs.

## API (all under `/api/core/costing`, `@requires_auth` + org scope + permission)

| Route | Purpose |
| --- | --- |
| `GET /purchases?state=&from=&to=&historical=` | purchases page list and counts |
| `POST /purchases/<line_id>/record` | create lots + allocations (idempotency key) |
| `POST /purchases/<line_id>/link` | allocate to existing lots |
| `POST /purchases/<line_id>/not-stock`, `/skip`, `/reopen` | decide, hide, undo |
| `POST /purchases/historical-run` | fetch a date range from Xero if not yet synced |
| `GET /readiness`, `GET /readiness/<product>` | which materials each product still needs a cost for |
| `GET /purchases/<line_id>/candidates` | lots that might already be this purchase |
| `GET/PUT /lots/<item_id>/cost` | lot cost panel; manual / free entry |
| `GET /executions/<id>/cost` | batch cost card |
| `GET /materials/<name>/history` | price history (Phase 2) |
| `GET /margins?from=&to=&group=` | margins (Phase 2) |
| `GET /stock-value`, `POST /stock-value/snapshot`, `GET /bridge?from=&to=` | Phase 3 |
| `GET/POST/PUT/DELETE /rules`, `GET/PUT /accounts`, `GET/PUT /settings` | purchase rules, account treatments, start date, cost basis, last-known price |

## Acceptance criteria

Phase 1
- AC1: After a Xero sync, a spend-money transaction coded to a `DIRECTCOSTS` account named
  "Purchases - Ingredients" appears in `GET /purchases` as `open` with payee, date and ex-GST
  amount, with no rules configured.
- AC2: A transaction coded to "Excise Duty", "Direct Rent Costs" or a non-direct-cost expense
  account never appears on the Purchases page.
- AC3: Recording a $90.00 purchase as one row (2 kg juniper) creates one raw lot of 2 kg and one
  allocation of $90.00; the lot's unit cost is $45.00/kg, status `actual`; the line is
  `recorded`.
- AC4: Recording a $100.00 purchase as rows of $60 and $25 with "rest is not stock" creates two
  lots, sets `not_stock_amount = 15.00` and state `recorded`. Rows totalling $101 are rejected
  with 400 and nothing is created.
- AC5: Repeating the same record request with the same idempotency key creates no second lot.
- AC6: Linking a purchase to an existing hand-entered lot creates an allocation and no new lot;
  the lot's cost status becomes `actual`.
- AC7: A raw lot with no cost, where an earlier lot of the same material cost $45/kg, reports
  $45/kg with status `estimated`. With no costed lot of that material, or with
  `use_last_known_price` off, it reports status `unknown` and `unit_cost` null — never 0.
- AC8: A lot marked free reports unit cost 0 with status `actual`.
- AC9: A lot with `contract_customer_id` set reports unit cost 0, `actual`, source
  `customer_owned`.
- AC10: A batch that consumes 1 kg of the $45/kg lot and 10 L of a $5/L lot and produces 20
  units reports input cost $95.00 and $4.75 per unit.
- AC11: While that batch has consumed inputs but produced nothing, `GET /executions/<id>/cost`
  reports $95.00 as cost so far.
- AC12: A step producing 8 L and 2 L of two outputs splits its pool 80/20. With one output
  configured `byproduct`, the other receives 100%.
- AC13: A batch that used one `unknown` input reports status `partial` (shown as Incomplete),
  names that input, returns the subtotal as `cost_so_far` and returns `unit_cost` null. Once
  that input gets a cost, the same request returns a complete `unit_cost`.
- AC14: A multi-step batch whose step-1 work-in-progress lot is fully consumed by step 2 gives
  the final output the full input cost, counted once.
- AC15: Linking a purchase to a raw lot **after** a batch consumed it updates that batch's
  output lot cost and cost per unit in the same request.
- AC16: When a recorded purchase's amount changes in Xero from $90 to $99, the allocation
  becomes $99, downstream costs update, and the line carries `review_reason = amount_changed`.
- AC17: When a recorded purchase is deleted in Xero, its lots and their quantities are
  unchanged, the allocation is `orphaned`, the lot's status is `estimated`, and the line appears
  on the Purchases page with `review_reason = deleted_in_xero`.
- AC18: `workflow costing rebuild` on an org produces caches identical to those built
  incrementally.
- AC19: A user without `costs.view` gets 403 on every costing route, and inventory and
  execution API responses contain no cost fields for them.
- AC20: No costing route returns or changes another org's purchases, lots, rules or costs
  (cross-tenant test per route).
- AC21: Purchases dated before the start date do not appear in the To record tab. A historical
  run over a range before the start date lists them.
- AC21a: A skipped purchase is absent from To record and present, as open, in any historical
  run covering its date. A not-stock purchase appears in the run collapsed with undo.
- AC21b: A historical run for a range older than the last sync fetches that range from Xero and
  lists its stock purchases; running it twice creates no duplicates.
- AC21c: With a rule "payee contains X → 20 L neutral spirit, ask batch number", a new purchase
  from X is listed with that row pre-filled and the full amount; submitting only a batch number
  creates a 20 L lot carrying the purchase amount.
- AC21d: A `not_stock` payee rule keeps that payee's purchases out of To record and raises no
  notification. A payee + account rule beats an account-only rule.
- AC21e: "Remember this for <payee>" after recording creates a rule whose template reproduces
  the rows just recorded.
- AC21f: A sync that brings in three new stock purchases raises exactly one notification
  linking to the Purchases page; a sync that brings none raises none.
- AC21g: `GET /readiness/<product>` lists every material consumed by that product's batches
  with costed / not costed, and reports the product complete only when all are costed.
- AC21h: A purchase recorded to a `final_product` lot gives that lot the purchase's unit cost
  and it is sellable and costed with no batch behind it.
- AC22: The record dialog is fully usable at 375px wide with no horizontal scroll.
- AC23: Completing a step still succeeds, and writes its `cost_step_flows`, when the org has
  costing switched off or the costing code raises (failure is logged, not surfaced).

Phase 2
- AC24: An `AUTHORISED` bill line with quantity 10 and item code pre-fills a row with quantity
  10 in the record dialog; `DRAFT` bills are not synced.
- AC25: A sale line of 12 units at $480 ex GST, allocated to a lot costing $4.75/unit with $9.20
  duty per unit, reports revenue $480, production cost $57, duty $110.40, margin $312.60.
- AC26: Sale units with no lot are costed at the product's average and flagged `estimated`. A
  product whose cost is incomplete shows revenue and "cost incomplete", with no margin figure.
- AC27: The margin report returns 403 without both `costs.view` and `sales.revenue`.
- AC28: With the compliance module off, duty is reported as not tracked (null), not 0.

Phase 3
- AC29: A stock value snapshot's total equals the sum of on-hand × unit cost over lots plus
  in-production pools, and reports the actual / estimated / unknown split.
- AC30: For a period between two snapshots, opening + recorded purchases − closing equals COGS +
  wastage + samples + variance + unabsorbed ± estimate changes, to the cent.
- AC31: The bridge lists every stock-account purchase line in the period that is not recorded as
  stock.

## Phasing

| Phase | Delivers | Outcome |
| --- | --- | --- |
| 1 | Scopes; accounts + bank-transaction sync; account defaults; purchase rules with pre-fill and "remember this"; Purchases page (record / already in stock / not stock / skip); historical runs; notification + Home card; manual and free cost; last-known price; `cost_step_flows` hook + backfill; roll-up and recompute; cost readiness; lot cost panel; batch cost card; permissions; feature flag | Any producer gets a real cost per bottle, complete as soon as each material has been costed once. No setup required. |
| 2 | Bills and supplier credits; margins with duty; material price history; auto-record rules; "paid for by" on Add Inventory | Profit per product over time. |
| 3 | Stock value and month-end snapshots; Xero P&L fetch; bridge; closing stock export; closed-month figures held fixed | Accountant-ready stock figure and an explained tie-back to Xero. |
| 4 (opt-in) | Overheads into batch cost (rent, freight, labour per litre or per batch); freight added to a purchase's landed cost | Full absorption costing for those who want it. |

Phases 1–3 are the product. Phase 4 stays opt-in per org and is never needed for a cost per
bottle.

Whistlebird as the worked example: switch on, reconnect Xero, run history from 2026-04-01,
work through the cards using "already in stock" where lots exist, and save a rule for each
regular supplier. From then on new purchases arrive pre-filled.

## Needs the founder to decide

- **F1. Roadmap ID.** Where this sits in `docs/source-to-sale-plan.md`.
- **F2. GST.** Costs are stored excluding GST. Correct for a GST-registered producer;
  `cost_basis = inc_tax` exists for one who isn't. Confirm the default.
- **F3. Last known price.** On by default: stock with no purchase of its own is costed at the
  material's last known price, so a forward-only org gets complete costs quickly. Off means a
  cost is complete only when every lot has its own purchase. Confirm the default.
- **F4. Heads, tails and feints.** Default: if they are stocked as lots they take cost by
  quantity. Recommended for Whistlebird: mark them `byproduct` so hearts carry the full cost.
- **F5. Closing stock.** Export only, no journals posted to Xero. Posting needs write access to
  manual journals and an accountant's sign-off on the method.
- **F6. Who records purchases.** v1 needs `costs.manage`, so staff without it don't see the
  Purchases page. Letting staff record quantities with amounts hidden is possible later.
- **F7. Packaging.** Is costing part of the base product or a paid add-on (plan item 6.3)?
- **F8. Overheads.** Rent and freight stay out of bottle cost until Phase 4. Confirm that
  "cost per bottle" meaning materials + packaging (+ duty at sale) is the number wanted.

## To verify at build (not read during design)

- **V1.** How and where output lots are created at step completion, and whether the produced
  quantity is recoverable for history (PRODUCTION movement, `actual_outputs`, or events). If
  not, backfill reconstructs it as on-hand + consumed + sold + wasted.
- **V2.** Whether a completed step can be reopened or undone; if so that path must call
  `rebuild_step_flows` and `on_change`.
- **V3.** Outputs reconciled into untracked items (`reconciliation` slice) and outputs added to
  an existing lot — both must produce a `produced` flow for the right lot.
- **V4.** How a site transfer creates the destination stock (`transfer_receipt_id`), to wire
  cost inheritance.
- **V5.** Where permissions are registered and how role defaults are seeded.
- **V6.** What the Xero sync job runs on, for queued recomputes and month-end snapshots.
- **V7.** Xero's current scope names, and whether LineItemIDs on bank transactions survive an
  edit.
- **V9.** What in-app notification mechanism exists for users (Home cards, notices); if none,
  Phase 1 ships the Home card and page badge and the notification follows.
- **V8.** How the excise module links a removal to a `SalesFifoAllocation`, including sales made
  from tasting stock (`tasting_allocation_id`), to expose duty per sale line.

## Out of scope

- Posting anything to Xero.
- A material/item master table (materials are identified by lot name, as elsewhere today).
- Purchase orders, supplier price lists, reorder suggestions.
- Accounting sources other than Xero (the `purchase_sources` seam leaves room).
- Labour and time costing.
