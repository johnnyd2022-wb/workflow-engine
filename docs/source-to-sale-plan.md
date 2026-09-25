# Source-to-sale product plan

Plan to turn biz-e into excellent **NZ craft-alcohol compliance software, from source to
sale**: the system a New Zealand distillery, brewery or winery trusts for production,
compliance and sales, from supplier lot to customer invoice.

Written 25 Sep 2026 from a product review of the running app (24 screens at desktop and
phone width), database checks on a live tenant with Xero sales connected, and the code.
Revised after founder review. Findings that only concern Whistlebird's own data
(back-filled dates, historic batches) are excluded; they are a data clean-up, not a
product change.

## How to use this plan

- **Tick items off in the MR that delivers them.** Change `- [ ]` to `- [x]` and append
  the MR number, e.g. `- [x] **1.2** Whole bottles … (!331)`. A partly delivered item
  stays unticked; tick its sub-items instead and note what's left.
- **Keep IDs stable.** Future MRs, findings and agents refer to items by ID (`1.3`,
  `4.7c`). Add new items with the next free number; don't renumber.
- **Re-check the evidence first.** Each item records what was true on 25 Sep 2026. Before
  starting, confirm it still holds; if an item is already fixed, tick it with a note
  saying where.
- **Don't reopen the decisions below** without the founder. They were made on purpose.
- Sizes are relative: **S** days, **M** about a week, **L** two weeks or more.
  **Critical** items affect stock accuracy or a new producer's first day.

## Decisions already made

| Topic | Decision |
| --- | --- |
| Pre-sales | Producers do sell stock before it's made. FIFO filling a sale from a later batch is correct, not an error. Make it visible, and give owners a choice of matching mode (1.1); never block it by default. |
| Partial fills | Whole units only for counted goods. Remainders go to a **Library stock** category by default, which can be sold, reused or written off (1.2). |
| Batch / lot IDs | No new lot-code concept. Orgs configure their own batch ID as a step prompt, and the production board already shows it (`core-active-batches-graph.js:140`). Label-run mapping (e.g. VATs to rolls of 500 labels) is org configuration. |
| Databases | At go-live a new production database holds real tenants, and a demo org lives in a test database (0.1). |
| Customs | The Customs page is placeholder data; the module isn't built yet. 2.1 is design rules for building it. |
| Module shape | NZ Alcohol is one module made of NP1/NP2/NP3, Customs and liquor licensing. Each part plugs into Core the way ABV does: required fields on the relevant steps when switched on, with no change to the producer's process (2.4). No second module is planned. |
| "Just works" | NZ producers expect it to work without setup or babysitting. Defaults must need no attention; control is opt-in. |

## What excellent means

The finish line for this plan. Each outcome can be tested.

| Outcome | How we know |
| --- | --- |
| **Recall in minutes.** From any finished batch or supplier lot to a customer list with quantities and contacts. | A timed mock recall takes under 5 minutes and ends in an export, with no manual lookups. |
| **Stock you can trust.** Finished goods in the system match the shelf. | Stocktake variance on finished goods is under 1%, and every screen shows the same number. |
| **Excise from records.** Litres of alcohol (LAL) per period come from recorded production and sales. | The producer checks a draft and files it, with no spreadsheet. |
| **Audit day is a download.** NP evidence pack, verification result and corrective actions are all in the app. | No manual assembly before a visit; the next verification date is always on screen. |
| **Live in a day.** A new producer goes from sign-up to a first traced sale in one sitting. | Template + Xero + go-live stocktake, with no back-dated history. |
| **Works on the floor.** Recording a step, scanning stock and attaching photo evidence work on a phone. | The main action is visible without scrolling at 390 px on every recording screen. |
| **Safe by default.** Admins use 2FA, production data is isolated, backups are restore-tested. | No admin can sign in with a password alone; a restore has been rehearsed. |

## Where it stands (25 Sep 2026)

**Strong foundations**

- Batch-to-customer recall works end to end: pick a finished batch and see every invoice
  and store it went to.
