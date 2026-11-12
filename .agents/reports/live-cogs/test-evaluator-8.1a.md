# Test-evaluator report — live-cogs 8.1a

Scope reviewed: spec v4’s requested sections, all five costing test files, and the relevant Core reconciliation, execution, inventory, access-policy, and site-transfer code. The missing `app/features/costing/` implementation was treated as expected.

## A. Correctness of expected values

### Independently recomputed expectations

| Test | Independent result |
|---|---|
| `tests/test_costing_engine.py:51` | $45/kg ÷ 1000 = **$0.045000/g**. |
| `tests/test_costing_engine.py:112` | Priced residual case: $90 ÷ 2 kg = **$45/kg estimated**. Fully priced: ($90 + $120) ÷ 5 kg = **$42/kg actual**. |
| `tests/test_costing_engine.py:132` | $20 for 2 kg implies **$10/kg**, with 3 kg unpriced and status `estimated`. |
| `tests/test_costing_engine.py:172` | Whole-lot price initially $80 ÷ 2 = **$40/kg**; flow price supersedes it for those units: $90 ÷ 2 = **$45/kg**. Second lot: ($90 + 3 × $20) ÷ 5 = **$30/kg**. |
| `tests/test_costing_engine.py:230` | 15 Oct uses 1 Oct’s $40; 5 Nov uses 1 Nov’s $50; 1 Sep uses earliest-after $40; adding 10 Oct at $44 makes the 15 Oct estimate **$44**. |
| `tests/test_costing_engine.py:291` | Input pool = 1 × $45 + 10 × $5 = **$95**; 20 outputs = **$4.75/unit**. Before output, `cost_so_far = $95`; afterward zero. |
| `tests/test_costing_engine.py:313` | 500 g = 0.5 kg; 0.5 × $45 = **$22.50**; over 9 bottles = **$2.50/bottle**. |
| `tests/test_costing_engine.py:324` | Split cases are correct: 80/20 gives $76/$19; byproduct gives $95/$0; 30/70 gives $28.50/$66.50; 60/60 normalizes to $47.50 each; invalid/all-byproduct cases fall back to $76/$19. |
| `tests/test_costing_engine.py:413` | $100 ÷ 3 rounds half-up to **$33.3334 + $33.3333 + $33.3333**. |
| `tests/test_costing_engine.py:424` | Known floor = $45; 9 outputs = **$5 known/unit**. After pricing mystery input at $18, total = $63; $63 ÷ 9 = **$7/unit**. |
| `tests/test_costing_engine.py:451` | Complete case: ($45 + $50 + $30) ÷ 20 = **$6.25**. Partial case: ($50 + $30) ÷ 20 = **$4 known/unit**. External `known_input_cost = $125` in the complete case is also correct. |
| `tests/test_costing_engine.py:508` | $30 allocated to 6 L = **$5/L**. |
| `tests/test_costing_engine.py:530` | $390 over 78 bottles = **$5/bottle**; Library stock receives zero. |
| `tests/test_costing_engine.py:579` | Backfilled $45 input over 9 outputs = **$5/unit**. |
| `tests/test_costing_engine.py:639` | $10 ÷ 3 g = **$3.333333/g** at six decimals. |
| `tests/test_costing_flows.py:87` | 300 g + 200 g = **0.5000 kg**. |
| `tests/test_costing_flows.py:206` | Create 2, add 3, consume 2 correctly reconstructs `created 2`, `added 3`, `consumed 2`. |
| `tests/test_costing_flows.py:238` | Starting 10 and consuming 4 leaves 6; fallback reconstruction would be 6 + 4 = **10**—although this test does not actually reach that fallback, as discussed below. |
| `tests/test_costing_routes.py:152` | Whole-lot $90 ÷ 2 kg = **$45/kg**. |
| `tests/test_costing_routes.py:173` | Consuming 1 kg at $45 gives $45; 9 outputs = **$5/unit**. |
| `tests/test_costing_transfer.py:14` | $200 ÷ 20 bottles = **$10/bottle**; the 4-bottle fragment retains that unit cost. |

