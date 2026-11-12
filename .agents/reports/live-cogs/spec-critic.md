# spec-critic — live-cogs, round 1 (Codex gpt-5.6-sol, 2026-11-10)

Captured from the Codex session transcript (read-only sandbox could not write this file).

The spec is not build-ready: 15 gaps found (10 high, 5 medium). The requested report could not be written because the workspace is read-only; `.agents/reports/live-cogs/spec-critic.md` was not created and the worktree remains clean.

Key blockers:

- Produced-lot identity is unreliable: no `source_output_id` reaches created lots, no production movements are written, and fully reconciled outputs create no output lot.
- The roll-up uses `allocated_cost` and `status` fields absent from `cost_step_flows`.
- Quantity additions lack durable cost-inflow facts; manual costs plus later purchase allocations can double-count.
- The claimed recompute queue does not exist; Xero sync is synchronous, and failed non-blocking hooks have no durable retry.
- Purchase lines lack a stable uniqueness/upsert contract; `ignore` versus `not_stock` is inconsistent.
- Changed amounts, partial allocations, refunds, and future supplier credits lack defined arithmetic.
- Permissions reference nonexistent `OWNER` and `sales.revenue` roles/permissions, with no route-method matrix.
- “Same material” normalization and cost-readiness scope are undefined.
- Numerous Phase 1 promises lack ACs, including feature gating, Home card, bulk/review actions, Add Inventory cost, and repeated-receipt averaging.
- The spec remains draft with unresolved founder decisions.
- AC18, AC21g, AC21h, and AC22 are not fully falsifiable.
- The required External Surfaces section is missing.
- No generic durable notification service exists.
- Historical runs have no persistence/resume model.
- Phase 1 does not preserve sufficient immutable valued movements for Phase 3 snapshots/bridge; supplier-credit and Phase 4 labour contracts also conflict.

V1–V9 findings:

