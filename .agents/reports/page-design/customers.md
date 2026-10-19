# PAGE DESIGN — Customers — 2026-10-19

plan: docs/customers-redesign-plan.md
research: 3 comparable products (Pipedrive, HubSpot, Attio), 2 craft references (Linear, Notion), 1 pattern source (Carbon)
directions considered: 3; selected by founder: Style 1, Directory
verdict: patched — selected implementation complete; no remaining visual or independent-review findings

## Selected result

The full-width Directory is the only production layout. Removed the temporary chooser, Desk and Contact book DOM/CSS/helpers, URL/session selection, and Desk region/resize logic. Preview is an accessible modal drawer at every width, with keyboard focus trapping and return to its opener. Search, status, missing-details filtering, ordering, server pagination, real record links, create/edit and permission-aware Xero actions retain their existing APIs. Recent CRM creation/Xero regressions from !527/!538/!539 remain covered. No schema, API, calculation, tenant/auth or export changes; no production data used.

The source/open-MR audit selected Customers as a primary Sales destination without competing redesign work. Sales tasks, Batch matching and customer detail remain separate candidates. The plan preserves the research and three-direction comparison history rather than inventing a reason for the founder's choice.

## Final screenshot evidence

`~/.cache/workflow-engine-ui-shots/customers-style1-final/01`: **37 final PNGs, every image inspected**, all seven scenarios passed, zero console errors and an empty visual defect list. Busy and quiet directories at 390/1024/1440/1920 in both themes, archived/missing/search/no matches, loading/empty/error/retry, long contacts, desktop/phone drawer, create/save navigation and real boosted return/search are included. All 37 uploaded into !540. Private synthetic fixture purged successfully; state credentials were not committed or published. Independent parent spot-checks of phone, phone drawer and dark also found no defects.

Historical comparison evidence remains at `customers-design/{00-before,01,02,03,04}`: 9 baseline/sibling, 30 first-pass, 63 second-pass, 68 final comparison and 12 unchanged-code supplemental images, all inspected. Pass 01 had a scenario failure and visual findings; pass 02 had clean execution but visual findings. Pass 03 plus supplemental 04 were clean. Those findings and fixes remain in the plan. The final selected-layout pass above was rerun after removing the rejected designs.

## Final verification

- Selected page plus existing contact-sync browser/API suite: **46 passed**,17 warnings,44.94s (`customers-style1-final/tests-page-final.log`). All nine selected-page cases ran, including strengthened main-scroller overflow assertions.
- Shared production layout, pages, boosted navigation, CRM flow/API and navigation suite: **272 passed**,123 warnings,395.09s (`tests-shared-final.log`). **318 passed total in two serial processes.** Warnings are existing Flask-Limiter local storage and structlog formatting notices.
- An initial combined nine-file invocation ended **232 passed / 86 setup errors** (159.77s), with shared `app_url`, `logged_in_page` and `e2e_user` fixtures absent during setup. This was not counted as a pass. The same suites then passed in the original separate invocation groups; no fixture, test assertion or application change was made to achieve those results. Precise import/collection-order root cause was not established; retained log `tests-final.log` documents the limitation.

- Ruff app + changed test, Node syntax and diff whitespace: pass.
- Semgrep auto on final app template/script: **214 rules, zero findings**. Screenshot helper unchanged since exploration; earlier separate 290-rule scan had two unchanged trusted-CLI patterns and baseline-aware comparison zero new findings. No suppression added.
- Independent test evaluation and final HTML/JS/CSS review: **valid / clean**, `.agents/reports/test-evaluator/2026-10-19-customers.md`. The four original behavioral cases are unchanged. Four selected Directory width cases replace the temporary concept matrix; one real boosted return/search case replaces the concept persistence matrix. Desk-only close/resize tests retire with their removed structure, not to hide a failure.
- Independent CSS mutation exposed a real validity gap: forcing 1100px page width at 390px escaped the document-only overflow check. All four width cases now additionally check the actual `#page-content` scroll container. Verified mutation then failed at the added assertion (7.25s); restoring exact CSS passed (8.19s). The earlier exact-link href mutation also failed, then passed on restoration. All probes ran in a separate disposable worktree, now removed; author production files were never mutated.
- No dependency, migration or shared-runtime changes. MR head CI is monitored separately in GitLab; readiness is set only after its exact head passes. No merge or automatic merge enabled.