- Compliance rules are enforced by the server and reach production steps through the
  Compliant → Core workflow-rule seam, so Core never hard-codes a regulation.
- It carried a real producer through an MPI NP3 verification.
- 730 tests against a real Postgres database, and a tenant can be rebuilt from its sources.
- Xero sync, FIFO matching of sales to stock, and correct exclusion of voided and draft
  invoices.

**What stops it being excellent**

- Sales matching is FIFO only. The manual and hybrid options in configuration do nothing,
  so owners can't review pre-sold or unclear matches.
- Nothing stops fractional bottles, and there's no set place for a partly filled bottle
  to go.
- Getting started means reconstructing past production, which pushes producers to guess
  dates. Adding finished stock by hand is treated as an error.
- The interface explains itself instead of showing work, uses three visual styles, and
  shows different stock figures on different screens.
- Admins can sign in without 2FA.

---

## Phase 0: Safety and a green baseline

Small, and everything else builds on it.

- [ ] **0.1 Separate real data from test data.** *Planned for go-live.*
  - Plan: a production database for real tenants at go-live, and a demo org in a test
    database.
  - Remaining work: schedule backups and rehearse a restore before the first paying
    customer.
  - Done when: the test suite cannot reach a real tenant, and a restore has been
    rehearsed.

- [ ] **0.2 Require 2FA for owners and admins.** *Critical · S*
  - Evidence: the admin of a live tenant signs in with a password alone. The
    `/auth/verify-2fa` rate-limit finding (F6 in
    `.agents/reports/auth/security-audit.md`) is still open.
  - Change: an org policy that forces TOTP enrolment for admin roles at next sign-in;
    rate-limit 2FA verification.
  - Done when: no admin session can start without a second factor.

- [ ] **0.3 Keep main green.** *S*
  - [ ] a. Ruff check and ruff format pass on `main`.
  - [x] b. ~~Remove dead `app/features/workflow_engine/` and `dilution_calculator/`
    folders.~~ Not a repo issue: neither is tracked in git; they are untracked leftovers
    in one local checkout (delete locally if `test_ac9_package_and_factory_wiring_removed`
    fails).
  - [ ] c. Fix `CLAUDE.md` drift: test DB password (now `$POSTGRES_PASSWORD_TEST`), test
    counts, DAG code location (`CLAUDE.md` says `app/features/workflow_engine/`; it's
    `app/core/backend/dagtraversal.py`).
  - [ ] d. Run end-to-end tests in merge request pipelines (currently skipped by
    relevant-test selection).
  - [ ] e. Block merges while `main` is red.
  - Done when: a fresh clone passes lint and every test on the first run.

---

## Phase 1: Traceability you can stake a recall on

The core of the product. It should just work by default, give owners control when they
want it, and never produce a recall list that can't be trusted.

- [ ] **1.1 Let owners choose how sales are matched to batches.** *High · M*
  - Evidence: Sales configuration offers FIFO, manual and hybrid matching plus "manual
    review days", but only FIFO is implemented. Choosing manual or hybrid silently stops
    all matching (`app/features/crm/services/sales_traceability_service.py:68` returns
    `deferred`). Under FIFO a pre-sold order is matched correctly, but nothing shows it
    was pre-sold.
  - Change:
    - [ ] a. **FIFO (default, just works):** today's behaviour, pre-sales included. A sale
      filled from a batch completed after its invoice date gets a quiet "pre-sold" note
      on the sale and on the recall list. Nothing to action.
    - [ ] b. **Hybrid:** FIFO proposes every match. Pre-sold or unclear matches wait in a
      review list for `manual_review_days`, then confirm themselves; the owner can change
      the batch before then.
    - [ ] c. **Manual:** the owner picks the batch for each invoice line from what was in
      stock, oldest first.
    - [ ] d. In every mode, only a line that can't be filled from any stock goes to the
      unmatched queue (3.3).
  - Done when: all three options do what they say, and FIFO still needs no attention.

