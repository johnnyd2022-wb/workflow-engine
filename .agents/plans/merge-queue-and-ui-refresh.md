# Merge queue and UI refresh

Requested 4 October 2026. Work oldest-first; finish the existing queue before starting
UI changes. Preserve unrelated working-tree files and use an isolated worktree.

## 1. Integrate the existing merge requests

- [x] Review !461 (portal order timeline), fix blockers, verify current-head CI, merge.
- [x] Review !463 (planned production priorities), integrate updated main, fix blockers,
  verify current-head CI, merge.
- [x] Review !467 (capacity overload suggestions), integrate updated main, fix blockers,
  verify current-head CI, merge.
- [x] Review !476 (shared dev/test Google credentials), verify current-head CI, merge.
- [x] Review !477 (opt-in fast CI), integrate updated main, fix blockers,
  verify current-head CI, merge.
- [x] Confirm the original queue is empty and update the UI branch from merged main.

Merge only after required checks pass; fix causes without weakening tests. Retest a
new head after conflict repairs. Keep the CI implementation's own pipeline complete.

## 2. Understand and design

- [x] Review the UX roadmap, Sales overview reference, Production and Compliance hubs,
  navigation partials, permissions, empty states, status components, and current tests.
- [x] Capture baseline Playwright screenshots with a seeded isolated test organisation
  at desktop and 390 px mobile; document the specific clutter and spacing problems.
- [x] Define no more than four top tabs for Production, Compliance, and Sales.
  Keep secondary destinations reachable as contextual links/buttons on relevant pages.
- [x] Design Production's in-page health card: coloured health bar and useful status
  wording, with clear access to findings. Remove the competing top banner button.
- [x] Use shared button styles for Production CTAs, grouped in a clean action container.
  Follow the Sales overview's spacing, hierarchy, and simple cards across the hubs.

## 3. Build and iterate

- [x] Implement shared navigation/spacing changes and the Production overview actions.
- [x] Implement the Compliance overview to the same visual standard.
- [x] Simplify Sales tabs while retaining its existing visual strengths.
- [x] Preserve destination URLs, permissions, subscriptions, tenant isolation, deep
  links, keyboard access, and useful loaded/error/empty states.
- [x] Capture updated desktop/mobile Playwright screenshots; inspect and refine
  spacing, alignment, density, health states, and action placement until clean.
- [x] Exercise navigation and the main actions in Playwright; record evidence.

## 4. Deliver the UI MR

- [x] Run frontend/auth/navigation tests, lint and formatting; require normal CI security checks.
- [x] Update the UX roadmap with this MR's delivered items and evidence.
- [x] Commit scoped changes, push a UI branch, and open an MR with screenshots and
  concise before/after explanation. Leave this new UI MR open for founder review.
- [x] Record merged MRs, UI MR and validation evidence for review handoff.

## Integration evidence

- Main deployment failed because private auth variables were absent. Provisioned
  protected, masked `FLASK_SECRET_KEY`, `GOOGLE_CLIENT_ID`, and
  `GOOGLE_CLIENT_SECRET`, scoped to the test deployment environment, from KeePassXC.
  Main pipeline 2910554048 recovered through deploy, three browser smoke tests, and
  stable-image promotion. No test or merge gate was disabled.
- !461 integrated current main without conflicts; 25 local portal tests passed.
  The tested head was 8bce45c7; pipeline 2910582402 passed.

- !461 merged after successful exact-head pipeline 2910582402: 2,805 regression
  tests, browser smoke, security checks, and migration reversibility passed. The
  390 px portal flow also passed locally against the integrated head.

- !463 integrated main after !461, without conflicts. Follow-up f119b6bf restores
  the completed !459 drag entry. Forty-two local dashboard/planning tests pass,
  including live HTTPS Chromium at 390 px and 1440 px. Current-head pipeline:
  2910600505.

- !463 merged after exact-head pipeline 2910600505 passed all required jobs;
  2,808 regression tests passed. Main’s preceding release pipeline 2910599676
  also passed through deployment, browser smoke, and promotion.

