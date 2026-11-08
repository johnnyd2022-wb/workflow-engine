# TEST EVALUATION — 2026-10-11

Batch: `tests/e2e/test_compliance_design.py`, all newly added tests. No existing tests or assertions changed. Skill: `.claude/skills/test-evaluator/SKILL.md`; autonomy policy read.

## Static review

| Test | Claim and validity |
|---|---|
| `test_setup_checks_are_visible_in_readiness` | Nonzero setup checks from the API must appear in the UI total. Independent API-to-DOM comparison; not backend count verification. |
| `test_customs_and_np2_have_honest_evidence_labels` | Customs must not carry NP3 or Compliance score labels; NP2 link must exist. Positive NP2 assertion prevents a wholly empty UI from passing. |
| `test_concepts_keep_evidence_and_actions_reachable` | Twelve style/viewport cases enforce real regions, two obligation articles, links and no horizontal overflow. Board geometry is independently measured. Register disclosure must toggle via keyboard. |
| `test_all_returned_actions_expand_and_primary_opens_mapping` | API queue title/count/link assertions plus real configuration navigation. Expectations originate in server response, not the renderer. |
| `test_concept_switch_remembers_choice_and_survives_boosted_return` | Choice is reflected in URL/pressed state and persists after swaps. Window sentinel rejects full-navigation substitution. Explicit query overrides remembered style. |
| `test_failed_load_has_no_success_totals_and_retry_recovers` | Injected 503 must produce unavailable state and dash; unroute and retry must render real frameworks and remove error. |
| `test_setup_and_quiet_states_do_not_invent_assurance` | Empty frameworks cannot claim current evidence; real frameworks with empty queue retain review warning. Synthetic response is a deliberate state stimulus, not a fixture asserted against itself. |
| `test_access_errors_offer_sign_in_or_admin_instead_of_retry` | 401/403 injected API failures must expose different UI guidance and hide retry. Tests presentation, not server authorization. |
| `test_np2_and_customs_links_boot_their_destination_scripts` | Real destination DOM populates after each link. More than a URL-only navigation smoke test. |
| `test_non_manager_has_no_configuration_action` | Actual read-only role must get admin guidance, no mapping/configuration links, and readable programme link. Final MEMBER fixture has read access and excludes manage permission. The initial misselected COMPLIANCE role was corrected without weakening assertions. |
| `test_data_coverage_keeps_live_gaps_and_sources_accessible` | Explicit injected 3/7 counts and server scope must survive disclosure. |

Every scoped test has behavioral assertions. No catches swallowing failures, expected-value recomputation through renderer, catch-all statuses, skips, xfails, deleted assertions or silent widening found.

## Falsifiability evidence

Caller-recorded `/tmp/compliance-regression-before.log` proves both primary regressions fail unchanged main: setup readiness displayed `0 need attention` instead of `34 to review`; Customs displayed NP3 and Compliance score. `/tmp/compliance-tests-initial.log` reports those tests plus unchanged workspace suite green (32 passed). This samples presentational behavior with real old-code regressions rather than editing the shared tree.

Mandatory permission-display probe completed independently in isolated `/tmp/compliance-test-probe-dor7ncyf`:

1. Final MEMBER fixture with original code: **1 passed**, `/tmp/compliance-permission-baseline.log`.
2. Surgically replaced `var canManage = root.dataset.canManage === '1';` with `var canManage = true;`: **1 failed**, `/tmp/compliance-permission-mutant.log`. The assertion saw “Map products” instead of the required admin guidance. The test rejects leaking the configuration action to a reader.
3. Restored exact original script: **1 passed**, `/tmp/compliance-permission-restored.log`. SHA-256 matches the shared script (`0de54c999a8392d6af7aa2e63001dedbf112254b4ec480e7b3b4af6a07054b08`).

No shared app/test mutation performed. Only this report is written by the grader. No backend authorization, tenant isolation, money, inventory-write or idempotency code changed by this batch; injected 401/403 tests certify UI handling only.

## Coverage limits

Nonblocking followups: loading state before response; Customs action exact-control query; food current/attention/overdue filter hrefs; asserting disclosure/style switching does not refetch; failure after an already-successful load. These are not certified by the current assertions. Screenshot checks, dark theme and server isolation are separate from this test batch.

## Verdict

**valid**. Every scoped test asserts a real claim; no existing assertions were weakened. Sampled presentation regressions demonstrably fail old code; the permission-display test passes final code, fails a targeted mutant, and passes after restoration.

Runtime note: initial full suite had 20 passed / 2 failed (`/tmp/compliance-tests-new.log`): invalid COMPLIANCE role fixture and 1920/Register article-count failure before keyboard interaction. The fixture is corrected and independently green. Final stable code passed all 23 cases on three consecutive runs, including UTC (78.12s, 88.03s, 63.17s). This validity grade remains distinct from the runtime checks.