- [ ] **1.2 Whole bottles, with partial fills going to Library stock.** *Critical · M*
  - Evidence: nothing stops a finished lot holding 78.5 bottles, and FIFO
    (`app/core/db/repositories/inventory_repo.py:361`) will split one sold bottle across
    two lots (0.5 + 0.5).
  - Change:
    - [ ] a. Mark units as counted (bottle, can, keg, case) or measured (L, mL, g); only
      whole numbers for counted units, enforced on write.
    - [ ] b. When a final step's output doesn't divide into whole units, the remainder goes
      by default to **Library stock** for that product, in mL, keeping the batch's
      lineage. The category name is configurable.
    - [ ] c. Library stock can be mapped to a Xero item and sold (tastings, samples,
      refills), used as an input to a later batch, or written off as loss.
    - [ ] d. Matching never splits a unit.
    - [ ] e. Pack sizes are explicit in product mapping (a case of 6 is 6 bottles) and
      tested.
  - Done when: no counted stock or sale match holds a fraction, and every partial fill
    can be found in Library stock.

- [ ] **1.3 Go live with a stocktake instead of reconstructing history.** *Critical · L*
  - Evidence: the only way to get traceable history today is to rebuild past production.
    Adding a finished product by hand warns that it "creates untraceable stock and will
    require reconciliation" and demands a justification
    (`app/core/frontend/inventory/add_manual.html:211`). The product treats opening
    stock as a problem, when every new customer arrives with some.
  - Flow:
    - [ ] a. **Go-live date.** Defaults to today. Traceability starts here, and the app says
      so plainly.
    - [ ] b. **Workflows.** Pick a template for the producer type or build one. Comes first
      because finished stock belongs to a workflow's final output, using the same
      final-step list as the ABV setting (`terminal_steps` in
      `app/features/compliant/modules/nz_alcohol/workflow_rules.py`).
    - [ ] c. **Count what's on hand**, one screen with three pre-filled lists:
      - *Raw materials and packaging:* the existing manual, CSV and barcode entry, with
        quantity, supplier batch and expiry.
      - *Finished goods:* one row per final output. Add batches with the org's own batch
        ID, whole-unit quantity, ABV, and bottling date if known ("unknown" allowed).
        Library stock on the same screen.
      - *In progress:* for batches mid-process (in barrel, fermenting), choose the step
        it's at, quantity and batch ID; the batch continues from that step. **First check
        whether Core can start a batch partway through a workflow.** If not, that is the
        main engineering work in this item.
    - [ ] d. **Connect Xero.** Past invoices come in for sales reporting. Those before
      go-live are marked and left out of matching, and those after are matched from
      opening stock first. Finish with a summary such as "412 earlier invoices imported
      for reporting; tracing starts 1 Oct 2026".
    - [ ] e. **Under the hood:** opening stock is written with its own reason (a new
      opening-balance value in `InventoryQuantityWriteReason`), with no warning. Source
      Map shows it as a starting point: "Opening stock at 1 Oct 2026, earlier history
      not recorded". A recall on an opening batch lists customers from go-live onward and
      says so.
    - [ ] f. **Later:** the same screen becomes the regular **Stocktake**: count, compare
      with the system, record differences as adjustments with a reason.
  - Done when: a new producer goes live in one sitting without inventing a past date, and
    the first sale after go-live traces to an opening batch.

- [ ] **1.4 Build the recall screen for the call to NZFS.** *High · M*
  - Evidence: sales on a traced batch are listed without quantities or totals, process
    steps appear out of order, there's no export, and lots with 0 units are listed under
    "In stock" in the batch picker.
  - Change:
    - [ ] a. Header shows product, the org's batch ID, ABV and bottling date.
    - [ ] b. Summary line such as "48 sold to 8 customers · 30 on hand", with pre-sold
      sales marked.
    - [ ] c. Per customer: quantity, invoices, dates and contact details, with a warning
      where contact details are missing.
    - [ ] d. Steps listed in process order.
    - [ ] e. CSV and PDF export.
    - [ ] f. Trace can start from a supplier lot (forward) or an invoice (backward).
    - [ ] g. Sold-out lots under their own heading, not "In stock".
  - Done when: the timed mock recall is under 5 minutes.