All other qualitative expectations—unknown/partial statuses, permission codes, feature-gate codes, active-entry behavior, source labels, and basic flow shapes—are consistent with the scoped spec except where called out below.

### Findings

- **High — `tests/test_costing_engine.py:159`; spec `.agents/specs/live-cogs.md:1001` and `:273`.**  
  `test_ac54_second_flow_price_replaces_first` does not test AC54’s stated scenario. AC54 says $20/2 kg followed by $30/3 kg on the same flow produces a fully priced 5 kg at $10/kg. The test instead replaces the first entry with $50/5 kg. The test’s result is arithmetically sound, but it silently resolves a real spec contradiction: the data model permits only one active `lot_cost_entries` row per lot/flow, so AC54’s two simultaneous manual entries cannot exist.  
  **Concrete fix:** Prefer the data-model-consistent rule: rewrite AC54 to say the second PUT replaces the first with $50/5 kg, and assert the first row is inactive with `deactivated_at` set. Alternatively, if cumulative entries are intended, remove/change the uniqueness rule and restore a literal $20/2 + $30/3 test.

- **Medium — `tests/test_costing_flows.py:138`; spec `.agents/specs/live-cogs.md:334`.**  
  The unique-name test sends `" Gin "` and expects resolution to `"Gin"`. The spec says the declared name is stripped before comparison, but does not say the client-supplied actual name is stripped. Current Core also retains the actual output name without stripping. Two reasonable implementations can differ.  
  **Concrete fix:** Either send `"Gin"` in the test, or explicitly change the spec to compare `declared_name.strip()` with `actual_name.strip()`.

## B. Falsifiability

- **High — `tests/test_costing_engine.py:341`.**  
  AC27c is intended to prove that a `final_product` beats another inventory type when incompatible units prevent quantity sharing. In the real completion route, every output of a terminal step is assigned `final_product`; the test’s “Botanical mash” is therefore also a final product. Gin wins merely because 19 is larger than 3. An implementation that ignores inventory type and always picks the largest quantity passes.  
  **Concrete fix:** Create outputs with genuinely different inventory types—most realistically a final-product output plus reconciliation into an existing raw/WIP untracked lot—and make the non-final output’s quantity larger so only type precedence can select Gin.

- **High — `tests/test_costing_flows.py:238`; `tests/factories.py:77`.**  
  `test_ac37_backfill_without_created_event_uses_current_plus_consumed` claims `InventoryItemFactory` makes a lot with no event, but that factory calls `InventoryRepository.create_inventory_item`, which emits `inventory_item.created`. The expected 10 is therefore obtained from the created event, not from current quantity plus consumption. A broken fallback passes.  
  **Concrete fix:** Delete that lot’s `inventory_item.created` event before backfill, or construct a deliberate legacy row through an authorized fixture path that emits no event. Assert the event is absent before invoking backfill.

- **High — `tests/test_costing_engine.py:601`.**  
  The forged cross-org flow test treats any exception while inserting the row as a pass. Because the required composite FK should reject the forgery, the engine’s org filtering is normally never exercised. It also catches every `Exception`, so unrelated schema or session failures are accepted.  
  **Concrete fix:** Split this into two tests: one expects the precise `IntegrityError` proving the composite FK, and a separate engine-isolation test that bypasses the FK in a controlled migration/test mode or uses a mocked repository result to prove every traversal query filters `org_id`.

- **High — `tests/test_costing_flows.py:256`.**  
  `test_ac37_backfill_is_org_scoped` creates data only in the other org, backfills an empty target org, then checks the other org remains empty. A complete no-op backfill passes.  
  **Concrete fix:** Create and wipe flow-bearing lots in both orgs; backfill one org; assert its expected rows were inserted while the other remains untouched.

- **High — `tests/test_costing_flows.py:147`.**  
  The duplicate-name identity test asserts only `source_output_id is None`. AC52 also requires that no matching `cost_share` be applied. An implementation can store null correctly but still look up split configuration by name and pass.  
  **Concrete fix:** Give the two duplicate definitions sharply different `cost_share` settings, supply a priced pool and multiple outputs, and assert the null-identity output receives the fallback quantity/primary allocation.