- V1: quantities exist in `actual_outputs`, but output identity/backfill is incomplete.
- V2: no completed-step reopen path exists.
- V3: reconciliation explicitly does not create/update an output lot.
- V4: destination cost can follow `transfer_receipt_id → transfer → source_item_id`.
- V5: permissions live in `access_policy.py`; the stated roles do not match it.
- V6: Xero jobs are synchronous bookkeeping, not a queue.
- V7: current scopes are `accounting.banktransactions.read` and `accounting.settings.read`; Phase 3 P&L uses `accounting.reports.profitandloss.read`. Xero documents bank LineItemIDs but not stability after UI line replacement. [Xero scope table](https://developer.xero.com/documentation/guides/remote-mcp/overview)
- V8: excise joins FIFO allocations to invoices, while tasting sales are deliberately excluded and handled as earlier removals; no per-sale-line lodged-duty API exists.
- V9: notifications are derived system findings, not durable per-sync notifications.

F1 is resolved: the roadmap already defines 8.1a–h, with this build scoped to 8.1a–e.

VERDICT: gaps-found
---

# Spec critic — `live-cogs`, round 2

Reviewed draft v3 in `/home/johnny/wt-live-cogs` against the current `feat/live-cogs` code. No files were changed.

The rewrite substantially improves the spec, but it is not build-ready. Four round-1 gaps are fully resolved; eleven are only partially resolved. I found 18 remaining gaps.

## Round-1 gap reconciliation

1. **Produced-lot identity and reconciled outputs — partially resolved.**  
   `cost_flows` now records produced, consumed and fully reconciled quantities, so the missing-movement part is fixed. Stable output identity is not: `source_output_id` is still inferred by name ([spec lines 278–304](/home/johnny/wt-live-cogs/.agents/specs/live-cogs.md:278)), while current `complete_step` creates output lots without passing the existing `source_output_id` field ([execution_routes.py:1150](/home/johnny/wt-live-cogs/app/core/backend/execution_routes.py:1150)).

2. **Roll-up referenced absent `allocated_cost`/`status` fields — resolved.**  
   Allocated values now live in `execution_costs.breakdown`, not `cost_flows` ([lines 322–327](/home/johnny/wt-live-cogs/.agents/specs/live-cogs.md:322)).

3. **Quantity additions lacked facts and manual costs could double-count — partially resolved.**  
   Added flows now exist, and linking deactivates a flow-specific manual entry. Whole-lot entries and partially priced flows still have double-count/coverage problems.

4. **Nonexistent recompute queue — partially resolved.**  
   Stale-on-change and compute-on-read match the synchronous codebase ([lines 411–435](/home/johnny/wt-live-cogs/.agents/specs/live-cogs.md:411)). Dependency invalidation is incomplete.

5. **Purchase-line identity and inconsistent vocabulary — partially resolved.**  
   The vocabulary is unified. `LineItemID` plus positional fallback is not stable under line insertion or reorder ([lines 226–240](/home/johnny/wt-live-cogs/.agents/specs/live-cogs.md:226)).

6. **Allocation/refund/rescaling arithmetic — partially resolved.**  
   Partial recording and amount rescaling are specified, but the refund pseudocode contradicts AC12 and partial-flow quantities remain undefined.

7. **Permissions referenced nonexistent roles/permissions — partially resolved.**  
   Role names and `sales.view` now match `access_policy.py`; the stated AND-permission rules cannot be represented by its policy table alone.

8. **Same-material and readiness scope undefined — partially resolved.**  
   Normalisation and latest-batch traversal are defined. Product identity and process selection remain ambiguous when names or workflows collide.

9. **Phase-1 promises lacked AC coverage — partially resolved.**  
   AC1–AC43 cover most backend behavior, but several promised actions and user surfaces remain uncovered.

10. **Unresolved founder questions — resolved.**  
    A1–A8 provide explicit defaults and rejected alternatives ([lines 901–918](/home/johnny/wt-live-cogs/.agents/specs/live-cogs.md:901)).

11. **Untestable ACs — resolved.**  
    The replacement Phase-1 ACs are generally falsifiable.

12. **External Surfaces section absent — resolved.**  
    It is now present and materially useful ([lines 706–719](/home/johnny/wt-live-cogs/.agents/specs/live-cogs.md:706)).

13. **No durable notification service — partially resolved.**  
    Choosing a derived finding matches the codebase, but per-permission filtering and registration are not designed.

14. **Historical runs had no persistence/resume model — partially resolved.**  
    Line state plus the stored range is a coherent no-run-object model. Its fetch condition contradicts AC20.

15. **Insufficient Phase-3 movement facts and Phase-2/4 conflicts — partially resolved.**  
    Supplier credits and labour phasing are clarified. Immutable movement valuation needed for closed-period bridge arithmetic is still absent.

## Code checks that passed

- The only non-model `InventoryItem(...)` construction is in `InventoryRepository.create_inventory_item`.
- Current completed steps cannot be reopened.
- `reconcile_output_to_untracked_reduce_only` really does update only the untracked item and leaves output-lot creation to its caller.
- Site-transfer provenance can be followed through receipt → transfer → source lot.
- Xero sync jobs are synchronous bookkeeping, not a queue.
- `ADMIN`, `MEMBER`, fixed role defaults, `_ALL`, `ADMIN_ONLY`, and `GRANTABLE` behave as described.
- The test database is PostgreSQL 16, so `NULLS NOT DISTINCT` works in tests. The production version remains unverified.
- The proposed granular Xero scope names are current, and the inclusive-tax subtraction rule agrees with Xero’s documentation: [Xero scopes](https://developer.xero.com/documentation/guides/remote-mcp/overview), [Xero tax behavior](https://developer.xero.com/documentation/guides/how-to-guides/tax-in-xero).

## Remaining gaps

### GAP 1 — high: Output identity is still name-based

`cost_flows.source_output_id` is “matched by name at write time” ([lines 278–304](/home/johnny/wt-live-cogs/.agents/specs/live-cogs.md:278)), but output definitions already have stable IDs and `InventoryItem` already has `source_output_id`. Current `complete_step` discards that ID. Duplicate output names, renamed definitions, Library-stock synthetic outputs and reconstructed flows can therefore be assigned the wrong cost share.

**Suggested fix:** Require an output-definition ID in each `actual_outputs` entry, pass it into `create_inventory_item`, store it on both produced and reconciled flows, and reject an ID not declared by that execution step. Define a distinct synthetic identity for Library stock. Add ACs covering duplicate names, a renamed definition and a fully reconciled output.

### GAP 2 — high: Refunds are counted twice by the roll-up

The algorithm first includes all null-`cost_flow_id` allocations in `whole_lot`, then separately adds all negative allocations as `refunds` ([lines 365–373](/home/johnny/wt-live-cogs/.agents/specs/live-cogs.md:365)). AC12’s `$90 − $20 = $70` result would instead become `$90 − $20 − $20 = $50`.

**Suggested fix:** Exclude negative refund allocations from `whole_lot` and apply them exactly once after positive inflows are priced. State how refunds exceeding positive cost behave. Pin this with AC12 plus multi-refund and orphaned-refund cases.

### GAP 3 — high: Partial pricing of one inflow loses unpriced quantity

When an inflow has any allocation, the pseudocode adds only `Σ allocation.quantity` to `priced`; it does not add `flow.quantity − priced_quantity` to `unpriced` ([lines 356–375](/home/johnny/wt-live-cogs/.agents/specs/live-cogs.md:356)). Nor is there an invariant preventing allocations from pricing more quantity than the flow contains. A 5 kg flow with a 2 kg allocation can incorrectly appear fully actual.

**Suggested fix:** Calculate priced and residual quantity per flow, enforce `0 ≤ Σ positive allocation.quantity ≤ flow.quantity`, and mark a residual as estimated. Add under-allocation, exact-allocation and over-allocation ACs.

### GAP 4 — high: “Already in stock” contradicts AC8 and still permits manual-cost double counting

Candidates exclude every lot with an active cost entry ([lines 515–521](/home/johnny/wt-live-cogs/.agents/specs/live-cogs.md:515)), but AC8 requires linking a lot that already has a manual entry ([lines 750–752](/home/johnny/wt-live-cogs/.agents/specs/live-cogs.md:750)). Linking deactivates only an entry on the created flow; a whole-lot manual entry remains active and is then added alongside the purchase.

**Suggested fix:** Either allow manually priced candidates and deactivate every overlapping manual entry, including `cost_flow_id = null`, or change AC8 and make such lots unlinkable until their manual entry is removed. Add a whole-lot manual-entry case.

### GAP 5 — high: The backfill arithmetic cannot satisfy AC37

The backfill says it creates one reconstructed inflow plus consumed outflows only ([lines 310–314](/home/johnny/wt-live-cogs/.agents/specs/live-cogs.md:310)). AC37 nevertheless subtracts “other recorded decreases” ([lines 836–838](/home/johnny/wt-live-cogs/.agents/specs/live-cogs.md:836)), while the schema permits no out kind except `consumed`. Recorded additions are subtracted while deriving “original” but are not recreated as added flows. The resulting flow balance fails for lots with both additions and consumption.

This is also left explicitly undecided in V12 ([lines 942–949](/home/johnny/wt-live-cogs/.agents/specs/live-cogs.md:942)).

**Suggested fix:** Enumerate every authoritative historical source, add flow kinds for reconstructed additions and relevant decreases, and give every reconstructed row a stable source key/unique constraint so reruns are idempotent. Provide worked examples for create-only, add-then-consume, sale, wastage, transfer and manual correction.

### GAP 6 — high: Last-known-price invalidation misses new dependencies

`mark_stale` follows existing downstream flows and lots whose current last-known source is being changed ([lines 417–429](/home/johnny/wt-live-cogs/.agents/specs/live-cogs.md:417)). A newly priced lot may become a better source for estimated lots that did not previously depend on it. Changes to a lot’s name, unit or purchase date can also change material matching, but none is a stale trigger.

**Suggested fix:** On any actual-cost or material-identity/date change, stale all unpriced compatible lots in the affected normalised-material groups, then cascade forward. Add ACs for introducing a newer source, changing its date, renaming it and toggling unit compatibility.

### GAP 7 — high: Partial costs cannot propagate through WIP

The public contract makes `unit_cost` null for a partial output ([lines 394–396](/home/johnny/wt-live-cogs/.agents/specs/live-cogs.md:394), [AC28](/home/johnny/wt-live-cogs/.agents/specs/live-cogs.md:807)), but the next execution step multiplies `c.quantity * u.unit` for every non-unknown input ([lines 379–390](/home/johnny/wt-live-cogs/.agents/specs/live-cogs.md:379)). A partial WIP therefore has no usable internal unit value.

**Suggested fix:** Define a separate internal known-floor amount/unit cost that propagates while the external `unit_cost` remains null. Carry the missing-input set through each downstream output. Add a two-step AC where step 1 has one known and one unknown input.

### GAP 8 — high: Joint-output rules are incomplete, and Library stock contradicts them

The spec does not define how configured percentages mix with unconfigured outputs, what happens when all outputs are byproducts, or validation bounds for percentages ([lines 94–106](/home/johnny/wt-live-cogs/.agents/specs/live-cogs.md:94)). AC27 never tests percentage shares.

Library stock is said to take an ordinary Q4 share ([line 449](/home/johnny/wt-live-cogs/.agents/specs/live-cogs.md:449)), but a bottle output and mL Library-stock output are incompatible. Phase-1 fallback therefore assigns 100% to the final-product bottles and zero to Library stock.

**Suggested fix:** Define mixed configured/unconfigured weighting, reject invalid/all-zero configurations, and state a Phase-1 Library-stock rule based on liquid volume or an explicit zero-cost/byproduct decision. Add percent, mixed-mode, all-byproduct and bottle-plus-remainder ACs.

### GAP 9 — high: Positional Xero line keys are not stable upsert identities

Missing `LineItemID` falls back to `pos:<n>` ([lines 226–240](/home/johnny/wt-live-cogs/.agents/specs/live-cogs.md:226)). Inserting or reordering Xero lines reuses those keys for different content, so existing allocations can silently move to another purchase. `superseded_at` handles a vanished key, not a reused positional key. AC3 tests only an unchanged second sync.

**Suggested fix:** Store a content fingerprint and previous source snapshot. When a positional key’s material content changes, supersede the old line and create a new one, or require review without moving allocations. Add reorder, insertion, deletion and description/account-change ACs.

### GAP 10 — medium: Historical fetch behavior contradicts AC20

Historical sync runs only when the requested start precedes the earliest stored document ([lines 539–543](/home/johnny/wt-live-cogs/.agents/specs/live-cogs.md:539)). AC20 says an identical second run calls Xero again ([lines 783–785](/home/johnny/wt-live-cogs/.agents/specs/live-cogs.md:783)). After the first fetch, the start may equal or follow the earliest stored date, so the second request would not call Xero.

Earliest document date is not a completeness marker in any event.

**Suggested fix:** State that every explicit historical run refetches its requested range idempotently, or store durable coverage ranges separate from a user-facing run object. Align AC20 with that rule.

### GAP 11 — high: The permission matrix does not specify enforceable AND semantics

The spec requires `costs.manage + inventory.adjust` for a wide group of actions ([lines 663–669](/home/johnny/wt-live-cogs/.agents/specs/live-cogs.md:663)). In current `access_policy.py`, tuple requirements mean “any of,” not “all of” ([access_policy.py:176](/home/johnny/wt-live-cogs/app/core/security/access_policy.py:176)). Additional AND checks require the route-level `requires_permission` decorator ([permissions.py:43](/home/johnny/wt-live-cogs/app/core/security/permissions.py:43)).

The matrix also over-applies `inventory.adjust` to skip, not-stock, review and historical sync even though only record/link creates or associates stock.

**Suggested fix:** Give each endpoint its exact policy-table requirement and exact secondary decorator. Require `inventory.adjust` only where inventory is created or deliberately linked/adjusted. Add tests for a custom role with `costs.manage` but not `inventory.adjust`, and the inverse.

### GAP 12 — high: AC21’s notification privacy cannot be implemented through the current generic contract

The derived finding is visible only to `costs.manage` users ([lines 552–559](/home/johnny/wt-live-cogs/.agents/specs/live-cogs.md:552)), but `CheckResult.system_alerts` has no required-permission field. `/api/core/system-findings` returns the same org payload without per-alert permission filtering ([corechecks.py:278](/home/johnny/wt-live-cogs/app/features/compliance_checks/routes/corechecks.py:278)). Core also must not branch on a costing check ID.

The spec does not define the registration seam, stable alert ID, required `system_finding` plus `system_alerts` payload, or Home-card integration. V11 leaves this for build time ([lines 946–947](/home/johnny/wt-live-cogs/.agents/specs/live-cogs.md:946)).

**Suggested fix:** Extend the generic system-finding contract with a validated `required_permission`, filter generically at serialization, and register costing through a product-check provider seam. Specify stable ID and payload. Add contract, permission-filter and “Core contains no costing check ID” tests.

### GAP 13 — medium: Rule precedence is nondeterministic and account overrides have no persistence contract

Rules may contain any combination of account, payee and description matchers ([lines 250–264](/home/johnny/wt-live-cogs/.agents/specs/live-cogs.md:250)), but precedence defines only payee+account, payee/description alone, account alone ([lines 471–484](/home/johnny/wt-live-cogs/.agents/specs/live-cogs.md:471)). It does not cover three-field rules, description+account, payee+description, exact versus contains, or ties between multiple matching patterns.

The UI/API also promises editable account treatments, but `xero_accounts` has no treatment/override field and the spec does not say whether `PUT /accounts` creates an account-only rule.

**Suggested fix:** Restrict allowed matcher combinations or define a complete ordered score plus deterministic tie-break. State where account overrides persist and add an account-treatment AC.

### GAP 14 — medium: Review reasons conflict with tab and treatment rules

The tabs say any `review_reason` appears in To record and only `stock` lines appear anywhere ([lines 486–492](/home/johnny/wt-live-cogs/.agents/specs/live-cogs.md:486)). A recorded line recoded to non-stock is instead said to remain under Recorded with a badge ([lines 570–578](/home/johnny/wt-live-cogs/.agents/specs/live-cogs.md:570)). Those rules cannot both hold.

**Suggested fix:** Define tab precedence per review reason and whether recorded reviewed lines are exempt from the `treatment == stock` filter. Add recoded, amount-changed, deleted and superseded tab-placement ACs.

### GAP 15 — high: Readiness has no stable product identity

Products are distinct normalised final-product names, and a product without a batch uses “its process” ([lines 119–127](/home/johnny/wt-live-cogs/.agents/specs/live-cogs.md:119)). Multiple workflow outputs can share a normalised name, and more than one process can declare that name. The API also addresses a product by `<product>` rather than a stable output ID ([lines 690–692](/home/johnny/wt-live-cogs/.agents/specs/live-cogs.md:690)).

**Suggested fix:** Key readiness by stable `source_output_id`, with a documented legacy/name-only bucket for lots that lack it. Define behavior when several processes or output IDs share a display name. Extend AC39 accordingly.

### GAP 16 — medium: Execution cost payload cannot represent several outputs

`execution_costs.breakdown` is per produced flow, but the common payload exposes only one `unit_cost`, one status and one missing list ([lines 322–327](/home/johnny/wt-live-cogs/.agents/specs/live-cogs.md:322), [lines 698–701](/home/johnny/wt-live-cogs/.agents/specs/live-cogs.md:698)). Q4 and AC27 explicitly support several outputs.

**Suggested fix:** Define an `outputs[]` payload keyed by produced flow/output ID, containing quantity, unit, allocated amount, unit cost, status and missing inputs. Define separately what the batch-level headline represents.

### GAP 17 — high: The proposed MR chain cannot satisfy its assigned ACs independently

8.1a is assigned AC30, which requires linking a purchase even though purchase documents and allocations arrive in 8.1b/8.1c. 8.1b is assigned AC34–AC35, which require existing allocations and review actions delivered in 8.1c ([lines 887–895](/home/johnny/wt-live-cogs/.agents/specs/live-cogs.md:887)).

**Suggested fix:** Move end-to-end purchase invalidation/review ACs to 8.1c, or move the necessary allocation model/service earlier. Give 8.1a a manual-cost late-change AC for engine invalidation. State which migration owns each table.

### GAP 18 — high: Phase-1 UI and action promises still lack acceptance coverage

The following Phase-1 promises are not pinned by ACs:

- Percentage `cost_share` and validation.
- Bulk Not stock and Apply rule.
- Review Edit amounts.
- Editable account treatments.
- Initial “new purchases” versus “load history” start choice.
- Purchase-rules settings UI.
- Existing-lot cost panel entry/edit/free workflow.
- Batch cost card rendering and missing-input links.
- Readiness page rendering.
- Historical-run/resume UI.
- Phone-width behavior for dialogs and pages other than Purchases/record.
- Notification newest-document date.

The promises appear across [lines 164–190](/home/johnny/wt-live-cogs/.agents/specs/live-cogs.md:164), [lines 481–568](/home/johnny/wt-live-cogs/.agents/specs/live-cogs.md:481), while AC43 covers only the Purchases page and record dialog ([lines 853–855](/home/johnny/wt-live-cogs/.agents/specs/live-cogs.md:853)).

**Suggested fix:** Add focused API/component ACs for every action and a small number of E2E ACs covering the promised pages, panels, navigation, permissions and 375 px layout.

### Additional medium issues to resolve within those gaps

- Define `transfer_in` precedence over `produced`: site-transfer destination lots copy production provenance and also have `transfer_receipt_id`; the hook rule is currently ambiguous ([lines 293–304](/home/johnny/wt-live-cogs/.agents/specs/live-cogs.md:293)).
- Define the foreign-currency formula, rounding sequence and missing/zero-rate behavior; “converted at the document’s rate” is insufficient ([lines 209–221](/home/johnny/wt-live-cogs/.agents/specs/live-cogs.md:209), [lines 591–599](/home/johnny/wt-live-cogs/.agents/specs/live-cogs.md:591)).
- Define a cold-cache response when a dependency walk exceeds 500 nodes; there may be no stale target figure to return ([lines 431–435](/home/johnny/wt-live-cogs/.agents/specs/live-cogs.md:431)).
- Add list-result isolation assertions to AC42; its current “request naming another org’s ID” form does not cover list, readiness or settings responses ([lines 851–852](/home/johnny/wt-live-cogs/.agents/specs/live-cogs.md:851)).
- Add `costing_enabled` to the admin/CLI feature-grant surface and define creation of `costing_settings.start_date`. The current admin whitelist contains only `compliant` ([operations.py:52](/home/johnny/wt-live-cogs/app/admin_site/operations.py:52)).
- Resolve V10 before build or use a portable expression/partial index. Test PostgreSQL is 16, but the production database version is not established in the spec.
- Correct the recompute section’s “AC18” reference to AC33 ([line 435](/home/johnny/wt-live-cogs/.agents/specs/live-cogs.md:435)).
- For Phase 3, explicitly add immutable valued-movement facts from the first snapshot onward, or define how closed-period COGS, losses and estimate changes remain reproducible after source costs change ([lines 341–345](/home/johnny/wt-live-cogs/.agents/specs/live-cogs.md:341), [lines 623–649](/home/johnny/wt-live-cogs/.agents/specs/live-cogs.md:623)).

VERDICT: gaps-found