- [ ] **1.5 Show when something happened and when it was entered.** *High · M*
  - Evidence: a step entered days later looks the same as one recorded live, which
    undermines an auditor's trust in the whole record.
  - Change: store both the time a step happened and the time it was entered; show an
    "entered later" badge when they differ by more than a day; keep an edit history on
    each record.
  - Done when: every late entry is visibly marked and every edit is traceable.

- [ ] **1.6 Show one stock number everywhere.** *High · S*
  - Evidence: a Source Map card shows one lot's quantity (`sourcemap.js`, primary lot)
    while Live Inventory shows the total for the same product.
  - Change: one shared calculation; cards show the total and the number of lots.
  - Done when: the same product shows the same figure on every screen.

- [ ] **1.7 Check stock nightly and raise problems as findings.** *M*
  - Change: for each lot, check produced − sold − wasted ± adjusted = on hand; no counted
    unit holds a fraction; no sale after go-live is unmatched without a reason. Each
    failure becomes a system finding with a fix action (see
    `docs/system-findings-module-contract.md`).
  - Done when: the checks run in CI (5.2) and nightly on live tenants.

---

## Phase 2: Compliance that closes the loop

Finish the NZ Alcohol module so compliance outputs come from production and sales
records, not from people typing figures in.

- [ ] **2.1 Build Customs excise to calculate from records.** *High · L*
  - Status: not built; the current Customs page is placeholder data. Observed problems in
    the placeholder, to avoid when building: a second ABV list separate from the
    final-step ABV (so it shows "0.0000 LAL"), botanicals offered as alcohol products to
    map, a field asking for "comma-separated … UUIDs", periods out of date order.
  - Design rules:
    - [ ] a. ABV comes from one place: the final-step `ABV (%)` field.
    - [ ] b. Only alcohol products (final outputs) are offered for mapping, never raw
      materials.
    - [ ] c. LAL produced and removed per period is calculated from bottling and sales,
      with a breakdown back to batches and invoices.
    - [ ] d. The producer checks a draft for the period and attaches the filing
      confirmation to it; periods listed in order, gaps flagged.
    - [ ] e. No field asks for raw IDs; records are linked by picking them.
    - [ ] f. Return fields checked against current NZ Customs excise guidance before
      building.
  - Done when: a producer files a period from the draft without opening a spreadsheet.

- [ ] **2.2 Track verifications from visit to next due date.** *High · M*
  - Evidence: after a passed verification the NP3 page still says "Verification ready",
    and there's nowhere to record the outcome.
  - Change: record each verification (date, verifier, outcome, corrective actions with
    owners and due dates); work out the next verification from the programme's frequency
    and show it on the dashboard.
  - Done when: the app always knows the current verification status and next due date.

- [ ] **2.3 Make evidence counts consistent and clickable.** *S*
  - Evidence: "38 evidence ready" appears next to "0 active evidence files" on the NP3
    page, and the "Guided next steps" panel is empty.
  - Change: define ready, needs evidence and overdue once; every count links to the
    records behind it; remove panels with nothing in them.

- [ ] **2.4 Finish the NZ Alcohol module on one pattern.** *L*
  - Direction: NZ Alcohol = NP1, NP2, NP3, Customs and liquor licensing. Each part plugs
    into Core like ABV does: when switched on, it adds required fields to the relevant
    steps, and producers keep their existing processes.
  - Change:
    - [ ] a. Document the Compliant → Core contract (step-scoped prompts, completion
      constraints, how steps are matched) so every part is built to it. Starting point:
      `app/features/compliant/platform/workflow_rules.py`.
    - [ ] b. Build NP1 and NP2 alongside NP3, selected by the existing food-safety
      programme setting.
    - [ ] c. Starter pack for each producer type (spirits, beer, wine, cider, mead, RTD):
      a workflow template plus the fields and checks that type needs, preconfigured.
  - Done when: switching on any part of NZ Alcohol shows the right required fields on the
    right steps, with no change to anyone's workflow.