- !467 integrated main after !463 without conflicts. Twenty-three local capacity
  tests passed, including 390 px and 1440 px Chromium suggestion/reschedule flows.
  Tested head 56b3c3c4; pipeline 2910621243 passed.

- !467 merged after exact-head pipeline 2910621243 passed all required jobs,
  including 2,808 regression tests. Main release 2910620676 passed before merging.

- !476 merged after exact-head pipeline 2910638578 passed: 2,812 regression tests.
  Local dev starts with the shared KeePass credentials; main release 2910638378 passed.

## UI design decisions and baseline

Desktop 1440 px and phone 390 px captures are in `/home/johnny/ui-refresh-artifacts`.
The baseline used a throwaway admin organisation, seeded inventory/workflow/batch,
and enabled NP3/licensing, with real HTTPS login. The organisation was cleaned up.
Navigation/registry baseline: 29 tests passed. E2E coverage inventory was run first.

- Production: Overview, Planner, Workflows, Inventory. Batches and contract orders
  become workspace actions; suppliers stay close to inventory. Tasks remains a page
  action. Preserve legacy `?tab=` URLs while removing the duplicate top tab row.
- Compliance: Overview, programme-specific Food safety, Customs, Licensing. Premises,
  registrations, tools, and configuration become permission-aware workspace actions.
- Sales: Overview, Customers, Tasks, Analytics. Batch matching and sales configuration
  become workspace actions. Keep dashboard widgets; place Add widget in the header.
- Use the existing registry for every URL/permission. Group secondary destinations
  beneath their primary parent and substitute a permitted secondary for roles whose
  primary parent is unavailable. Never exceed four primary destinations.
- Production gets a plain header, a prominent rectangular action card, a health card
  with explicit green/amber/red labels, and neutral pending/unavailable states.
  Preserve setup progress and the health details flow. Use roomier metric tiles.
- Compliance gets a standard header, a concise status card and roomy framework cards.
  Module-owned scores, evidence counts and links retain their meaning.

Acceptance: no more than four top tabs; each destination remains reachable for its
role; no horizontal page overflow at 390 px; keyboard-operable actions and menus;
health severity changes both colour and wording without reporting loading as healthy;
boosted navigation and legacy deep links work; real desktop/mobile screenshots inspected.

- !477 merged after exact-head pipeline 2910654779 passed: 2,820 regression tests,
  security, browser smoke, and migration checks. Rollback receives test-scoped secrets.
  The original queue is empty. UI work starts from main after all five merges.

## Visual iteration and validation

- Baseline: Production 7 primary destinations plus 4 duplicate in-page tabs;
  Compliance 8 and Sales 6. The new browser acceptance check failed on all three.
- Iteration 1: four primary destinations, contextual actions, plain headers, grouped
  Production actions and health card. Real HTTPS browser navigation passed.
- Iteration 2: scan-friendly Production metric tiles and operational status row;
  quieter Compliance framework cards; Sales Add widget moved into the header.
- Iteration 3: repaired dark-card, hover, icon and KPI contrast after screenshot
  inspection. Refined role permissions and keyboard focus for health details.
- Browser checks cover 1440 and 390 px, light/dark, healthy/degraded/critical,
  unavailable/pending and empty setup; inventory menu choices and legacy links.
- Existing all-page boosted-navigation checks passed with the new workspace suite:
  64 browser tests passed. Navigation, registry and asset checks: 50 passed.

- Final workspace browser stability: 12 cases passed three consecutive runs (3/3).
  The full suite passed: 2,860 tests, 507 skipped, using an isolated live HTTPS server on port 8005. Ruff check/format and diff checks passed; normal remote security checks remain required before review handoff.

## Delivery

UI MR: [!478](https://gitlab.com/whistlebird/workflow-engine/-/merge_requests/478),
left open for founder review. Its description includes the screenshot gallery and
local validation; exact-head remote CI results are added there before handoff.
Roadmap items 2.7, 4.2, 4.5 and 4.8 reference !478. All five original MRs merged
oldest-first with green required CI. No unrelated workspace changes were included.