- **Medium — `tests/test_costing_routes.py:81`.**  
  The test says "`costs.manage` alone is enough" but grants both `costs.view` and `costs.manage`. A route incorrectly requiring both permissions passes.  
  **Concrete fix:** Grant only `["costs.manage"]`, PUT a price successfully, and use a separate authorized reader to verify the persisted result.

- **Medium — `tests/test_costing_engine.py:413`.**  
  Sorting the three rounded allocations proves only the multiset. It does not prove the rounding remainder goes to the largest weight, or—on a tie—the earliest flow as required by the roll-up rule.  
  **Concrete fix:** Assert allocation by output/flow identity: output A, the earliest tied flow, must receive `$33.3334`.

- **Medium — `tests/test_costing_flows.py:63`.**  
  `added.source_key.startswith("add:")` accepts random or unstable suffixes and does not prove the suffix is the exact `inventory_item.quantity_adjusted` event ID.  
  **Concrete fix:** Query the emitted event and assert `source_key == f"add:{event.id}"`.

- **Medium — `tests/test_costing_flows.py:230`.**  
  The second backfill asserts only `inserted == 0`; it does not assert that row count and source-key set remain unchanged. A function that inserts duplicates but reports zero could pass unless the database constraint happens to catch it.  
  **Concrete fix:** Snapshot `(id, source_key)` and count before rerun, then assert exact equality afterward. Also directly test the unique `(org_id, source_key)` constraint.

- **Low — `tests/test_costing_flows.py:110`.**  
  The feature-off hook test compares only a set of kinds. Duplicates, zero/wrong quantities, wrong directions, or invalid source keys still pass.  
  **Concrete fix:** Assert the exact row multiset, quantities, directions, source keys, and count.

- **Low — `tests/test_costing_routes.py:152` and `:173`.**  
  Payload “shape” tests mostly assert key presence. Wrong types, nulls, missing nested fields, or malformed entry/output objects can pass. `cost_so_far_status` and execution `warnings`, both required by the spec, are not checked at all.  
  **Concrete fix:** Assert the full payload contract, including exact string precision and every nested field.

## C. Setup realism

- **High — `tests/test_costing_flows.py:238`.**  
  The supposed legacy no-event lot is not realistic for the intended path because its factory deliberately uses the repository and emits the event. This is the clearest setup failure unrelated to costing behavior.  
  **Concrete fix:** Explicitly create a legacy condition and assert it before testing backfill.

- **Medium — `tests/test_costing_engine.py:341`; `app/core/backend/execution_routes.py:898`.**  
  The incompatible-output setup does not create the advertised final-product-versus-other-type situation. Terminal-step completion assigns the same inventory type to both ordinary outputs.  
  **Concrete fix:** Use reconciliation into an existing non-final lot, or establish a supported per-output inventory-type mechanism before relying on this scenario.

- **Medium — `tests/test_costing_engine.py:512`; `app/core/backend/inventory_routes.py:842`.**  
  The untracked lot is created directly with only `{"untracked": True}`. The real Add Inventory API also stores `remaining_balance_to_reconcile`. The reconciliation service deliberately supports the missing-field legacy case, so this setup will work, but it tests the legacy fallback rather than the normal production shape.  
  **Concrete fix:** Create the untracked item through `/api/core/inventory` with `untracked: true` and required notes, or include `remaining_balance_to_reconcile: "10"` explicitly. Add a separate legacy test if that fallback is important.

- **Low — `tests/test_costing_transfer.py:18`; `tests/factories.py:77`.**  
  The comment says the factory lot has “no flows”, but `InventoryItemFactory` uses `InventoryRepository`, so after the hooks are implemented it will have a `created` flow. The expected $10 still follows the spec because a whole-lot price applies to that flow, so this does not invalidate the test, but the comment and intended setup are stale.  
  **Concrete fix:** Correct the comment and assert the source flow explicitly.

