# Typed Tasks test evaluation — 2026-10-27

Scope: exactly the `HEAD` diff of `tests/e2e/test_tastings_page.py` and new `tests/test_tasting_task_types.py`, assessed against `.agents/specs/tastings-tasks.md`. Previous stock/excise tests were unchanged and are not regraded. This evaluator changed no application, test or script files; only this report was created. Mutation probes used process-local function replacement from an external cache wrapper, never source-file edits. All backend executions used private `workflow-engine-test_tastings_build`; no migrations/schema operations or concurrent browser run were started.

## Assertion-diff review

Existing create/dispatch/partial-outcome/reuse assertions remain intact: exact150 mL used,550 mL reusable stock, actual returned lot identity, canonical0.5L line and source identity. Entry-point labels, selectors and URL expectations change from the retired standalone page to typed shared Tasks. This is faithful to the founder's explicit direction, not assertion weakening.

The shared-calendar test is replaced by inline shared-Tasks opening, Customers→Tasks boosted revisits and **two** history-Back transitions ending at the filtered Week workspace. Exact event title and post-restoration search/clear behavior remain asserted. Waiting for real navigation and initialized controls is stronger than inspecting stale DOM, but the current navigation trigger has a harness error described below.

The nine layout cases retain exact style selection and both document/workspace overflow assertions. Removed standalone heading/pool-region checks become shared task-type filter and secondary Tasting stock action checks, matching the new hierarchy. Error-state count assertions now inspect shared `.tasks-card` records. The page performance test now awaits shared Tasks' loaded state while retaining successful responses, exact sample counts, positive LCP and unchanged budgets/ceilings. No skip/xfail, broadened response set, swallowed assertion, or tautological expected result was introduced.

## New test review

| Test | Independent claim and assessment |
|---|---|
| ac1_simple_types_persist_and_update | General/Call/Email exact serialized and persisted types; omission defaults General; ordinary update to Call. Valid. |
| ac1_generic_service_rejects_forged_types (4 parameters) | Specialized/unknown/object/null type rejects and creates no task. Valid; deterministic collection parameters. |
| ac4_unified_creation_is_one_typed_task_and_event | HTTP201, matching bidirectional IDs, canonical deep link, exactly one task/event; generic rewrite400/delete409; original status persists; compatibility redirect. Valid. |
| ac4_invalid_specialized_creation_leaves_no_partial_task | Reversed/equal time400 with no task/event persisted. Valid validation-boundary claim. |
| ac1_lapse_hides_specialized_tasks_from_crm_core_and_direct_read | Establishes pre-lapse visibility, then exact ordinary CRM set, specialized Core exclusion, generic/specialized reads404, forged creation404, absent UI and retained accounting event. Valid. |
| ac1_database_rejects_unknown_type | Real PostgreSQL rejects unsupported type via raw SQL. Valid. |
| task_type_switch_preserves_common_and_specialized_unsaved_fields | Exact common-field mapping and selected day, then specialized venue/time retention after switching and common-field editing. Valid. It does not claim to exhaust every priority/status/long-text/customer transition. |
| type_filter_survives_all_views_without_fetching_tasting_lists_or_choices | Actual Board/List/Week transitions retain type and URL; captures network requests and forbids separate Tastings API traffic. Valid. |
| simple_call_task_still_creates_edits_and_completes | Actual create Call, edit Email and complete removes open row. Valid. |
| direct_task_link_opens_tasting_when_not_in_initial_list | Only initial list is deliberately replaced with empty result; real scoped detail opens the seeded event. Valid client fallback test, not proof of archived backend query semantics. |
| specialized_task_dialog_inherits_dark_workspace_tokens | Dark appearance is explicitly selected; dialog cannot remain white or share title color. Valid coarse presentation assertions; not a computed contrast-ratio or exact-token proof. |
| stock_pagination_failure_is_visible_and_retries_same_page | Controlled first page and503 second page: exact visible server error, retry succeeds without losing first batch, alert clears and exact request offsets `[0,50,50]`. Valid client behavior regression; mocked server responses are inputs, not asserted against themselves. Expected503 explains omission of a blanket clean-console assertion. |
| type_switch_keeps_people_missing_from_ordinary_options | Ordinary people responses deliberately omit selected records. Specialized choices provide them; intended assertions retain exact IDs and display names in ordinary draft, round-trip customer identity, and actual outgoing contact/assignee payload. Valid intended scope, but inaccessible locator currently prevents execution (F2). POST is mocked intentionally, so no backend acceptance/persistence is claimed. |

