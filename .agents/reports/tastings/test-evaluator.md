# TEST EVALUATION — 2026-10-27

Scope: new `tests/test_tastings.py` and `tests/e2e/test_tastings_page.py`; additive `feature_measure.tastings` route registration in `.agents/perf/budgets.json`. The briefly separate `test_tastings_perf.py` was mechanically consolidated into the page module before this final grade to share one session fixture. Existing performance thresholds are unchanged.

Read-only evaluation: no application, test, script or source file was edited by this evaluator. Mutation functions were compiled and installed only in isolated Python process memory from an external cache wrapper. No checkout, stash, source restoration, shared test database migration or Claude-pane operation was used. All execution used the private `workflow-engine-test_tastings_build` database. Root held the source tree stable during the final grade.

## Static assertion review

All tests are new, rather than modifications removing existing assertions. No new skip, xfail, quarantine, permissive status sets, swallowed assertion, assertion against a mock itself, or expected-value calculation through the function under test was found. Fixed quantity/duty/date/status assertions compare independent concrete expectations against persisted application results.

| Backend test | Claim checked; static result |
|---|---|
| plan_calendar_and_cancel_do_not_remove_stock | Exact linked task date/assignee; no pool; generic task update/delete/lane rejected; cancellation status and unchanged quantity. Valid. |
| dispatch_outcomes_and_reuse_conserve_partial_bottles | 10→9 warehouse, 700→550 mL; immutable final outcome; 300 mL reuse reservation; exactly one removal; cancellation releases reservation without stock restoration. Valid. |
| dispatch_replay_and_changed_request | Exact single debit; changed replay rejected; post-dispatch edit rejected. Valid. |
| excise_frozen_date_rate_and_no_xero_or_transfer_duplicate | Exact 28.00 liability and September identity; full equality after changing live stock/profile/rate; no October line; unresolved modern projection remains incomplete. Valid assertions; see naming limit below. |
| missing_basis_persists_visible_problem_never_false_nil | Missing ABV produces problems/incomplete return and lodgement rejection; later profile edit does not silently repair frozen capture. Valid. |
| late_backdated_removal_keeps_lodged_snapshot_and_identity | September lodged nil remains unchanged; one October adjustment retains September identity. Valid. |
| validation_and_reference_isolation (7 cases) | Invalid rep/contact IDs, missing/wrong NZ offset, reversed time, oversized title and unknown venue type each raise. Invalid UUIDs prove reference rejection; hostile existing objects are separately exercised. Valid. |
| all_lines_rollback_on_insufficient_stock | A second insufficient line fails; transaction rollback leaves both original exact quantities and no lots. Valid transaction-boundary claim. |
| concurrent_warehouse_dispatch_prevents_oversell | Two separate sessions compete for 7 of 10; exactly one succeeds, final balance 3. Valid. |
| api_subscription_roles_csrf_and_hostile_ids | Unsubscribed page/API404, subscribed reads/create succeed, Sales dispatch403, Auditor write403, hostile detail404/empty stock choices/rejected source references; missing CSRF400. Valid. |
| pool_concurrent_reservations_do_not_double_allocate | Two separate 500 mL reservations compete for 700; one succeeds, reserved500/remaining700. Valid. |
| own_venue_records_removal_and_pack_volume_blocks_unknown_conversion | Missing pack size blocks own-venue dispatch; restored conversion yields exactly one removal. Valid. |
| modern_cca_register_and_source_period_review_use_same_removal | Dated CCA mapping, 28.00 observed duty, tasting-specific identity, review equality and explicitly incomplete/non-nil modern register. Valid. |
| dispatch_signed_movement_and_livesync_events_are_atomic_and_replay_safe | One signed -2 movement, -2 aggregate change, one tasting event and inventory event with actor/delta after replay. Valid successful-commit/replay claim; does not itself inject an EventWriter failure. |
| frozen_removal_facts_are_database_immutable | Raw SQL snapshot update rejected by real PostgreSQL trigger. Valid. |
| stock_sources_remain_same_org_and_library_is_never_tasting_pool | Existing hostile stock, name-marked Library stock and raw material each rejected. Valid. |
| backdated_unresolved_capture_blocks_next_period_nil_and_rates_roll_over | Backdated unknown capture becomes unresolved adjustment and blocks current lodgement. Valid assertions; rollover amounts are proved by the following separate test. |
| rate_rollover_uses_each_physical_dispatch_date_and_metadata_library_is_excluded | Exact September28/October56 duties, recorded actor and metadata-marked Library rejection. Valid. |
| booking_without_stock_does_not_allow_dispatch | Zero-line planning succeeds, dispatch rejects, planned status/stock/no-pool remain exact. Valid. |
| outcome_keeps_plan_instructions_and_separate_outcome_notes (2 cases) | Omitted or explicit outcome notes remain distinct from plan notes; replay conserves600 mL. Valid. |
| coalesced_prior_removals_reject_ambiguity_without_server_error_or_debit (2 cases) | Real coalesced repeated out-movements rejected with status400; unchanged balance/no pool. Valid. |

