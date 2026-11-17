# Design review: public MCP, live cost, production planning and sales analytics

Date: 17 Nov 2026. Read against `origin/main` at `6ce608e3` (16 Nov 2026).
Living copy with the same content: https://claude.ai/artifact/PhFGRBmiAimXUVoeDFtE2A

## Verdict

The architecture holds up. Seven confirmed issues should be fixed before MCP is switched on for a
production organisation, or before its calculations are described as authoritative. Four are
security or data-integrity problems in the MCP and costing designs. Three are calculations in
planning and sales analytics that give wrong or contradictory numbers.

Keep these decisions as they are: the MCP server calls the app's API and holds no database
credentials; the app is the only authorization server; `execute` is a declarative call list with
no model-written code; cost is derived on read from facts; an unknown cost is never shown as $0.

"Confirmed in code" below means the behaviour was read on `origin/main`. "Risk" means it needs a
measurement or a decision before it counts as a defect.

## Scope

| Area | Reviewed | Kind |
| --- | --- | --- |
| Public MCP (8.2) | `.agents/specs/public-mcp.md`, `.agents/plans/public-mcp.md`, `bize_mcp/`, `app/api/middleware/tenant_context.py`, `app/core/security/access_policy.py`, `app/features/mcp_oauth/` | Spec + code |
| Live cost (8.1) | `.agents/specs/live-cogs.md`, `live-cogs-overheads.md`, `live-cogs-packs.md`, `app/features/costing/` | Spec + code |
| Production planning (7.3) | `docs/planned-batches.md`, `docs/production-demand.md`, `app/features/planning/` and its README, `docs/knowledge/planning.*` | Docs + code, no spec |
| Sales analytics | margins contract 8.1f-2, `app/features/crm/` analytics routes and `xero_invoice_repo.py` | Part spec, part code |

## Security findings

- **S1. Security: the app does not enforce the MCP allowlist (token bypass).** Confirmed in code.
    - Problem: `token_scope_includes` (`app/core/security/access_policy.py:507`) checks only that the
      method is GET/HEAD and the route needs a view permission; it never checks `x-bize.mcp`. In
      `docs/openapi.json`, 160 of 178 GET operations are token-reachable; 28 are in the catalogue.
    - Impact: anyone holding a token can call the public app directly, skipping the MCP server's row
      caps, 30/min execute limit and `mcp.execute` audit. Reachable this way: customer records,
      invoice PDFs, evidence and process-doc downloads, NP3 audit files, recall contact notices, the
      stock snapshot CSV. Audience binding protects nothing because the app accepts the token from any caller.
    - Fix: enforce `x-bize.mcp` in `token_scope_includes` (deny by default), and accept `bza_` tokens
      only from the MCP container (a service credential or network rule).
    - Status: fixed in !735 (the token rule now requires `x-bize.mcp`, read once from the overlay; deny by default. Accepting tokens only from the MCP container is DR-S1B.)