The following setups otherwise match current app behavior:

- Completion payload keys and route are realistic.
- Duplicate inputs are aggregated by current `complete_step`.
- Library-stock payloads use the real `library_remainder_ml` path.
- Reconciliation accepts the supplied `untracked_item_id` and compatible name/unit.
- Custom roles created in `user_client` are loadable by the access policy.
- Site-transfer receipt creation copies provenance and uses `transfer_receipt_id`.
- Add Inventory returns an `id` with status 201 for the supplied payload.

## D. Coverage gaps

- **High — AC32, `tests/test_costing_transfer.py:14`.**  
  Same-unit transfer is covered; required unit conversion is not.  
  **Concrete fix:** Add a supported scenario where source and destination cost units differ, or resolve the spec/platform mismatch described in section E before writing the test.

- **High — AC37, `tests/test_costing_flows.py:206`.**  
  The required transfer-destination backfill example is absent. The real no-created-event fallback is also untested because of the faulty fixture.  
  **Concrete fix:** Add a transfer destination with production provenance, wipe flows, backfill, and assert `transfer_in` wins over `produced`, with the exact `create:<item_id>` key and `reconstructed = true`.

- **High — AC42, `tests/test_costing_engine.py:601`.**  
  Tenant isolation inside the recursive cost walk is not actually exercised when the FK rejects the forgery. Same-material estimate candidate selection across orgs is also untested.  
  **Concrete fix:** Add an org A unpriced lot and a same-name, directly priced org B lot; assert org A remains unknown. Separately exercise foreign produced/transfer dependencies under a controlled FK bypass.

- **High — AC52, `tests/test_costing_flows.py:125-193`.**  
  Missing assertions include:

  - Duplicate-name null identity disables `cost_share`.
  - Renamed definitions continue to apply `cost_share` by ID, not merely store the ID.
  - Name-resolved and Library-stock flows themselves carry the correct ID/null.
  - `reconciled_in` carries the resolved output ID.

  **Concrete fix:** Extend identity tests through a priced execution and assert allocations plus both lot and flow fields.

- **High — AC53/A9, `tests/test_costing_engine.py:530`.**  
  The required “only output is Library stock, so it receives the whole pool” case is absent.  
  **Concrete fix:** First define how that state can be produced through Core; then test it. If only historical/forged data can represent it, build a focused engine fixture.

- **High — AC57, `tests/test_costing_engine.py:215`; `tests/test_costing_routes.py:231`.**  
  Only production lots are tested. `transfer_in` and `reconciled_in` lots must also reject PUT and report `editable: false`.  
  **Concrete fix:** Add API-level tests for all three forbidden inflow kinds.

- **High — 20,000-node recompute guard, spec `.agents/specs/live-cogs.md:500`.**  
  No test proves traversal termination or `status: unknown`, warning `too_large`.  
  **Concrete fix:** Make the limit injectable for tests and build a small chain exceeding the test limit.

- **Medium — AC31, `tests/test_costing_engine.py:508`.**  
  Same-unit reconciliation is covered, but conversion into the untracked lot’s unit, exact reconcile source key, and resolved `source_output_id` are not.  
  **Concrete fix:** Reconcile mL into an L lot or vice versa and assert converted flow quantity, key, identity, allocation, and payload.

- **Medium — AC36, `tests/test_costing_flows.py:51-107`.**  
  Transaction rollback is tested only for creation. There is no forced rollback after add, consumption, production, or reconciliation hook insertion. Produced and reconciliation source keys are not checked exactly.  
  **Concrete fix:** Inject a failure after each hook has flushed but before commit, then assert neither stock mutation nor flow survives.

- **Medium — split rules, `tests/test_costing_engine.py:324`.**  
  Untested branches include:

  - Percent outputs with no free outputs and total below 100, which must still normalize to 100.
  - Percent plus several compatible free outputs sharing the residual by quantity.
  - Percent/byproduct with no free output.
  - Primary ordering by `final_product > WIP > raw`, independently of quantity.
  - Primary tie-breaking by earliest flow and flow ID.
  - Rounding remainder assignment to the largest weight.

  **Concrete fix:** Add one discriminating case per branch, with quantities chosen so a simpler wrong rule gives a different answer.

