# Biz-E UX overhaul: navigation, page loading, layout and consistency

- **Owner:** Johnny (founder). **Executor:** sonnet-master. **Written:** 1 October 2026.
- **Evidence:** the audit folder `audit-2026-10-01/` (kept by Johnny in `mc/ux-overhaul/`, not committed: about 13 MB of screenshots): 47 pages, each screenshotted after a full load (`*__full.png`) and after a boosted in-app click (`*__boosted.png`), plus `results.json` with text length, element count, "Loading…" count and console errors for each.
- **Tracking:** this file lives at `docs/ux-overhaul-plan.md`. Items in the work plan carry stable IDs (`1.3`, `4.5`) and are ticked with the MR number as they land. `docs/source-to-sale-plan.md` points here rather than duplicating them.

## Goals (from the founder)

1. **Pages load fully on in-app navigation.** htmx boost must give the same page as a full load, with no refresh needed.
2. **Fix placement** of icons, buttons and sections. Some are poorly placed at a glance.
3. **One consistent UI style** across every screen.
4. **Five main tabs only:** Dashboard, Production, Compliance, Sales, Settings. Everything else lives inside one of them. Planner and contract orders belong inside Production.

## What the audit found

### A. Boosted navigation is broken on 19 of 47 pages

Boost is set on `<body>` in `app/core/frontend/shared/base_spa.html`, with `hx-target="#page-content"` and `hx-select="#page-content"`. Only `#page-content` is swapped. That causes two faults:

- **Page assets are dropped.** 53 of the 56 `base_spa` pages put CSS in `{% block head_extras %}` (in `<head>`) or JS in `{% block scripts %}` (after `</main>`). Both are outside `#page-content`, so a boosted swap never loads them. The workaround so far has been:
  - loading ever more page stylesheets globally in `base_spa`, plus every CRM script;
  - putting `hx-boost="false"` on links: 94 times in 47 files, including 4 of the 7 sidebar links;
  - a special case that reloads `/core` after a swap.
- **Page init never runs.** 43 JS files start on `DOMContentLoaded`, which doesn't fire after a swap.

**Broken when reached by a boosted click** (from `results.json`; see the paired screenshots):

