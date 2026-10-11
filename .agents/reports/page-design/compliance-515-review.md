# Compliance review after Production !515 — 2026-10-11

Scope: independent HTML/Jinja2, JavaScript and test-validity review of Compliance !514's updated three concepts. Style 1 Board follows Production !515; Style 2 Action desk and Style 3 Register vary the content layout. Reviewed the branch diff against `origin/main` and the assertion changes in the current update. No application or test edits made by this reviewer.

## HTML and JavaScript

**Verdict: clean. No unresolved actionable findings.**

- Shared SPA shell and section header provide the single Compliance h1. Header actions stay inside `#page-content`; the lifecycle callback finds the dynamic primary through the closest page content. Initial/loading/error states hide it and remove its destination. Permission-dependent configuration destinations remain gated by the rendered manage capability.
- Server strings use text nodes, control queries are encoded, the read-only overview GET has visible loading/error/retry handling, and the lifecycle teardown aborts the request. There is no mutation endpoint, backend authorization change or new credential storage.
- Reading order remains readiness, next action, obligations and workspace links. Style 2 explicitly opens the additional-action disclosure; Style 3 starts framework disclosures closed. Independently exercised native `<details style="display: contents">` in Chromium: its body is visible while open and hidden after closing.
- Final CSS-only adjustments inspected after the runtime snapshot: the dark primary rule overrides the shared button treatment; Style 2 framework cards stack; Style 3 data coverage spans the readiness band. These do not change template, script or test semantics. Final screenshot review belongs to the orchestrator.

## Test evaluation

**Verdict: valid.**

Assertion-changed tests reviewed: `test_concepts_keep_evidence_and_actions_reachable` (12 style/viewport cases), `test_all_returned_actions_expand_and_primary_opens_mapping`, `test_concept_switch_remembers_choice_and_survives_boosted_return`; newly added `test_primary_action_matches_production_row_and_hides_during_reload`. Existing permission-display test was included as the mandatory risk probe. Every scoped case asserts observable behavior. No skipped cases, swallowed assertions, tautologies or silent weakening found. Moving the primary-link locator from the action card to the page preserves exact destination and real navigation assertions. Renumbering Board from 2 to 1 updates its geometry checks; the parameterized viewport set remains unchanged.

Independent isolated snapshot: `/tmp/compliance-515-evaluator`.

1. Primary-treatment and reader-permission baseline: **2 passed**, `/tmp/compliance-515-evaluator-green.log`.
2. Changed only the isolated script's manage predicate to `canManage = true`: reader test **1 failed** as expected, `/tmp/compliance-515-evaluator-permission-mutant.log`.
3. Restored script; changed only the isolated primary CSS to the secondary surface treatment: primary test **1 failed** as expected, `/tmp/compliance-515-evaluator-style-mutant.log`.
4. Restored both; assertion-changed tests plus permission probe: **16 passed in 43.51s**, `/tmp/compliance-515-evaluator-restored.log`.

After restoration, script, template, CSS and test SHA-256 values matched the shared worktree snapshot. The caller subsequently made the CSS-only adjustments listed above; no template, script or test changes followed. No mutant was applied to the shared worktree. Shared editable-package metadata was restored to the Compliance worktree after the isolated run.

## Coverage limits

The new primary test proves successful rendering, desktop/phone action geometry, filled-primary distinction, failed initial load and error-to-retry recovery. `_open` waits for loading to finish, so this test does not certify transient delayed-response visibility or failure after a prior successful response in the same mounted page. The caller's loading screenshots are separate evidence. Browser runtime and native disclosure sampling here used Chromium only. This report does not independently certify screenshot aesthetics, screen-reader behavior, backend authorization or tenant isolation; no corresponding backend paths changed in this update. Final CSS adjustments were statically reviewed rather than included in the independent 16-case snapshot run.

## Shared overview test update — independent follow-up

Scope added: `test_compliance_overview_groups_obligations_and_actions_in_cards` in `tests/e2e/test_workspace_overviews.py`, all three existing widths (390, 1024, 1440). **Verdict: valid.** The wide-screen full-width readiness assertion described the superseded single-column layout. Its replacement explicitly guards the requested Board: readiness and Next action share a row, readiness precedes Next action, and Next action ends at the full-width obligation card's right edge. Obligation/manage widths remain equal at every width; the original three-card width equality remains on narrow screens. Content, containment, reading-order, workspace-link geometry and horizontal-overflow assertions are retained. This is a documented behavior change, not silent widening.

Updated the isolated snapshot with final CSS and this test file. Independent results:

- All three widths: **3 passed in 10.70s**, `/tmp/compliance-515-evaluator-shared-green.log`.
- Mutated only isolated Board readiness from `grid-column: span 5` to `span 12`: wide-screen case **1 failed** as expected on same-row geometry, `/tmp/compliance-515-evaluator-shared-mutant.log`.
- Restored exact final CSS: wide-screen case **1 passed in 5.31s**, `/tmp/compliance-515-evaluator-shared-restored.log`.

Final CSS and shared test snapshot hashes match the worktree after restoration. No shared app/test mutations. This follow-up exercises the final CSS at three widths, supplementing the earlier 16-case run; it does not extend the stated cross-browser or screenshot-aesthetic coverage.

## Static module-title test update — independent follow-up

Scope added: `test_nz_alcohol_module_has_a_dedicated_page` in `tests/test_compliant_module_pages.py`. **Verdict: valid.** Requiring a literal local `<h1>Compliance</h1>` was obsolete after the shared-title adoption. The replacement checks the actual overview's shared-header opt-in, rejects a local duplicate h1, and renders the real shared section template to assert exactly one Compliance h1. The existing route, overview-surface and configuration-label assertions remain. This is an explicit relocation contract supported separately by twelve actual-page browser cases, not an assertion deletion to conceal a missing heading. The isolated shared-template render certifies that partial's opt-in behavior; it does not replace full-page integration coverage.

Independent isolated-copy results:

- Exact updated unit case: **1 passed in 0.09s**, `/tmp/compliance-515-evaluator-title-green.log`.
- Mutated only isolated dashboard opt-in from `true` to `false`: **1 failed in 0.10s** as expected, `/tmp/compliance-515-evaluator-title-mutant.log`.
- Restored exact dashboard: **1 passed**, `/tmp/compliance-515-evaluator-title-restored.log`.

Dashboard and unit test hashes match the current worktree after restoration. No shared application or test edits made by the reviewer; only this report was appended.