- [ ] **2.5 Reminders for licences and people.** *S*
  - Change: reminders for licence renewals, duty manager certificates and training
    refreshers, built on the licence dates and training records that already exist.

---

## Phase 3: Sales that feed compliance

Sales matter here because they finish the trace. Make them readable and complete.

- [ ] **3.1 Total sales per product.** *High · S*
  - Evidence: CRM Top Products lists one product across seven or more rows because Xero
    item codes and descriptions vary, typos included.
  - Change: group by the mapped product, with a row that expands to show Xero codes;
    unmapped lines go to a queue to be mapped.

- [ ] **3.2 Make sales readable in the activity log.** *High · S*
  - Evidence: a sale is logged as "Quantity adjusted 36.0000 → 30.0000 units"
    (`app/core/backend/backend.py`, `Quantity adjusted` formatter), and one sync writes
    hundreds of these, flooding the dashboard's "Logged events".
  - Change: log sales as "Sold 6 × Wildflower (batch 044), INV-0386, Eastbourne Sports
    Club"; show each sync as one entry with a count that expands.

- [ ] **3.3 A queue for unmatched sales.** *S*
  - Change: invoice lines with no product mapping, or that can't be filled from any stock
    (1.1d), become tasks with a direct fix.

- [ ] **3.4 Customer records ready for a recall.** *S*
  - Change: show how many customers have a contact phone and email on record and prompt
    for missing ones. A recall is only as good as its contact list.

- [ ] **3.5 Hide empty sales metrics.** *S*
  - Evidence: revenue-target tiles on the dashboard and CRM read "n/a" until a target is
    set.
  - Change: hide them, or offer a one-click setup.

---

## Phase 4: An interface that shows the work

Start after Phase 1 so redesigned screens show correct numbers; 4.1 and 4.7 can start at
any time.

- [ ] **4.1 Put data at the top of every page.** *High · S*
  - Evidence: every Core and CRM page (dashboard, product workflows, active batches, live
    inventory, source map, CRM) opens with a decorative three-node illustration and a
    centred description, about 400 px on desktop. On a phone the dashboard's whole first
    screen is decoration and explanation.
  - Change: headers become the title, the main action and key numbers. Remove copy that
    describes the app's structure: "Business control tower", "See the whole business. Act
    in the right workspace.", "Dashboard gives you the signal…", "DO THE WORK / Choose a
    workspace", "CONTEXT, NOT A TO-DO LIST", "Use trends to understand the picture…".

- [ ] **4.2 One design system.** *High · L*
  - Evidence: three distinct visual styles.
    - Core: illustration header, blue pill tabs, yellow back button, oversized "Trace"
      button with icon above.
    - Compliance: dark teal gradient banner, underlined breadcrumbs, grey tabs.
    - CRM: its own blue tabs and widget cards.
  - Change: shared tokens and components (page header, tabs, buttons, breadcrumbs, cards,
    tables, status badges) used by all three; migrate each area as it's touched.

- [ ] **4.3 Use words and numbers producers use.** *S*
  - [ ] a. Rename Core → **Production**, Compliant → **Compliance** (nav already says
    Compliance; pages and cards say Compliant), CRM → **Sales**.
  - [ ] b. Durations in days ("22 days"), not hours ("Started 535h 54m ago").
  - [ ] c. No trailing zeros ("30", not "30.0000"), including activity entries.
  - [ ] d. Fix "5 active batchs".

- [ ] **4.4 One route to each job.** *S*
  - [ ] a. "Trace" button and Source Map lead to the same place; keep one.
  - [ ] b. "Add to inventory" and "+ Receive stock" do the same job; keep one.
  - [ ] c. Pages have three back controls (top-bar arrow, "← Back to …" link, sidebar);
    keep one.
  - [ ] d. Old URLs redirect without explanation: `/compliant/nz-alcohol/np3-audit` →
    food-safety, `/compliant/nz-alcohol/evidence` → customs, `/core/tasks` →
    `/core?tab=tasks`. Redirect on purpose or remove.

