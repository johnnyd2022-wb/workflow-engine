# PAGE DESIGN — Customers — 2026-10-19

plan: docs/customers-redesign-plan.md
research: 3 comparable products (Pipedrive, HubSpot, Attio), 2 craft references (Linear, Notion), 1 pattern source (Carbon)
directions: 3 (Directory, Desk, Contact book); chosen: awaiting the pick
passes: 3 plus baseline and an unchanged-code supplemental state pass; defects fixed during concept passes: 6 (phone header/chooser density, laptop Desk structure, status accessible name, closed Desk layout, modal focus on resize, URL-style persistence)
screenshots: ~/.cache/workflow-engine-ui-shots/customers-design/{00-before,01,02,03,04}; counts 9 / 30 / 63 / 68, plus 12 supplemental images in 04, all inspected
verdict: findings-open — three finished options are presented for a founder choice; final visual pass has no remaining defects

The source/history audit selected Customers because it is a primary Sales destination without prior design work or a competing open MR. Sales tasks, Batch matching and customer detail remain separate candidates. Recent customer creation and Xero fixes from !527/!538/!539 are retained.

The original page's duplicate connection actions, control stack, phone table and dark header are recorded in the plan. Customer names now have real keyboard-accessible links. Phone/email and sync metadata remain reachable through preview; full customer records and original create/edit/Xero flows remain in place. Contact book counts explicitly refer to the current result page, not the entire directory.

## Screenshot evidence

`01` found phone density, missing laptop split and an inaccessible select label; its interaction scenario failed and the pass was not clean. `02` captured every scenario without execution errors, but review still found closed Desk and resize-focus issues, non-persistent URL concepts and the wrapping phone header. `03` captured 68 images with no scenario/console failures and an empty visual defect list. It includes actual create/save navigation and cleanup in the private fixture, filtered/empty/error/recovery/loading states, phone long contacts, boosted return and explicit close/reopen at 1024/1440 plus modal resize. No scenario was removed to get a clean pass. Supplemental `04` adds all three quiet layouts at laptop/phone/dark and empty phone: 12 more images, all inspected with no defects on unchanged code. Both screenshot fixtures were purged successfully.

## Verification

- Page, all 22 new browser cases, existing contact-sync UI and API regressions: **59 passed**, 30 warnings, 44.74s. Warnings are Flask-Limiter's existing in-memory local storage notice.
- Shared layout/render/boosted navigation, CRM flow/API and navigation: **272 passed**, 123 warnings, 351.71s. No failures.
- Ruff app + changed Python files, node syntax, diff whitespace: pass.
- Semgrep auto: **214 rules on both changed template/script files, zero findings**, final code. The screenshot helper separately ran 290 rules: two pre-existing trusted-CLI findings (dynamic model import, existing fixed-host GitLab upload) are present unchanged on origin/main; baseline-aware comparison reports zero new findings. No suppression added.
- Independent test evaluation and HTML/JS/CSS review: **valid / clean**, `.agents/reports/test-evaluator/2026-10-19-customers.md`. Existing tests/assertions unchanged. Reviewer changed only exact customer links in a separate disposable checkout: keyboard link test failed at href assertion, then passed when restored. Author checkout never mutated.
- New Desk close-width and resize-focus tests: all three failed on the pre-fix implementation, then pass after the fixes. URL-style tests for 2/3 failed at persisted-style checks before correction. A separate provisional Style 1 filtering failure was caused by test interaction before boosted initialization; explicit network-idle readiness fixed the test while retaining the actual one-result filter assertion. No shared runtime change was made. Removed redundant explicit x-init because Alpine already calls init.

No schema/API/calculation/export changes. No production data used. No Slack announcement: this is deliberately a draft comparison MR. Human style selection and merge remain pending.