- **S2. Security: read-only bypass, because some GET routes write irreversible state.** Confirmed in code.
    - Problem: `GET /api/core/costing/stock-value` (in the MCP catalogue) takes and commits the
      month-end snapshot for an org with no Xero (`app/features/costing/routes.py:675`), which is then
      held fixed. `GET /api/core/costing/bridge` calls Xero's P&L API on every request
      (`app/features/costing/bridge.py:87`). The other reachable GET routes have not been checked.
    - Impact: a read-only assistant can perform an irreversible month close and spend the org's Xero rate limit.
    - Fix: no snapshot on a token request; a test that runs every token-reachable GET against a
      session that fails on flush. L1 removes the write from the read path entirely.
    - Status: fixed in !734 (a token read takes no month-end snapshot and the bridge skips Xero's P&L; invoice-defaults no longer asks Xero; a guard runs every token-reachable GET and fails on any write or Xero call)
- **S3. Security: consent cannot tell a real client from an impostor (authorization).** Confirmed in code.
    - Problem: every client is created with `verified=False`
      (`app/features/mcp_oauth/services/client_registry.py:142`, `:354`) and nothing sets it true;
      registration is open.
    - Impact: Claude and an attacker's client named "Claude" look identical on consent. An admin who
      approves a crafted link grants rolling 30-day read access. The redirect host and per-org
      off-by-default limit this but don't close it.
    - Fix: seed verified records for known clients by metadata URL or redirect URIs; an org setting,
      default on, allowing verified clients only.
    - Status: fixed in !740 (a cited verified list in code matched by redirect URIs and metadata URL, never by name; orgs allow verified apps only unless an admin opts in; consent blocked and bearer 403 for unverified clients)
- **S4. Security: rate limits are per worker, so brute-force limits are doubled.** Confirmed in code; production config not checked.
    - Problem: gunicorn runs `WEB_CONCURRENCY=2` by default and the limiter keeps counts in process
      memory unless `[ratelimit] storage_uri` is set; the templates leave it commented out.
    - Impact: 120/min per grant is really 240; 10 registrations/hour is 20. One request can walk the whole cost graph (L6).
    - Fix: a shared store before any production org enables MCP, and a lower limit for `calculation` operations.
- **S5. Refresh-token reuse has no grace window, so retries crash the grant.** Risk.
    - Problem: presenting a replaced refresh token revokes the grant
      (`app/features/mcp_oauth/services/token_service.py:197`).
    - Impact: a client retrying after a lost response disconnects itself.
    - Fix: accept the previous token for 30–60 s and return the same successor.
- **S6. Security: text written outside the org reaches the model (data leak risk).** Risk; needs validation.
    - Problem: portal users, Xero payees/descriptions and customer names are third-party text; the
      only defence is a sentence in each tool description.
    - Impact: an assistant that also has email or web tools can be steered into sending data out.
    - Fix: list which fields in the 28 operations carry outside text; mark them by origin, leave
      portal-authored text out by default, and say so beside the enable switch.

## Cross-cutting findings

- **X1. Incorrect revenue: two figures, both published as authoritative.** Confirmed in code.
    - Problem: `GET /api/crm/analytics/monthly-sales` sums `XeroInvoice.total`
      (`app/features/crm/repositories/xero_invoice_repo.py:391`): GST-inclusive, every line incl.
      freight, foreign currency unconverted, as float, while its docstring says "net revenue". Margins
      uses ex-GST, mapped product lines, base currency only.
    - Impact: the same month differs by 15%+ between Sales and margins; both are `x-bize.kind: calculation`.
    - Fix: one revenue function in `sales_sources` (ex-GST, base currency) used by both; if the invoiced
      total is wanted, name it `invoiced_inc_gst`.
    - Status: fixed in !738 (one ex-GST, base-currency rule in `sales_sources` for monthly, daily, customer and Home totals; old figure kept as `invoiced_inc_gst`; foreign currency counted in `not_converted`).
- **X2. Incorrect cost of sales: margins and the bridge disagree for one month.** Confirmed in the spec, not traced in code.
    - Problem: margins date a sale by invoice date at today's lot cost; the bridge dates movements by
      `created_at` before the cutoff at closing cost, then freezes them.
    - Impact: a sale invoiced 30 Oct and synced 2 Nov is October in one and November in the other.
    - Fix: date by sale date in both; for a closed month, margins read the frozen movements and show "changed since close".
- **X3. Incorrect stock totals: four definitions of stock on hand.** Confirmed in code.
    - Problem: costing stock value counts held, expired and not-ready lots; planner `stock.on_hand`
      counts only lots with the output's `source_output_id`, drops held/expired, subtracts pending
      inputs, ignores ready dates; `stocktake.stock_position` and the inventory list are two more.
    - Impact: "how much gin do I have" has a different answer per operation.
    - Fix: one availability module in Core with named rules (on hand, usable, sellable); each response says which rule it used.
- **X4. Possible incorrect estimates: materials are matched by name.** Risk; needs validation.
    - Problem: last known price, price history and legacy readiness match lots by normalised name and compatible unit.
    - Impact: 200 mL and 700 mL "Bottles" can share a price estimate that then counts as complete in margins.
    - Fix: don't estimate across differing packs; show the estimate's source lot wherever it feeds a
      margin. Check first whether the packs work already blocks this.

## MCP design findings

- **M1. Wrong total risk: no server-side totals, so the model sums partial pages.** Confirmed in code.
    - Problem: lists cap at 50 rows; `select` projects fields but there is no filter, sum, count or sort.
    - Impact: the model adds up the first page; the truncation note is a request, not a control.
    - Fix: every `list` operation returns `total_count` and a server-computed total of its main
      quantity; add a few aggregate operations (stock by product, batches by period, sales by product).
- **M2. Incorrect traces: results that must be complete are cut short.** Confirmed in code.
    - Problem: nested lists in a calculation are cut to 50 with a note and no cursor (`_cap_lists` in `bize_mcp/tools/execute.py`).
    - Impact: a partial forward trace (the scope of a recall) is presented as an answer.
    - Fix: trace, excise and reconciliation are complete-or-fail; over the limit they return counts and a link to the app page.
- **M3. Context limits are loose.** Confirmed in code.
    - Problem: one `execute` may return 256 KB (~60–70k tokens); `docs` 20,000 chars; records come back whole.
    - Fix: cap output near 32 KB; a default compact projection per operation in the overlay.
- **M4. Nothing tests that the assistant gets the right answer.** Gap.
    - Problem: "prefer layer-3 operations" is a description instruction; `discover` is keyword scoring with no synonyms.
    - Fix: 20–30 real questions with known answers on seeded data as a regression set; `aliases` in topic frontmatter where it misses.
- **M5. Knowledge and catalogue can drift.** Confirmed in the spec; low.
    - Problem: knowledge ships in the MCP image; the catalogue comes live from the app; they deploy separately.
    - Fix: version the catalogue and drop unresolved operation links when serving a topic.

## Analytics findings

- **A1. Incorrect totals: margins silently drop unmapped sales.** Confirmed in code.
    - Problem: `app/features/costing/margins.py:170` discards `_unmapped` from `sale_lines`.
    - Impact: margins revenue is below Xero's by an unshown amount.
    - Fix: return an `unmapped` total (revenue, line count) beside the product rows.
    - Status: fixed in !738 (margins return `unmapped: {revenue, lines, not_converted}` beside the rows).
- **A2. Past figures move without a marker.** Confirmed in the spec.
    - Problem: cost is computed on read; a late purchase or setting change moves last quarter's margin. Only stock value has a frozen close.
    - Impact: numbers copied out through MCP later disagree with the app.
    - Fix: `as_of` and `provisional` (true until the month closes) on margins and batch cost responses.
- **A3. Sales analytics has no spec.** Gap. Write the contract with worked numbers before calling monthly sales, customer breakdown or contact analytics authoritative.

## Production planning findings

All in `app/features/planning/forecast_service.py` unless stated.

- **P1. Miscalculated forecast: the seasonal factor counts the current season twice.** Confirmed in code.
    - Problem: `weekly_rate` scales the trailing-N-week average by last year's next N weeks ÷ last year's
      annual average. The trailing average already sits at this season's level.
    - Impact: 100/wk average, 150/wk Oct–Dec, 80/wk Jan–Mar. On 31 Dec it forecasts 150 × 80/100 = 120;
      right is 150 × 80/150 = 80 (50% high). End of September it is about 15% low (128 vs 150).
    - Fix: factor = last year's next N weeks ÷ last year's trailing N weeks, keeping the clamps.
- **P2. Incorrect run-out date: it ignores when planned stock arrives, and counts blocked plans.** Confirmed in code.
    - Problem: `cover_row` uses `available = on_hand + planned − ordered` then `today + available ÷ rate`;
      the per-batch ready dates from `planned_output` are discarded, and `blocked` batches count as supply.
    - Impact: a batch eight weeks out hides a stock-out in week three.
    - Fix: walk supply by ready date (the net-requirements engine in `engine.py` already does this);
      show blocked batches separately.
- **P3. Miscalculated rate: new products are under-forecast.** Confirmed in code.
    - Problem: the rate divides by the full window even when the first sale is inside it; out-of-stock weeks count as zero demand.
    - Impact: a three-week-old product on a 12-week window shows a quarter of its rate.
    - Fix: divide by weeks since first sale (with a floor) and say so on the row.
- **P4. Incorrect on-hand: it counts only lots made by the workflow.** Confirmed in code; size needs validation.
    - Problem: `stock.on_hand` filters on `source_output_id`; bought-in, imported and legacy lots have none.
    - Fix: count Whistlebird's finished lots without `source_output_id` before choosing how to match them.
- **P5. Planning docs no longer describe the code.** Confirmed.
    - Problem: `docs/planned-batches.md` says the start check always blocks and nothing is netted; the
      code now has material, capacity and compliance blockers, forecasts and targets. No spec in `.agents/specs/`.
    - Fix: write one, with worked examples for P1–P3.

## Live cost findings

- **L1. Irreversible close: a month closes itself before its purchases are recorded.** Confirmed in code.
    - Problem: `ensure_month_end_snapshots` (`app/features/costing/stock_value.py:965`) snapshots on the
      first sync or costing read after month end, pricing at costs known then and freezing B; no grace period.
    - Impact: the closed value is priced on estimates and the bridge's "not recorded as stock" is
      frozen high; the accountant's CSV is the frozen one.
    - Fix: freeze quantities at the cutoff automatically; keep valuation provisional until a
      `costs.manage` user closes the month or a set day (e.g. the 20th).
- **L2. Incorrect stock value: foreign-currency purchases can't be costed from Xero.** Confirmed in code.
    - Problem: non-base documents are `needs_rate` with no amount and accept no action
      (`app/features/costing/purchase_sources.py:432`); assumption A11 is unresolved.
    - Fix: confirm the rate direction on one real transaction, or let the user type the NZD paid.
- **L3. Costs exclude GST for everyone.** Risk; business assumption.
    - Problem: A2 assumes every customer is GST registered; NZ registration is compulsory only above $60k turnover.
    - Fix: ask the pilot producers; if any is unregistered, add a per-org basis applied at sync.
- **L4. Margin duty is claimed to equal what is lodged, untested.** Risk.
    - Fix: one test and one report line reconciling the month's margin duty to the excise period.
- **L5. Absorbed overhead is never compared with actual.** Risk.
    - Problem: rates are typed; Xero overhead lines are stored but shown "untouched"; freight can enter cost three ways.
    - Fix: show absorbed overhead beside Xero's overhead accounts per period.
- **L6. Performance: every cost read walks the graph, and MCP multiplies reads.** Risk; needs measuring.
    - Fix: time margins and stock value at 10× Whistlebird's size before enabling MCP in production; lower limit for calculations (S4).

## Gaps

- An admin can't see what an assistant read: `mcp.execute` / `mcp.request` are log events only, not `audit_logs` or Connected apps.
- Grants never expire from disuse (M1 follow-up); no org-wide disconnect; no notice when a new app connects.
- The enable switch doesn't say customer data goes to a third-party, usually offshore, AI provider. Check the privacy position with an adviser.
- "Read and write" would inherit S1 and S2; fix them first.
- Costing and planning assume NZ time throughout; blocks a first Australian customer.
- Stale spec text: the 8.2d deploy section still expects `tools/list` to contain `search_inventory`; the plan's directory layout still lists per-area tool modules.

## Fix order

Before any production org enables MCP:

1. Enforce `x-bize.mcp` in the app's token rule; accept tokens only from the MCP container (S1).
2. No snapshot on token requests; test every reachable GET for writes (S2).
3. Seed verified clients; default orgs to verified-only (S3).
4. Shared rate-limit store; check the production config (S4).

Before the numbers are described as authoritative:

5. One revenue definition; an unmapped total on margins (X1, A1).
6. Fix the seasonal factor, time-phase run-out, correct the new-product rate (P1, P2, P3).
7. Totals on list operations; complete-or-fail traces, excise and reconciliation (M1, M2).
8. Explicit month-end close with quantities frozen automatically (L1).

Then:

9. Align sale dating between margins and the bridge; `as_of` / `provisional` on cost responses (X2, A2).
10. Resolve the FX rate direction (L2).
11. The assistant-answer question set (M4).
12. Specs for planning and sales analytics (P5, A3).
13. Tighter output limits; refresh grace window (M3, S5).

## To validate before deciding

- Is any pilot producer not GST registered? (L3)
- Does a month's margin duty equal its excise return? (L4)
- How many finished lots have no `source_output_id`? (P4)
- Can lots with different packs share a price estimate today? (X4)
- Which catalogue fields carry text written outside the org? (S6)
- How fast are margins and stock value at 10× current size? (L6)