- **Medium — residual pricing and entry replacement, `tests/test_costing_engine.py:132-169`.**  
  A single residual is covered, but cumulative price facts from different fact sources, exact replacement/deactivation semantics, and residual coverage by a whole-lot price after partial flow pricing need explicit tests. AC55 covers the last case numerically but does not inspect which quantities each fact priced.  
  **Concrete fix:** Assert active/inactive entries and `priced_quantity`/`unpriced_quantity` after each transition.

- **Medium — AC56/data model, `tests/test_costing_engine.py:191`.**  
  Whole-lot uniqueness is tested, but equivalent database enforcement for non-null `cost_flow_id`, nonnegative amount, positive quantity, `free ⇒ amount = 0`, valid kind, and composite tenant FKs is absent.  
  **Concrete fix:** Add focused constraint tests for each invariant.

- **Medium — AC63, `tests/test_costing_engine.py:263`; `tests/test_costing_routes.py:243`.**  
  Deletion falling back to `unknown` is covered, but falling back to a valid last-known estimate is not.  
  **Concrete fix:** Create an earlier directly priced same-material lot, delete the target’s entry, and assert `estimated`, source `estimate`, and correct `estimate_from`.

- **Medium — AC23, `tests/test_costing_engine.py:95`.**  
  Customer-owned pricing rejection is tested through the service, not through the required PUT API.  
  **Concrete fix:** PUT through the route and assert 400 plus unchanged zero customer-owned cost.

- **Medium — backfill keys/idempotency, `tests/test_costing_flows.py:206`.**  
  Missing coverage includes exact add-event key, transfer precedence, collision between live and reconstructed keys, skipped deleted input lots, unconvertible units and command counters, and the rule that historical reconciliations are not reconstructed.  
  **Concrete fix:** Add targeted backfill tests for each stated source/key rule rather than relying mainly on equality with live output.

- **Medium — cost-flow schema, `tests/test_costing_flows.py:280`.**  
  Invalid kind and zero quantity are tested, but not direction/kind compatibility, required execution fields for produced/reconciled/consumed flows, composite tenant references, or unique source keys.  
  **Concrete fix:** Add direct constraint tests.

- **Medium — API payload contract, `tests/test_costing_routes.py:152-189`.**  
  Lot `entries` are not validated field-by-field. Execution payload omits checks for `cost_so_far_status`, `warnings`, `flow_id`, `weight`, `known_unit_cost`, per-output `missing`, quantities, units, names, and step numbers.  
  **Concrete fix:** Assert complete representative payloads, including exact decimal-string scales.

- **Medium — estimate selection, `tests/test_costing_engine.py:51-84` and `:230-260`.**  
  Missing cases include `created_at` fallback when `purchase_date` is absent, same-date tie-breaking, trailing `" - library stock"` normalization, incompatible units, and customer-owned candidates.  
  **Concrete fix:** Add discriminating candidate sets for each selection rule.

- **Medium — A10/no caches, multiple engine tests.**  
  Late prices and settings are observed on the next read, which proves freshness but not the structural “no cache tables/no writes during read” requirement.  
  **Concrete fix:** Add a schema assertion that no cost cache tables exist and a read-only test proving cost reads do not insert/update database rows.

- **Low — AC41, `tests/test_costing_flows.py:110`.**  
  Feature-off coverage includes create, consume, and produce but not add or reconcile.  
  **Concrete fix:** Exercise every live hook with the feature disabled.

- **Low — material and money precision, `tests/test_costing_engine.py:639`.**  
  Unit precision is covered; general API money formatting to four decimals is only incidentally checked in some payloads.  
  **Concrete fix:** Assert all monetary fields use four decimals, including zero and rounding cases.

## E. In-scope spec gaps

