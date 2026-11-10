# Live batch/bottle cost (COGS) — context pack for the design session

Prepared 2026-11-10 against `origin/main` @ `1181748b`. Purpose: let the design model spend its
budget on design, not exploration. Everything below was read from the code or pulled live from
Whistlebird's Xero; file:line refs are to `origin/main`.

## The ask (founder's words)

> Design new batch or bottle live cost feature by linking up Xero purchases mapped to goods that go
> into units produced to give a real time/over time average of the cost of goods and give
> reporting into profits based on Xero reports etc.

Output wanted from the design session: a spec in `.agents/specs/` shape (data model, costing
method, roll-up algorithm, Xero sync changes, late/changed-cost handling, reconciliation to Xero
P&L, permissions, UI surfaces, acceptance criteria, phased MVP). Not code.

## Ground truth that shapes the design

### 1. No cost data exists anywhere today
`grep` for `unit_cost|cost_per|price|cogs` across `app/core`, `app/features/inventory`,
`compliant`, `contract_manufacturing` models returns nothing. No cost/price columns on any
inventory or step model. `docs/source-to-sale-plan.md` has no costing item (only 6.3 "Price by
what's included", which is Biz-E subscription pricing, unrelated). This is greenfield — it
needs a new roadmap item ID.

### 2. Whistlebird's real Xero data (pulled live 2026-11-10)
P&L 2026-04-01 → 2026-10-31, accrual:

| Line | NZD |
| --- | --- |
| Sales | 25,458.06 |
| **Cost of sales total** | **17,809.97** |
| — Excise Duty | 9,749.91 (55% of COGS) |
| — Purchases - Ingredients | 2,959.00 |
| — Purchases - Packaging | 2,106.83 |
| — Direct Rent Costs | 1,438.08 |
| — Purchases (uncategorised) | 979.40 |
| — Freight, Postage & Courier | 576.75 |
| Gross profit | 7,648.09 (30%) |
| Operating expenses | 15,842.04 (Rent 10,066 is the bulk) |
| Net profit | −8,193.95 |

Also present but zero: Opening Stock, Closing Stock, Stock Variance (Xero is on **periodic**
inventory — purchases are expensed straight to COGS, no perpetual stock asset).

**Critical finding: Xero returned zero ACCPAY bills issued since 2026-05-01**, and zero
unreconciled bank transactions Apr–Oct, yet ~$6k of purchases hit COGS. So Whistlebird's
purchases most likely go in as **spend-money bank transactions** (card/eftpos at Moore Wilson,
Countdown etc.), already reconciled, possibly with no line items or quantities. A bills-only
design would see almost none of Whistlebird's real costs. The design must handle:
- bills (ACCPAY) with line items + quantities (Biz-E's other prospects),
- spend-money bank transactions (`BankTransactions` endpoint, Type=SPEND) — often one line, a
  total, no quantity,
- receipts with no Xero record at all (manual cost entry on a stock lot),
- opening stock at go-live with no purchase record (standard/estimated cost).

The founder's own memory notes also say botanicals are bought as whole real packs at
supermarkets/wholesalers with often no email evidence (`project_whistlebird_pack_sizes`,
`feedback_whistlebird_botanical_no_email_evidence`) — quantities on the Xero side will often be
missing; the stock lot in Biz-E already has the real quantity.

### 3. Xero integration today (`app/features/crm/`)
- OAuth scopes: `openid profile email accounting.contacts accounting.invoices
  accounting.invoices.read offline_access` (`services/xero_oauth_service.py:24`).
  - `accounting.invoices` already covers ACCPAY bills.
  - Bank transactions need `accounting.banktransactions(.read)`; Xero Items need
    `accounting.settings(.read)`; P&L/reports need `accounting.reports.read`. **Not in prod yet:
    just add the scopes and reconnect — no re-consent migration or degraded mode needed.**
  - Check Xero's current scope model before finalising — Xero has been moving to granular
    scopes; verify names against their docs at build time.
- Sync pulls **ACCREC only**: `get_all_invoices` filters `Type=="ACCREC"`
  (`services/xero_api_client.py:216-232`); credit notes `ACCRECCREDIT` (`:242`).
- Storage: `xero_invoices` already has `invoice_type` (ACCREC|ACCPAY), status, totals, currency
  (`models/xero_invoice.py:30`). `xero_invoice_line_items` has description, item_code, quantity,
  unit_amount, line_amount, **account_code**, tax_type, tax_amount, tracking JSONB
  (`models/xero_invoice_line_item.py`). Bills could reuse these tables; bank transactions would
  need a new one.
- `ProductMapping` maps Xero sales descriptions → a Biz-E final product, with `match_type`
  exact|contains|alias and `units_per_line` (case of 6 → 6) (`models/product_mapping.py`). A
  purchase-side mapping (supplier line → raw-material identity) is the natural mirror.
- Sales → stock: `SalesFifoAllocation` (`crm_sales_fifo_allocations`) links each Xero sales line
  to the exact `inventory_item_id` lot(s) it came from, with quantity, `status`
  (confirmed/…), `presold` flag (`models/sales_fifo_allocation.py`). Written by
  `SalesTraceabilityService.reconcile_org` (`services/sales_traceability_service.py:36`).
  **This is the hook for "cost of this sale": sale line → lot → lot's unit cost.**
- `sales_sources.py` is the source-agnostic sales read model (`SaleLine` with
  `batches: list[(InventoryItem, units)]`) — reports should read it, not Xero tables. A
  purchase-side equivalent (`purchase_sources`) would keep MYOB/Hnry open later.

### 4. Inventory & lineage (`app/core/db/models/`)
- `InventoryItem` = one **lot** (`inventory_items`): `quantity NUMERIC(18,4)` (mutable on-hand
  cache, authoritative), `unit`, `inventory_type` raw_material|work_in_progress|final_product,
  free-text `supplier`, `purchase_date`, `supplier_batch_number`, `site_id`, `location_id`,
  `contract_customer_id` (customer-owned material → **zero cost to us**), `extra_data` JSONB.
  Lineage back-pointers: `source_execution_id`, `source_execution_step_id`, `source_output_id`.
- **Consumption is NOT in the movement ledger.** `InventoryMovementType` has only WASTAGE, ADD,
  ADJUSTMENT, PRODUCTION (`inventory_movement.py:16`). When a step completes, inputs consumed
  are recorded in `ExecutionStep.actual_inputs` JSONB:
  `[{"name","quantity","unit","inventory_item_id"}]` (`execution_step.py:44`), and the lot's
  quantity is decremented in place (`backend/execution_routes.py:758-865`, reason
  `EXECUTION_STEP_INVENTORY`). There's also an `inventory_item.consumed` entity event
  (`backend/event_writer.py:311`). So the cost graph is:
  `output lot → source_execution_id → all ExecutionSteps → actual_inputs[].inventory_item_id
  (+ quantity in that input's unit, converted to the lot's unit) → input lot's cost`, recursively
  for WIP inputs.
- Units: consumption can be in a different unit from the lot (converted via
  `app/core/utils/` unit helpers; `are_units_compatible`). Cost per unit must be stored in the
  lot's canonical unit.
- Every quantity write needs an `InventoryQuantityWriteReason`
  (`app/core/domain/inventory_quantity_guard.py:73`): wastage, execution step, sales FIFO
  consumption/reversal, opening balance, stock transfer, tasting dispatch, contract dispatch…
  Each of these is a place where value moves or is lost, and needs a costing rule.
- Wastage (`inventory_wastage` + WASTAGE movement), tastings (ADJUSTMENT), stocktake variance,
  site transfers (`site_transfer` — cost should travel with the lot), library stock remainders
  (plan item 1.2) — all have to say what happens to the cost.
- Existing tracer: `TemporalDagTracer(db, org_id, as_of, max_depth=5)`
  (`backend/temporal_dag_tracer.py:60`) walks lineage as of a time. `max_depth=5` may be too
  shallow for a full cost roll-up; check before reusing.

### 5. Excise duty is the largest cost and already computed
`app/features/compliant/modules/nz_alcohol/excise.py`: `resolve_rate(rates, tariff_item, on)`
(`:576`), `duty_for(rate, litres, lal)` (`:584`), `entry_lines` (`:746`); dispatch duty in
`movement_excise.py:27` (`prepare_dispatch_duty`). Per plan's Decisions table, NZ excise is
charged on alcohol **removed** from the licensed area per lodgement period (mainly sales), not
on production. So duty is a per-unit-sold cost known at removal, not a batch input cost — the
design has to decide whether bottle COGS includes duty (it should for margin; Xero books it in
COGS) and source it from the excise module rather than from Xero spend.

### 6. Overheads in COGS
Xero has Direct Rent Costs and Freight in COGS. Design should decide: v1 materials + packaging +
duty only ("prime cost"), with overhead absorption (rent per batch / per litre) as a later
opt-in. "Just works" principle: defaults need no setup.

### 7. Platform rules the design must obey
- Multi-tenant: every new table `TenantScoped` with `org_id`; composite `(org_id, id)` FKs
  like the existing models.
- Money figures are behind the `sales.revenue` permission (plan §0.4 roles: `sales.view`,
  `sales.revenue`, `sales.manage`). Cost figures need the same or a new `costs.view`
  permission; server enforces, UI only hides.
- Feature-slicing: new slice under `app/features/<slice>/` via `register_routes(core_bp)`
  (`.agents/plans/feature-slicing-plan.md`). Cost is used by CRM and Core → probably its own
  `costing` slice.
- "Just works": no mandatory setup; unknown costs are shown as unknown/partial, never as $0.
- Migrations go through migration-safety; reversible; no destructive changes.
- Xero sync runs as jobs (`xero_sync_job`) with rate limiting (`xero_api_client.py:36`).
- NZ time for prod, UTC in CI.

## Founder input (2026-11-10) — how purchases actually arrive

**Whistlebird has no bills.** All spending is on cards linked to the Xero bank account; Xero
pulls the card feed in and each transaction is coded to an account (e.g. Purchases -
Ingredients, Purchases - Packaging — the cost-of-sales accounts listed above). **There are no
quantities on them** — just a supplier/payee, date, amount and account.

The founder's preferred direction (the designer should treat this as a strong steer and improve
on it, not as a fixed spec):

- **Biz-E pulls every cost transaction from Xero** and uses a **mapping from Xero accounts (and
  optionally payee/description patterns) to "this is cost of goods"** — e.g. anything coded to
  Purchases - Ingredients or Purchases - Packaging is a COGS purchase. Flexible mapping setup,
  with sensible defaults so it "just works".
- **Each mapped purchase becomes a prompt in Biz-E** to record what was bought into inventory:
  item, quantity, supplier batch number, expiry, etc. — linked to that transaction, so the
  transaction's amount becomes the cost of the lot(s) created.
- The founder sees this as a **feature in its own right, not just costing plumbing**: it's the
  reminder to load ingredients into inventory at all, with quantities, batch numbers and expiry
  — so it closes the gap where purchases never get recorded (see the Whistlebird production-gap
  and botanical-evidence notes). It ties purchasing, receiving and traceability together.
- One transaction may cover several items (a supermarket shop); the design must decide how a
  single amount splits across multiple lots (user-entered split, proportional, etc.).
- **Bills (ACCPAY) must also be supported** for producers who use them, with the same flexible
  mapping — bill line items may carry quantities/item codes, so they can pre-fill the prompt.

The designer is the expert here: choose the best shape for the mapping rules, the
"record this purchase" inbox/prompt flow (where it appears, how it's dismissed or marked
not-inventory, partial recording, matching to lots already entered by hand), and how it handles
transactions that later change or are deleted in Xero.

## Design questions the session should answer (with a recommendation each)

1. **Costing method:** FIFO by actual lot (exact; Biz-E already has lot-level lineage and FIFO
   sales matching) vs weighted average per material (simpler, matches "average over time"). Likely
   answer: actual lot cost as the stored truth, with moving average shown as the trend/report view.
2. **Purchase → lot link** (see Founder input above — the purchase-prompt flow is the steer): how a Xero bill line / spend transaction becomes cost on one or more
   `InventoryItem` lots. Auto-match by supplier+description mapping+date window? Manual link UI?
   One spend covering many lots (a supermarket shop) → allocate by what?
3. **Late or changed costs:** bill arrives after the batch was made; bill edited/voided in Xero;
   lot partially consumed already. Recompute downstream (cost is derived, recalculated) vs
   snapshot at consumption time with adjustment entries. Determines whether cost is stored or
   computed.
4. **Joint outputs and yield:** one execution produces several outputs (hearts, heads/tails,
   multiple SKUs). How input cost is split (by volume, by LAL, by configured ratio). Losses
   (angel's share, wastage) absorbed into good output.
5. **Missing data:** lots with no cost (opening stock, gifts, untracked fresh peel). Standard
   cost fallback per material? Completeness % shown on every cost figure?
6. **Duty:** include per-unit excise from the excise module in bottle COGS.
7. **Reconciliation to Xero:** Biz-E's COGS for a period (cost of units sold) vs Xero's
   cost-of-sales accounts (periodic: purchases expensed). They will **not** match by design
   (Xero expenses purchases when bought, Biz-E costs when sold); the report should show the
   bridge (stock-on-hand value change) rather than pretend they agree. Possibly offer a monthly
   stock-on-hand valuation figure the accountant can post as Closing Stock journal — a
   strong value prop.
8. **Reports:** per-batch cost & cost/bottle; per-product margin over time (price from Xero
   sales lines, cost from allocated lots); stock valuation now; COGS bridge vs Xero P&L. Where
   they live (Production tab batch detail, CRM/Sales, a Finance view) — nav is Home /
   Production / Compliance (`project_nav_naming_and_shell`).
9. **Rollout:** feature flag per org. (No re-consent handling needed — app isn't in prod.)
10. **MVP cut:** smallest slice that gives Whistlebird a real cost per bottle this month (likely:
    manual cost on raw lots + bill-line linking + roll-up + duty + per-batch view), and what
    follows.

## Suggested prompt for the design session

> Read `.agents/plans/live-cogs-context-pack.md` in full. You are designing, not building.
> Using only what it says plus targeted reads of the files it cites (don't explore the wider
> repo), write a build-ready spec to `.agents/specs/live-cogs.md` covering every numbered design
> question with a decision and its reasoning, the data model (tables, columns, constraints,
> tenant scoping), the cost roll-up algorithm in pseudocode including late-cost recompute,
> Xero sync changes (bills + spend-money bank transactions + new scopes), the account-mapping rules and the "record this purchase" prompt flow from the Founder input section, the Xero P&L
> reconciliation bridge, permissions, UI surfaces, testable acceptance criteria, and a phased
> MVP where phase 1 gives Whistlebird a real cost per bottle with no mandatory setup. Flag
> anything that needs the founder to decide.