| Page | Symptom when boosted |
|---|---|
| `/compliant/nz-alcohol/np3-audit` (and `/food-safety`) | Unstyled; giant black SVG donut; "Loading…" never resolves; 80% of content missing |
| `/compliant/nz-alcohol/licensing`, `/customs`, `/evidence` | 30–60% of content missing |
| `/compliant/nz-alcohol`, `/premises`, `/food-registrations` | Stuck "Loading…" or partial content |
| `/crm/analytics` | 14 console errors; partial render |
| `/core/inventory/live`, `/core/stocktake`, `/core/site-transfers`, `/core/go-live` | Stuck "Loading…", sections missing |
| `/core/executions/live`, `/core/planner`, `/core/planner/board`, `/core/cases`, `/core/cases/new`, `/core/notifications`, `/core/flows/create/template-catalog` | Content missing (the data or init script didn't run) |

**Aliases and redirects found on the way** (to tidy under goal 4):
- `/compliant/nz-alcohol/food-safety` = `np3-audit`, and `/evidence` = `customs`.
- `/core/integrations` lands on `/crm/configuration`.
- `/core/tasks` lands on `/core`.
- `/core/sites`, `/core/people` and `/compliant/nz-alcohol/configuration` redirected the test user to the dashboard. Check whether that's a permission redirect; if so, the redirect should say why rather than silently bouncing.

### B. Navigation (information architecture)

- **Today's sidebar has 7 tabs:** Dashboard, Production, Planner, Compliance, Sales, Contract orders, Settings.
- **Unreachable pages.** These have no in-app link at all, only a typed URL: `/core/stocktake`, `/crm/analytics`, `/compliant/tools`. Inventory view, site transfers and integrations are only linked from obscure places (a case detail page, a JS file, the account menu).
- **Production hub** (`/core`, `core2.html`) links to only 5 places. Planner, contract orders, stocktake, trace (source map), sites, transfers and cases aren't in it.
- **Sub-navigation** exists as three different components:
  - a Production segmented bar (Overview / Inventory / Product workflows / Tasks);
  - Sales `_crm_section_tabs.html`;
  - Compliance `_nz_alcohol_tabs.html`.
  - Planner, contract orders, sites and settings have none.

### C. Layout and placement (from the screenshots)

- **Production** (`core__full.png`):
  - The primary action "Add to inventory" floats left of centre under the title instead of aligning with it.
  - The setup stepper is centred above the page heading.
  - "OVERVIEW" and "OPERATIONAL STATUS" headings are ALL CAPS, and stat cards mix centred and left-aligned text.
  - "Active Batches" uses Title Case.
- **Planner board** and **Contract orders** (`core_planner_board__full.png`, `core_contracts__full.png`) are off the design system:
  - browser-default grey buttons ("Show board", "Today", "Plan batches");
  - raw blue underlined links as navigation ("Production demand", "Customer raw materials");
  - native `<details>` disclosure rows, and headings with no card structure.
- **Contract orders** puts the create forms ("New order", "New contract customer") inline above the list. The empty "Orders" list is at the top, and 12 order fields are crammed into a 4-column grid with the submit button tucked in at the end of a row.
- **Sales:**
  - the active tab has dark text on bright blue (poor contrast);
  - "Add Widget" floats alone at the bottom right;
  - widget lock and move icons repeat on every card.
- **Settings** (`core_settings__full.png`):
  - one long column of full-width inputs (a 1-digit timeout field spans 1,000 px);
  - three separate centred save buttons;
  - no sections or sub-navigation, and nothing for organisation, sites, people or integrations, which live elsewhere.
- **Dashboard:**
  - the go-live card has a large empty area;
  - workspace labels are cased "CORE", "COMPLIANCE", "Sales";
  - flat zero sparklines add noise when there's no data.
- **Compliance** (the boosted versions): breadcrumbs render as raw links when unstyled. The home page uses a hero banner that no other area uses.
- **Shell:**
  - the sidebar header crams a two-line strapline next to a floating blue hamburger;
  - Logout sits mid-sidebar, detached from the account menu;
  - the yellow back arrow in the top bar appears on some pages and not others.

### D. Consistency

- **Three tab styles, several button styles, two card styles.** Heading case varies: ALL CAPS, Title Case, sentence case.
- **Page-scoped CSS files** each redefine buttons and inputs: `compliant.css`, planning, contracts, sites and so on. Colour tokens exist in `base_spa` and sidebar CSS, but many pages hard-code hex values and inline styles (the sidebar itself is full of `style=` attributes).

## Target information architecture

Five sidebar tabs, each with **one shared section sub-nav component** (a horizontal tab bar under the page title) plus in-page links for third-level pages.

| Main tab | Sub-nav tabs | Pages that move there |
|---|---|---|
| **Dashboard** `/core/dashboard` | none | Go-live (setup) becomes a dashboard card or a step-through launched from it. The notifications bell stays in the top bar. |
| **Production** `/core` | Overview · **Planner** · Batches · Workflows · Inventory · **Contract orders** · Suppliers | Planner: `/core/planner`, `/board`, demand. Batches: `/core/executions/live`, execution queue. Workflows: `/core/processes`, `/core/flows*`, template catalog. Inventory: view, add (manual, barcode, CSV), stocktake, disposal, live, **Trace and recall** (`/core/sourcemap`), site transfers. Contract orders: `/core/contracts`, materials, portal sharing (inside the order). Overview holds "Needs attention" (cases, tasks). |
| **Compliance** `/compliant` | Overview · NP3 · Customs · Licensing · Premises · Food registrations · Tools | Make `/compliant/tools` reachable. Collapse the `food-safety` and `evidence` aliases with redirects. Compliance configuration opens from a "Compliance settings" link, so it isn't a peer tab. |
| **Sales** `/crm` | Overview · Customers · Tasks · Batch matching · **Analytics** | Analytics becomes reachable. Sales configuration moves to Settings, or a settings cog in the section header. |
| **Settings** `/core/settings` | My account · Organisation · People and roles · Sites · Integrations · Notifications · Section settings | My account covers profile, password, 2FA, session and appearance. Organisation covers the company. Integrations covers Xero (today `/crm/configuration` and `/core/integrations`). Section settings covers the task board configuration and links to compliance and sales configuration. |

**Why contract orders live under Production:** a contract order is work Whistlebird makes for a customer. It drives planned batches, reserves customer-supplied materials, and is fulfilled by production runs, so its home is next to Planner. Two deliberate cross-links, not duplicates:
- the Planner shows contract-order demand, with each item linking to its order;
- a Sales customer's detail page lists that customer's contract orders, each linking into Production.

Keep existing URLs working. Where a page moves, keep the old URL as a 301 redirect, or just change which tab is marked active; don't break bookmarks. `active_page` becomes `active_section` (sidebar) plus `active_tab` (sub-nav).

## Work plan (one MR per step, in order; each through its own green pipeline)

### 1. Boost-safe page loading (goal 1). Do this first; everything else builds on it.

- [x] **1.1** (!471) **Harness first, as a committed regression test.** `tests/e2e/test_boosted_navigation.py` walks every page in a registry (below). For each page it loads the page directly, then reaches it by a boosted click from the dashboard, and asserts that the boosted render:
   - matches the full load (element count within 10% and the same key selectors present);
   - has no new console errors;
   - has no "Loading…" left after the network goes idle.

   It starts `xfail` for the 19 known pages, and each fix removes an `xfail`. The audit harness used for this plan was a temporary version of the same thing: `e2e_user` + `FeatureSubscriptionFactory(feature_key="compliant")` + `storage_state_path`, then page.goto, then inject `<a href>` into `#page-content`, `htmx.process`, click. Remember the memory note: CI skips e2e in `relevant_tests`, so prove fail-before and pass-after locally.
- [x] **1.2** (!471) **One page registry.** Add `app/ui/page_registry.py` listing every page: URL, section, sub-nav tab, title, required permission and feature flag. The sidebar, sub-nav, breadcrumbs and the e2e test all read from it, so none of them can drift again.
- [x] **1.3** (!472) Done differently from the letter of the plan: a boosted response (`HX-Boosted`) carries the assets inside `#page-content`; a full load keeps CSS in head and scripts at the end of body, so script order is untouched. Alpine initialises after the swap settles. **Move page assets into the swapped region.** In `base_spa.html`, render a `<div id="page-assets">` inside `<main id="page-content">` that holds `{% block head_extras %}` and `{% block scripts %}` output. htmx 1.9 runs `<script>` tags in swapped content. Stylesheet `<link>` tags in body content load in all target browsers. Guard against double-loading shared libraries: page scripts must be idempotent, and library scripts stay in the head.
- [x] **1.4** (!472) `bize.onPage` added; go-live, people, sites, stocktake, licensing and verification converted. The rest already guard with `readyState` and per-root flags and work unchanged. **One page-init convention.** Add a small `app/ui/shared/page-init.js`: `bize.onPage(selector, init)` runs `init(root)` on first load and after every `htmx:afterSettle` whose content contains `selector`, and runs teardown on `htmx:beforeSwap`. Convert the 43 `DOMContentLoaded` page scripts to it, starting with the 19 broken pages.
- [ ] **1.5** (!472 did the links and the `/core` reload; still to do: page stylesheets and CRM scripts loaded globally in `base_spa` for boost's sake, and `hx-boost="false"` on JS-handled forms) **Delete the workarounds** once their page passes the test:
   - the 94 `hx-boost="false"` attributes (keep them only on real non-HTML links: downloads, OAuth, logout, external);
   - the `/core` reload special case;
   - page stylesheets and CRM scripts loaded globally only for boost's sake.
- [x] **1.6** (not needed: the assets approach sufficed) **Consider the htmx `head-support` extension** (1.9-compatible) only if step 3 proves insufficient for a page; don't add it by default.
- [x] **1.7** (!472) Back/forward reload from the server (`historyCacheSize 0`, `refreshOnHistoryMiss`); covered by an e2e test. **Keep the history cache in mind.** Check that back and forward buttons restore a working page. Setting `htmx.config.historyCacheSize = 0` is acceptable if restored snapshots come back inert.

**Done when:** all 47 pages pass the boosted-navigation test, sidebar and sub-nav links are boosted, and no page needs a refresh.

### 2. Navigation: five tabs and section sub-navs (goal 4)

- [ ] **2.1** **Sidebar.** Reduce it to Dashboard, Production, Compliance, Sales, Settings, driven by the registry, with the same permission and feature gating as today.
- [ ] **2.2** **One shared sub-nav partial** (`app/ui/templates/shared/section_tabs.html`). It replaces the Production segmented bar, `_crm_section_tabs.html` and `_nz_alcohol_tabs.html`, and is added to Planner, Contract orders, Inventory pages, Settings and so on, following the target IA table.
- [ ] **2.3** **Breadcrumbs** from the registry for third-level pages (for example Production › Contract orders › Order CO-12 › Portal sharing). Replace the ad-hoc yellow back arrow with the breadcrumb, or make the back arrow consistent on every non-root page.
- [ ] **2.4** **Move pages to their new homes.** Add redirects for moved or aliased URLs, and make the unreachable pages reachable (stocktake, sales analytics, compliance tools).
- [ ] **2.5** **Settings restructure.** Add a sub-nav, move integrations (Xero), sites, people and section settings in, and reduce each form to its own card with one save button.
- [ ] **2.6** **The two contract-order cross-links** (Planner demand to order; Sales customer to their orders).

**Done when:** every page in the registry is reachable in at most 2 clicks from its main tab, and no page is linked only by typed URL. Add a test that walks the registry and asserts an in-app link exists to each page.

### 3. Consistent components and styling (goal 3)

- [ ] **3.1** **Write `docs/ui-style-guide.md`,** short and by example. It covers:
   - page header (title, one-line description, primary action top-right, secondary actions beside it);
   - section sub-nav;
   - card (title in sentence case, optional action link top-right);
   - stat tile; table; empty state (one sentence plus one action);
   - buttons (primary, secondary, danger, link) and form layout (label above, widths by content type, one primary submit bottom-right of the form card);
   - `<details>` replaced by a styled disclosure;
   - status badges; toasts.

   Headings use sentence case everywhere; eyebrow labels are the only small caps.
- [ ] **3.2** **Shared CSS.** Put tokens and components in one file (`app/ui/shared/components.css`), loaded globally. Page CSS keeps only page-specific layout. Replace hard-coded hex values and inline `style=` with tokens and classes. The sidebar is the first target.
- [ ] **3.3** **Fix contrast.** Active tab text on blue must meet WCAG AA. Check dark mode, which exists in Settings, on every converted page.
- [ ] **3.4** **Add a lint-style test** that fails on a new `style=` attribute, hex colour or `<button>` without a component class in templates. Grandfather the existing ones with a shrinking allowlist.

### 4. Page-by-page layout fixes (goal 2)

Go through the audit screenshots in this order; each item is a small MR or a batch of small ones.

- [ ] **4.1** **Shell:**
   - a one-line logo in the sidebar header;
   - the collapse toggle aligned with it, not a floating blue circle;
   - Logout moved into the account (bee) menu;
   - notifications and account menu aligned right in the top bar.
- [ ] **4.2** **Production overview:**
   - page header with the primary action ("Add to inventory") top-right;
   - the setup stepper as a dismissible card under the header, shown only until setup is complete;
   - consistent stat tiles.
- [ ] **4.3** **Planner board:**
   - controls (view, date, Today) in a toolbar row;
   - batch sizes and site capacity as styled disclosures or a side panel;
   - demand selection and "Plan batches" / "Check materials" as a clear action group;
   - a week grid with an empty state inside the grid.
- [ ] **4.4** **Contract orders:**
   - the list first, with the primary action "New order" top-right opening a form page or drawer;
   - customers as its own sub-tab or a panel with "Add customer";
   - the order form grouped into sections (Customer and reference, Product and quantity, Materials and specification, Duty and status).
- [ ] **4.5** **Sales:**
   - fix the tab contrast;
   - "Add widget" goes into the page header actions;
   - widget controls show only on hover or in an edit mode.
- [ ] **4.6** **Settings:** cards per the style guide; inputs sized by content.
- [ ] **4.7** **Dashboard:**
   - trim the go-live card;
   - consistent eyebrow casing;
   - hide sparklines when all values are zero.
- [ ] **4.8** **Compliance:** make the hero banner consistent with other section overviews (or drop it for the standard page header).

Re-run the audit harness after each area and attach before/after screenshots to the MR description.

## Rules for the executor

- **Separate MRs.** Steps 1, 2, 3 and 4 are separate MRs, and step 4 can be several. Keep each MR reviewable (under about 800 changed lines where possible).
- **Don't change behaviour and layout in the same MR** as a navigation move.
- **Tests:**
  - run the full suite before pushing;
  - e2e tests need a local fail-before and pass-after (CI skips e2e in `relevant_tests`);
  - never bypass CI;
  - don't commit `.agents/metrics`.
- **Worktrees:** use your own worktree; no scripted forced checkouts in shared ones.
- **Before/after screenshots** in each MR description, taken with the harness.
- **Ask Johnny** before removing any page outright. Moving or redirecting is fine without asking.