- [ ] **4.5 Make the dashboard today's work list.** *High · M*
  - Evidence: a "−100% batch completion vs last week" tile computed against a zero base;
    a sign-in ("Logged in with password from 127.0.0.1") shown as the day's featured
    event; several "n/a" tiles; a "System Issues Detected" banner on Core pages with no
    detail or link.
  - Change: show what needs attention, batches waiting on me, next compliance dates and
    stock alerts. Drop metrics with no meaningful base; filter sign-ins and sync noise out
    of featured activity; banners always name the issue and link to it.

- [ ] **4.6 A phone mode for the production floor.** *M*
  - Change: recording a step, scanning a barcode and attaching photo evidence each work
    one-handed at 390 px, with tests at that width. (The bottom nav on phone is already
    right; keep it.)

- [ ] **4.7 Fix the visual bugs.** *S*
  - [ ] a. Sidebar background stops at viewport height on long pages (white below it).
  - [ ] b. The floating blue menu toggle overlaps the sidebar edge.
  - [ ] c. CRM widget control icons render as missing-glyph boxes.
  - [ ] d. `/settings` requests a resource that returns 404.
  - [ ] e. Forms asking for raw UUIDs (Customs "Core source references") — pick records
    instead.
  - [ ] f. The Compliance workspaces page is one card on an empty screen; fold it into
    NZ Alcohol or give it content.

---

## Phase 5: Engineering health

Runs alongside the other phases, roughly a fifth of each. No big rewrite.

- [ ] **5.1 Split the two largest files as they're touched.** *M*
  - Evidence: `app/core/backend/backend.py` is 6,784 lines and
    `app/core/frontend/js/create-process-modal.js` is 6,895; both grow with every feature.
  - Change: when a change touches one of them, move that feature's code into its own
    module.

- [ ] **5.2 Run the stock checks as tests.** *S*
  - Change: the 1.7 checks as tests, plus a mock-recall scenario in the end-to-end suite.

- [ ] **5.3 Keep tooling in proportion.** *S*
  - Evidence: 40 report categories under `.agents/reports/`, plus several watchers and
    sweeps, for one customer.
  - Change: keep the tools that change decisions; retire the rest.

---

## Phase 6: Market it as what it is

Starts once Phases 1 and 2 hold up with a second producer.

- [ ] **6.1 A landing page for NZ craft alcohol.** *S*
  - Change: replace the generic "manufacturing operations" copy with what a producer
    gets: a real recall trace, an NP3 evidence pack and an excise draft.

- [ ] **6.2 Pilot a second producer of a different type.** *High · M*
  - Change: onboard a brewery or winery through the go-live stocktake (1.3); measure time
    to first traced sale; record every point where they needed help.
  - Done when: they reach a traced sale in one sitting, and their questions become the
    next items in this plan.

- [ ] **6.3 Price by what's included.** *S*
  - Change: plans built from Production, a compliance pack for the producer's type, and
    the Xero sales link, in line with the existing feature subscriptions.

---

## Order

1. **Phase 0.** Require 2FA and get `main` green; the database split is planned for
   go-live.
2. **1.2 then 1.3.** Whole bottles and Library stock, then the go-live stocktake. They
   decide whether a new producer can start cleanly and whether stock can be trusted from
   day one. Start 1.3 by checking whether Core can start a batch partway through a
   workflow; that sets its size.
3. **1.1 and 1.4.** Matching modes and the recall screen give owners control and turn the
   trace into something to hand to NZFS.
4. **Phase 3** alongside the end of Phase 1.
5. **Phase 2** as NZ Alcohol parts are finished; Customs depends on 1.2 and final-step ABV.
6. **Phase 4** on the corrected data; 4.1 and 4.7 can go first at any time.
7. **Phase 6** once a second producer works. Generalise from two real producers, not one.