- **High — `.agents/specs/live-cogs.md:273-276` versus `:1001-1004`.**  
  AC54’s cumulative two-price example conflicts with the one-active-entry-per-flow constraint. This is the largest remaining numerical ambiguity.  
  **Concrete fix:** Decide between replacement and accumulation. Replacement aligns with the existing model and current test; accumulation requires a schema change.

- **High — `.agents/specs/live-cogs.md:997-1000`; current Core output creation.**  
  “A step whose only output is Library stock” is not presently expressible through the completion route: Library stock is generated only as an auxiliary line for a positive counted output. Implementers can reasonably either support only engine-level historical data or add a new completion behavior.  
  **Concrete fix:** Specify the production payload/path that creates a Library-stock-only output, or narrow AC53 to engine behavior over pre-existing flow data.

- **High — `.agents/specs/live-cogs.md:930-932`; `app/features/site_transfers/service.py:417-445`.**  
  AC32 requires conversion when transfer source and destination units differ, but the current transfer service copies the source unit to the destination lot. There is no normal differing-unit path.  
  **Concrete fix:** Either remove the conversion clause from 8.1a, define a destination-unit conversion feature for transfers, or state that conversion applies only to legacy/forged data and test the engine directly.

- **Medium — `.agents/specs/live-cogs.md:334-340`.**  
  Output-name comparison does not clearly say whether both actual and declared names are stripped, only the declared name, or whether case matters.  
  **Concrete fix:** State an exact normalization expression, for example `declared.name.strip() == actual.name.strip()` with case-sensitive comparison.

- **Medium — `.agents/specs/live-cogs.md:269-297` and API section `:764-801`.**  
  The PUT payload and update semantics are not specified. Tests assume:

  - `{"kind":"free"}` may omit amount and quantity.
  - A second manual price on the same flow replaces the first.
  - A second delete returns 404.
  - PUT returns the recalculated lot payload.

  Competent implementations could instead require explicit zero/quantity, return 409 on an occupied flow, make DELETE idempotent, or return only the entry.  
  **Concrete fix:** Document request schemas, replacement rules, status codes, and response payloads for PUT/DELETE.

- **Medium — `.agents/specs/live-cogs.md:784-790`.**  
  `source: mixed` is listed but never defined. Source precedence is also unclear for lots combining flow prices, whole-lot residual pricing, free/manual entries, or created plus reconciled inflows.  
  **Concrete fix:** Define a deterministic source-reduction table.

- **Medium — `.agents/specs/live-cogs.md:784-790`.**  
  `priced_quantity` and `unpriced_quantity` are defined implicitly for created/added inflows but not for production, transfer, reconciliation, customer-owned, no-flow legacy, or mixed-inflow lots.  
  **Concrete fix:** Define those fields per inflow kind and for zero-cost Library stock.

- **Medium — `.agents/specs/live-cogs.md:464-483`.**  
  The primary-output type precedence is clear, but ordinary outputs from the same current Core step all receive the same inventory type. The spec does not identify which supported path makes the precedence observable, apart from possible reconciliation into an existing differently typed lot.  
  **Concrete fix:** State that primary classification uses the destination lots’ actual inventory types and give a reconciliation-based worked example.

- **Medium — `.agents/specs/live-cogs.md:299-316` and `:346-361`.**  
  Backfill `write_reason` values are unspecified. The historical `created_at` for reconstructed rows is also unspecified—event time, step completion time, lot creation time, or backfill time—which can affect “earliest flow” tie-breaking.  
  **Concrete fix:** Define reconstructed `write_reason` and timestamps for every source type.

- **Low — `.agents/specs/live-cogs.md:286` versus AC23.**  
  The prose describes a whole-lot price as having a “positive amount”, while a free whole-lot entry necessarily has amount zero. The intended special case is evident, but literal implementations can disagree.  
  **Concrete fix:** Say “nonnegative amount; zero only for `kind=free`.”

- **Low — `.agents/specs/live-cogs.md:455` and `:482-483`.**  
  “Earliest flow” is not defined when timestamps tie, even though reconstructed rows can easily share timestamps.  
  **Concrete fix:** Define ordering as `(created_at, id)` or another stable key and test it.

VERDICT: weakened