| Browser test | Claim checked; static result |
|---|---|
| rep_can_schedule_dispatch_sample_part_of_bottle_and_reuse_remainder (desktop/phone) | Real UI create/search/dispatch/finalise; 150 mL result and550 mL pool; actual returned lot identity; reuse editor selects pool unit. Valid. Reuse is opened in browser; actual second dispatch is proved by backend test. |
| tasting_is_linked_from_shared_sales_calendar_and_survives_boosted_round_trip | Actual shared calendar event opens correct tasting; boosted revisit and Back initialize controls; restored filter clears to original event. Valid. |
| search_empty_and_clear_preserve_the_event | Specific no-match message and restored original event. Valid. |
| concept_layouts_fit_phone_laptop_and_wall (3 styles×3 widths) | Correct structural style attribute; both main regions visible; document and workspace overflow assertions. Valid layout checks. These do not certify visual quality or dark theme appearance. |
| invalid_end_time_keeps_the_form_open_and_explains_the_problem | Visible validation, editor retained and unchanged visible event count. Valid UI claim; persisted count independently covered by backend validation. |
| tastings_api_budget (4 routes) | Real subscribed populated fixture; every response200, exactly5 measured samples after warmup; server duration/query ceilings evaluated. No skip-on-error fallback. Valid. |
| tastings_page_budget | Three successful navigations, content visible, exactly3 measurements, positive LCP and enforced backend/query/LCP ceilings. Valid. LCP is a local warm-browser tripwire, not production speed evidence. |

## Falsifiability probes

Each final probe ran a targeted real-Postgres test in a fresh process. The final mutated process failed for the intended reason; application files were never mutated.

| Broken behavior | Target test | Observed failure |
|---|---|---|
| Bypass dispatch `inventory.adjust` permission | api_subscription_roles_csrf_and_hostile_ids | Sales dispatch200 rather than403. |
| Remove repository org predicate **and** bypass global ORM tenant filtering for that lookup | api_subscription_roles_csrf_and_hostile_ids | Hostile detail200 rather than404. Removing only the explicit predicate stayed green because the independent global tenant filter correctly retained isolation; this was an equivalent mutation, not an escaped leak. |
| Skip warehouse decrement | dispatch_outcomes_and_reuse_conserve_partial_bottles | Actual warehouse10 rather than9. |
| Remove inventory quantity-write authorization context | dispatch_outcomes_and_reuse_conserve_partial_bottles | Existing quantity-write guard rejects flush. This proves the tested dispatch uses the protected write path; it does not separately regrade the unchanged global guard implementation. |
| Accept changed date under the same dispatch key | dispatch_replay_and_changed_request | Expected TastingError not raised. |
| Recompute stored tasting duty from current live excise rate when reading a removal | excise_frozen_date_rate_and_no_xero_or_transfer_duplicate | First draft remains28.00; changing rate reprices later draft to559.44 and breaks full frozen-line equality. |

Also called the existing budget evaluator with values one above the Tastings API query ceiling and page LCP ceiling: both rejected with pytest failure. Threshold values were not changed. Initial excise probe prototypes had a type/format error; those are not counted as falsifiability evidence. The corrected, quantized live-rate mutation above is the evidence.

Clean-process backend rerun after the probes: **29 passed**, one pre-existing Flask-Limiter warning,5.18s. Root's final4 browser/performance execution on the same final source: **19 passed**, three warnings,32.79s; log inspected independently. That browser execution was run by root, not duplicated by this evaluator. Final source status was inspected; only root's expected uncommitted feature files and generated perf report were present.

Evidence logs: `/home/johnny/.cache/tastings/evaluator/` (`auth.log`, `tenant-bypass.log`, `debit.log`, `guard.log`, `idempotency.log`, `excise-final.log`, `backend-clean.log`, `perf-ceiling.log`); browser `/home/johnny/.cache/tastings/browser-final4.log`.

## Bounded claims and advisory naming findings

- `test_excise_frozen_date_rate_and_no_xero_or_transfer_duplicate` creates no overlapping Xero invoice or transfer fixture; its exact single-removal assertion proves the fresh dispatch path, not every possible sale/transfer overlap. Rename to describe frozen date/rate/period identity, or add that overlap before claiming it. Prior-removal ambiguity has its own explicit real-transfer test.
- `test_backdated_unresolved_capture_blocks_next_period_nil_and_rates_roll_over` proves unresolved late adjustment/lodgement blocking; rollover amounts are checked by a different test. Rename to the narrower claim.
- No new browser hostile-tenant switching test, unauthenticated-login test, dark-mode assertion or failure-injected EventWriter rollback test is claimed. Backend hostile HTTP access, shared authentication tests, screenshot inspection and other feature review stages supply separate evidence; this grade does not invent coverage.
- Budget fixtures are representative small populated tenants, not maximum200-event/50-stock scaling data. They enforce regressions against existing ceilings without establishing worst-case scalability.

The naming recommendations do not weaken the real independent assertions or invalidate the passing claims. No test that was made substantively incorrect by a final probe stayed green.

VERDICT: valid