## Falsifiability probes

Four process-local mutations each made a targeted **new** backend test fail for the intended assertion:

1. Store every simple type as General → `ac1_simple_types_persist_and_update`: General≠Call.
2. Permit `tasting` through ordinary generic creation → `ac1_generic_service_rejects_forged_types[tasting]`: expected ValueError was not raised.
3. Remove generic subscription visibility predicate → `ac1_lapse_hides_specialized_tasks_from_crm_core_and_direct_read`: post-lapse exact CRM set includes forbidden tasting task.
4. Remove generic repository protection on linked tasting update → `ac4_unified_creation_is_one_typed_task_and_event`: forged lifecycle/type update returns200 instead of400.

Clean fresh-process rerun after probes: **9 passed**, three existing Flask-Limiter warnings,3.14s. Logs and external wrapper: `/home/johnny/.cache/tastings/evaluator-typed/`. Previous auth/hostile-tenant/inventory/idempotency/frozen-money probes remain evidence for unchanged ledger paths; they were not rerun or claimed as newly run here. The new backend file does not itself add a hostile-tenant probe for the newly introduced generic direct-read endpoint; independent tenant/security review must cover that boundary.

## Open findings

**F1 — history test has a navigation-trigger race, not a completed Back assertion.** Root's `/home/johnny/.cache/tastings/typed-browser6.log` ends with25 passed/2 failed. `test_tasting_is_inline_in_shared_tasks_and_survives_boosted_round_trip` fails in `page.evaluate("setTimeout(() => window.history.back(), 0)")`: the document navigates before Playwright receives its evaluation result, producing “Execution context was destroyed”. No completed two-Back restoration evidence is obtained. Use a navigation-safe Back driver/wait strategy, preserve both exact destination URLs and all restored-control/event assertions, then run the real test. Do not broadly swallow evaluation exceptions or delete a Back transition.

**F2 — selected-people regression addresses the wrong accessible name.** The same log shows `test_type_switch_keeps_people_missing_from_ordinary_options` timing out at `get_by_label("Customer · optional", exact=True)`. The real select has explicit `aria-label="Customer"`; that overrides the wrapping visible label for its accessible name. Change both specialized customer locators to the actual exact accessible name, preserving all value, checked-option-name and outgoing payload assertions, and run the real regression. The current failure occurs before the retention behavior is exercised.

These are test-execution findings, not evidence that assertions were gamed or weakened. The backend grade and static assertion design are sound, but the final batch cannot yet certify its new browser claims. Root has been notified; source lock is released for bounded corrections.

Initial verdict: findings-open (superseded by the bounded recheck below).

## Final recheck — both harness findings closed

Independently read the final two test corrections and root's real focused execution log `/home/johnny/.cache/tastings/typed-browser7-focused.log`: **2 passed**,25 deselected, two existing warnings,14.88s. This execution was run by root, not repeated by this evaluator.

- **F1 closed.** The test now places a marker in the current document, uses Playwright's actual `page.go_back(wait_until="commit")`, checks each of the same two exact destination patterns, and waits for the marker to disappear and a replacement document to finish loading. It then still requires initialized Tasks/Alpine controls, a successful search-empty/clear interaction and opening the original tasting detail. No Back transition, URL assertion or behavior assertion was removed, and no exception is caught or suppressed. This fixes the evaluation-protocol race while strengthening the proof that restored interactions operate in a fresh document.
- **F2 closed.** Both specialized customer selectors now use the select's exact accessible name `Customer`. Exact selected IDs/display names, round-trip customer value and outgoing contact/assignee assertions remain unchanged. The focused green run therefore exercises the intended retention behavior rather than stopping at an invalid locator.

All earlier static and mutation evidence remains applicable. No application/test/script was edited by this evaluator, and no test-validity finding remains open. This is the independent validity grade; the caller still runs its required final aggregate checks and CI.

VERDICT: valid
