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
| Architecture | Follow the agreed feature-slicing plan (`.agents/plans/feature-slicing-plan.md`): slices under `app/features/<slice>/`, moved through the `register_routes(core_bp)` seam with no URL changes. Don't invent another split (5.1). |
| Excise | Built around what Customs taxes: alcohol **removed** from the licensed area, per lodgement period, with sales as the main source of removals (2.1). Stocktakes reconcile counted stock to lodged duty (2.6). |
| Access | Staff roles are permission sets enforced on the server, default deny; the UI only hides what the server already refuses (0.4). |

## What excellent means

The finish line for this plan. Each outcome can be tested.

| Outcome | How we know |
| --- | --- |
| **Recall in minutes.** From any finished batch or supplier lot to a customer list with quantities and contacts. | A timed mock recall takes under 5 minutes and ends in an export, with no manual lookups. |
| **Stock you can trust.** Finished goods in the system match the shelf. | Stocktake variance on finished goods is under 1%, and every screen shows the same number. |
| **Excise from records.** Litres of alcohol (LAL) per period come from recorded removals and sales. | The producer checks a draft and lodges it, with no spreadsheet; a Customs stocktake reconciles counted stock to lodged duty. |
| **Right people, right data.** Staff see what their role needs. | A production user gets 403 from every sales endpoint and sees no revenue anywhere. |
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
- Admins can sign in without 2FA, and there are only two roles (admin and member): every
  member sees revenue, customers and invoices.

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

- [x] **0.2 Require 2FA for owners and admins.** *Critical · S* (!322)
  - Evidence: the admin of a live tenant signs in with a password alone. The
    `/auth/verify-2fa` rate-limit finding (F6 in
    `.agents/reports/auth/security-audit.md`) is still open.
  - Change: an org policy that forces TOTP enrolment for admin roles at next sign-in;
    rate-limit 2FA verification.
  - Done when: no admin session can start without a second factor.

- [ ] **0.3 Keep main green.** *S*
  - [x] a. Ruff check and ruff format pass on `main`, and the CI gate is check-only so it
    can fail (!320).
  - [x] b. ~~Remove dead `app/features/workflow_engine/` and `dilution_calculator/`
    folders.~~ Not a repo issue: neither is tracked in git; they are untracked leftovers
    in one local checkout (delete locally if `test_ac9_package_and_factory_wiring_removed`
    fails).
  - [x] c. (!323) Fix `CLAUDE.md` drift: test DB password (now `$POSTGRES_PASSWORD_TEST`), test
    counts, DAG code location (`CLAUDE.md` says `app/features/workflow_engine/`; it's
    `app/core/backend/dagtraversal.py`).
  - [ ] d. Run end-to-end tests in merge request pipelines (currently skipped by
    relevant-test selection).
  - [ ] e. Block merges while `main` is red.
  - Done when: a fresh clone passes lint and every test on the first run.

- [x] **0.4 Team roles and permissions.** *Critical · L*
  - Evidence: two roles, `UserRole.ADMIN` and `MEMBER` (`app/core/db/models/user.py:14`).
    11 routes check a role with `requires_role`, all admin-only. No CRM or sales route
    checks one, so every member sees revenue, customers and invoices. `/org/users` can
    add and remove users (admin only), with no role choice beyond admin or member.
  - Design:
    - [x] a. (!333) **Permissions, then roles.** Named capabilities per area, e.g.
      `production.view`, `production.record`, `production.design`, `inventory.adjust`,
      `sales.view`, `sales.revenue` (money figures), `sales.manage` (Xero, mappings),
      `compliance.view`, `compliance.sign`, `customs.lodge`, `users.manage`,
      `settings.manage`.
    - [x] b. (!333) **Built-in roles as permission sets:** Owner (everything; the last owner can't
      be removed), Admin, Production (record steps and stock; no money), Compliance
      (compliance plus read-only production), Sales (customers, sales and finished stock
      on hand; no recipes or process design), Auditor (read-only and time-limited, for a
      verifier visit). On migration, ADMIN becomes Owner/Admin and MEMBER becomes a
      "Staff" role with today's access, so nothing changes for current users.
    - [x] c. (!419) **Custom roles later:** clone a built-in role and tick permissions.
    - [x] d. (!333) **Server-side, default deny.** Every route declares
      `@requires_permission(...)`. A test walks Flask's URL map and fails if any route
      lacks a declaration; public routes are an explicit allow-list. Nav and buttons hide
      what a role can't use, but the server is the source of truth.
    - [x] e. (!333) **Aggregates respect permissions.** Dashboard and other composition endpoints
      leave out sections a user can't see (e.g. revenue tiles) instead of sending them
      for the browser to hide.
    - [x] f. (!333) **Permission matrix test:** for every built-in role and route, the expected
      200 or 403, generated from one table.
    - [x] g. (!333) **User management for owners and admins:** invite by email (2FA enrolment
      forced per 0.2), change role, deactivate (keeps history, blocks sign-in), resend
      invite. Every change goes to the audit log.
  - Fits the slicing plan: permissions are platform code (`app/core/security/permissions.py`
    today), and this is the authorisation change that plan already anticipates for
    enterprise customer logins.
  - Done when: a Production user gets 403 from every sales endpoint and sees no revenue
    anywhere, a Sales user can't open process design, and the route-coverage test passes.
  - As built (!333), where it differs from the design above:
    - One policy table (`app/core/security/access_policy.py`, `POLICY`) instead of a
      decorator on every route. Same default deny and the same URL-map coverage test,
      but it keeps the permission model out of the files the 5.1 carve is moving.
    - `sales.revenue` folded into `sales.view`: no role needs customers without money.
      `compliance.sign` is `compliance.record`; `customs.lodge` waits for 2.1.
    - Owner is Admin plus the last-admin rule; no separate Owner role yet.
    - "Invite by email" is an invite **link** the admin sends (7 days, one use, only a
      hash stored): the app has no email sender yet. Swap in email when one exists.
    - c. (!419): People → Custom roles. Clone any built-in role except Admin, name it,
      tick permissions; changing a role changes it for everyone who holds it, and a role
      in use can't be deleted. Custom roles can grant anything Staff can; users.manage,
      settings.manage and compliance.manage stay with Admins (those routes also check the
      Admin role). A person with a custom role carries its base role, so time limits
      (Auditor-based roles) and role checks behave as for that role.

---

## Phase 1: Traceability you can stake a recall on

The core of the product. It should just work by default, give owners control when they
want it, and never produce a recall list that can't be trusted.

- [x] **1.1 Let owners choose how sales are matched to batches.** *High · M* (!338)
  - Evidence: Sales configuration offers FIFO, manual and hybrid matching plus "manual
    review days", but only FIFO is implemented. Choosing manual or hybrid silently stops
    all matching (`app/features/crm/services/sales_traceability_service.py:68` returns
    `deferred`). Under FIFO a pre-sold order is matched correctly, but nothing shows it
    was pre-sold.
  - Change:
    - [x] a. **FIFO (default, just works):** today's behaviour, pre-sales included. A sale
      filled from a batch completed after its invoice date gets a quiet "pre-sold" note
      on the sale and on the recall list. Nothing to action.
    - [x] b. **Hybrid:** FIFO proposes every match. Pre-sold or unclear matches wait in a
      review list for `manual_review_days`, then confirm themselves; the owner can change
      the batch before then.
    - [x] c. **Manual:** the owner picks the batch for each invoice line from what was in
      stock, oldest first.
    - [x] d. In every mode, only a line that can't be filled from any stock goes to the
      unmatched queue (3.3).
  - Done when: all three options do what they say, and FIFO still needs no attention.
  - As built (!338): allocations carry `status` (confirmed / pending_review), `presold`
    and `review_due_at` (migration `sales_matching_modes_001`). Hybrid sends pre-sold
    matches and non-exact ("contains"/"alias") mappings to review; due reviews confirm on
    the next matching run. Manual mode lists mapped lines with no batch and takes the
    owner's picks, which must add up to the line (pack size included) and come from
    batches of the mapped product. The same picker changes the batch on any automatic
    match (stock goes back to the old batch). Page: CRM → Batch matching (`/crm/matching`).
    Source Map marks sales "pre-sold" / "awaiting review". For d, lines FIFO can't fill
    still count as `insufficient_stock` in the summary; their queue is 3.3.

- [x] **1.2 Whole bottles, with partial fills going to Library stock.** *Critical · M* (!336)
  - Evidence: nothing stops a finished lot holding 78.5 bottles, and FIFO
    (`app/core/db/repositories/inventory_repo.py:361`) will split one sold bottle across
    two lots (0.5 + 0.5).
  - Change:
    - [x] a. Mark units as counted (bottle, can, keg, case) or measured (L, mL, g); only
      whole numbers for counted units, enforced on write.
    - [x] b. When a final step's output doesn't divide into whole units, the remainder goes
      by default to **Library stock** for that product, in mL, keeping the batch's
      lineage. The category name is configurable.
    - [x] c. Library stock can be mapped to a Xero item and sold (tastings, samples,
      refills), used as an input to a later batch, or written off as loss.
    - [x] d. Matching never splits a unit.
    - [x] e. Pack sizes are explicit in product mapping (a case of 6 is 6 bottles) and
      tested.
  - Done when: no counted stock or sale match holds a fraction, and every partial fill
    can be found in Library stock.
  - As built (!336):
    - Counted units are `units`, `pcs`, `pieces`, `boxes`, `pallets`, `containers` and the
      new `bottles`, `cans`, `kegs`, `cases` (`app/core/utils/unit_conversion.py`). The
      rule is enforced in `InventoryRepository` on every write, and on the **change**, not
      the stored total: a lot created before this rule can still sell whole units down to
      its fraction, which then waits for a stocktake correction.
    - FIFO only takes whole units from a lot, so a half-bottle remainder is never split
      across batches; a fractional sale quantity is left unmatched and counted as
      `fractional_quantity` in the reconcile summary.
    - Step screens (modal and full-page) take whole numbers for counted outputs and have
      a "Part-filled, in mL" box; the server adds "<product> - Library stock" (mL, final
      product, same batch lineage). The name after the dash is the workflow setting
      `library_stock_name`.
    - Selling, re-using or writing off Library stock uses what exists: it is a final
      product, so it can be mapped to a Xero item, picked as a step input, or recorded as
      wastage.
    - Pack size is `units_per_line` on a product mapping (migration
      `product_mapping_pack_size_001`), shown and editable in CRM configuration.

- [x] **1.3 Go live with a stocktake instead of reconstructing history.** *Critical · L* (!337)
  - Evidence: the only way to get traceable history was to rebuild past production.
    Adding a finished product by hand warns that it "creates untraceable stock and will
    require reconciliation" (`app/core/frontend/inventory/add_manual.html:211`), so the
    product treated opening stock as a problem, when every new customer arrives with some.
  - Approach (Claude's recommendation after the founder asked "why not just start new
    batches?"; built in the recommended order, so revisit if the founder disagrees):
    producers **record new batches as normal** from go-live, with no history to rebuild,
    and count only what the system can't know. Starting a batch partway through a
    workflow was dropped as unnecessary.
  - [x] a. **Go-live date** (`organisations.go_live_date`, admin only). Tracing starts
    there, and the page says so.
  - [x] b. **Workflows** step: shows how many exist and links to templates. Each
    workflow's final output becomes a row in the count.
  - [x] c. **Count what's on hand** at `/core/go-live`: finished goods per final output
    (batch ID, whole-unit quantity, bottling date, ABV, Library stock in mL); what's in
    tank or barrel as opening work in progress, which a later step picks as an input;
    raw materials through the existing add-stock screens. All rows or none.
  - [x] d. **Xero boundary:** sales dated before go-live stay in sales reporting but are
    not matched to batches (`before_go_live` in the reconcile summary; earlier matches are
    undone). Later sales take opening batches first.
  - [x] e. **Under the hood:** opening stock is written with the `OPENING_BALANCE`
    reason, `add_method: opening_stock`, and `extra_data.opening_stock` / `opening_as_of`;
    it is not a traceability gap. Source Map notes "Opening stock counted at go-live on
    …; history before then wasn't recorded".
  - [ ] f. **Later:** the same count becomes the regular stocktake. Tracked in 2.6c.
  - Also: a dashboard prompt ("Setting up? Go live with a stocktake") until the date is
    set, and the manual-add warning points to the go-live stocktake.
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

- [x] **2.1 Excise per period from linked sales and removals.** *High · L* (!MR)
  - Status: not built; the current Customs page is placeholder data. Avoid what the
    placeholder does: a second ABV list separate from the final-step ABV (so it shows
    "0.0000 LAL"), botanicals offered as alcohol products, fields asking for
    "comma-separated … UUIDs", and periods out of date order.
  - Customs rules this must follow (checked 25 Sep 2026; see Sources):
    - Duty is due on alcohol **removed from the Customs-controlled area** (the licensed
      manufacturing area), not when it's invoiced. Monthly payment is due by the last
      working day of the month after removal.
    - Entries are monthly by default. Six-monthly (annual duty up to $100,000) or
      twelve-monthly (up to $50,000) needs Customs approval. A monthly entry is due by the
      15th working day of the following month.
    - A **nil return** is required for a period with no removals.
    - Records are kept for at least 7 years, in New Zealand or with approved cloud storage.
  - Change:
    - [x] a. **Excise products** are final-step outputs flagged as alcohol products (the ABV
      rule already identifies them). Each has a pack volume (e.g. 700 mL), the ABV
      recorded on its final step, and a Customs tariff item. Only these are offered for
      mapping, never raw materials.
    - [x] b. **Removals, not only sales.** Each period's lines come from stock leaving the
      licensed area: Xero sales dispatched straight from it (the default, and for many
      producers all of it), plus stock moved to an outside location (a sales rep, an
      event, samples). A later sale from a rep's stock links to the original removal and
      isn't counted twice. This needs stock locations in inventory; check what Core has
      today.
    - [x] c. **Lines calculated automatically for each period**, grouped by product and
      tariff item: units × volume × ABV = LAL, then LAL × rate = duty. Each line drills
      down to its batches and invoices or movements. The rate table is editable and
      dated, because rates change every 1 July.
    - [x] d. **Lodgement period** is configurable (monthly, six-monthly, twelve-monthly) to
      match the org's Customs approval.
    - [x] e. **Lodgement reminder:** at the start of the month after each period, a system
      alert such as "Excise entry for September 2026 due 21 Oct: 412.6 LAL, $x" (or
      "nil return due"). It stays until someone with `customs.lodge` confirms it's
      lodged, with the date and optionally the entry number or confirmation. An overdue
      entry escalates. Confirming locks that period's figures as a snapshot.
    - [x] f. **Changes after lodging** never rewrite a lodged period. A removal recorded
      late, or a correction, is carried into the next open period's draft as an
      adjustment noting the period it belongs to.
    - [x] g. Check entry fields and the rate table against current Customs guidance before
      building. This plan is not tax advice.
  - Done when: each period is lodged from the draft (or as a nil return) and confirmed in
    the app, and nobody opens a spreadsheet.
  - As built (!409): Customs page → Excise. Stock locations are a Core concept
    (`stock_locations`, `stock_transfers`, `inventory_items.location_id`; no location = the
    main licensed area), with a "move stock" action that splits a lot and records the
    direction (out = removal, in = possible credit, never auto-claimed). Batch uniqueness
    is now per location. Rates are dated per tariff item. Lodged periods are locked
    snapshots; late removals carry into the next open period once. The reminder is a
    system finding (`compliant.nz_alcohol.excise`) and only starts from the
    "remind me from" date. g: rules checked against customs.govt.nz on 25 Sep 2026
    (Sources); public holidays aren't counted in the due date, and the page says so.

- [x] **2.2 Track verifications from visit to next due date.** *High · M*
  - Evidence: after a passed verification the NP3 page still says "Verification ready",
    and there's nowhere to record the outcome.
  - Change: record each verification (date, verifier, outcome, corrective actions with
    owners and due dates); work out the next verification from the programme's frequency
    and show it on the dashboard.
  - Done when: the app always knows the current verification status and next due date.
  - As built (!413): NP3 page (and the NP1/NP2 page) → Verification. Each visit records
    date, verifier, agency, report reference, outcome (and, when unacceptable, whether the
    business is willing and able to comply) and corrective actions with owners and due
    dates. The next date follows MPI's national-programme frequency steps (Food
    Regulations 94: 3 months to 3 years, or none): the app suggests the step the rules
    give and records what the verifier actually set, including a date from their report.
    Before any verification, the registration date gives the initial due date (6 weeks
    new; 1 year NP1/NP2, 6 months NP3 existing). Alerts 60 days before the due date and a
    week before each action; the dashboard module card carries the next date as a
    milestone (rendered by !412). Recording a visit clears the booked-visit fields.

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

- [x] **2.5 Liquor licensing (basic).** *M*
  - Scope: Sale and Supply of Alcohol Act 2012 obligations for producers who sell (cellar
    door, online, events). The first version is a register with reminders and checks, on
    the existing NP3 patterns (checks, evidence, review reminders, training register).
    Confirm each obligation against the Act, its regulations and the org's own licence
    conditions before building; the in-repo licence dossier
    (`.claude/agents/outputs/whistlebird-licence-dossier.html`) is a worked example of
    one producer's process.
  - Change:
    - [x] a. **Licence register:** type (on, off, club, special), endorsements (e.g. s 40
      remote seller), number, issuing DLC, issue and expiry dates, conditions (sale and
      delivery hours), premises. Reminders far enough ahead of expiry to lodge the renewal
      in time (confirm the lead time with the DLC), and for annual fees.
    - [x] b. **Special licences** for events: date, venue, conditions, manager on duty.
    - [x] c. **Manager register:** certified managers with certificate number, issuing
      DLC, expiry and renewal reminders.
    - [x] d. **Recurring checks with evidence:**
      - the licence and the manager on duty are displayed where required;
      - host responsibility or social responsibility policy, and the alcohol management
        plan, are current;
      - staff training (reuse the NP3 training register);
      - for remote sellers: licence details shown on the website, and age verification
        and delivery conditions followed.
    - [x] e. **Incident and refusal log:** ID refusals, intoxication refusals, incidents,
      controlled purchase operations. This is what an inspector asks to see.
    - [ ] f. **Links to Core and Sales where cheap:** e.g. flag a delivery recorded outside
      licensed delivery hours, if order times are available.
  - Done when: licence and certificate dates never lapse unnoticed, and an inspector's
    request for policies, training and incident records is one download.
  - As built (!414): NZ Alcohol → Licensing (shown when a licence type is set in
    Configuration). Licence register with endorsements, DLC, dates, sale and delivery hours
    and conditions; the renew-by date is 20 working days before expiry counted as s 5 of
    the Act defines working days (weekends, national holidays including Matariki,
    Mondayisation, 20 Dec-15 Jan), reminded from 60 days before it, then "late: file with a
    waiver", then expired. Annual fee reminders 30 days ahead. Special licences with the
    event, dates and manager on duty. Managers' certificates reminded 60 days before expiry
    until renewal is lodged. The liquor-licence framework gains checks for displays, the
    host/social responsibility policy and AMP, and remote-seller website duties; licence
    scope, renewal and certified managers are proven by the register everywhere
    (overview included). Incident and refusal log. "Download inspector pack" is one PDF:
    licences, managers, checks with evidence, staff training (the shared competency
    register) and the log.
  - f is not built: Xero invoices carry a date but no order time, so a delivery outside
    licensed hours can't be detected yet. Revisit if an order source with times is added.

- [x] **2.6 Customs stocktake: count reality and reconcile it to lodged duty.** *High · L*
  - Why: at a Customs audit the officer asks for sales data and for where every product is
    right now (e.g. "VAT57 and VAT59 in tank, 43 bottles of Solstice on the shelf"), then
    counts the shelf to check. Customs requires stocktakes at least once a year.
    Discrepancies must be investigated and resolved, and a confirmed unexplained loss is
    dutiable and must be reported to Customs.
  - Change:
    - [x] a. **Stock position:** where everything is, by location and batch. Bulk stock in
      tanks in litres, ABV and LAL; packaged goods by product and batch; for the licensed
      area and each outside location. Exportable for a visit together with the lodged
      periods.
    - [x] b. **Stocktake schedule:** configurable frequency (monthly, quarterly,
      six-monthly or annual; Customs' minimum is annual) with a reminder, plus an
      on-demand "Customs is here" count.
    - [x] c. **Count screen** (reuses the stocktake from 1.3f): the expected quantity for
      each line; type the count or scan; variance per line in units and LAL. Works on a
      phone during the visit.
    - [x] d. **Reconciliation per product:** opening + produced − removed − approved losses
      = expected closing, tied back to the lodged entries.
    - [x] e. **Resolve variances** as below. Nothing blocks work; unresolved variances stay
      on the alert list with their LAL and potential duty.
  - Resolving a variance takes one tap, with the most likely reason suggested first. A
    variance can be split across reasons (e.g. 4 with a rep, 3 broken).

    | Counted less (expected 50, counted 43) | What the system does |
    | --- | --- |
    | Found elsewhere (rep, event, other store) | Move the 7 to that location. If it's outside the licensed area, that's a removal in the month it left: added to that period, or carried into the current draft if that period is already lodged. |
    | Removed but not recorded (tasting, samples, gift, missed sale) | Record the removal. Dutiable. |
    | Broken, damaged or faulty | Record the loss with a photo or note, and offer remission: licensees with pre-authorisation claim it in the entry; others use form NZCS 277. Not dutiable once remitted. |
    | Still looking | Hold it open as an investigation (default 14 days) with a reminder; the count can be redone. |
    | Can't explain | Confirmed loss: 7 bottles (x LAL, $y) added to the current draft as an unaccounted loss, with a prompt to advise Customs. |

    | Counted more (expected 50, counted 55) | What the system does |
    | --- | --- |
    | Came back from a rep or event | Move it back into the licensed area. If duty was paid when it left, flag a possible credit to raise with Customs (never claimed automatically). |
    | A removal was recorded that didn't happen | Reverse it. If its period is lodged, flag the overpaid duty as a correction to raise with Customs. |
    | Production was under-recorded | Correct the bottling record with a reason; lineage is kept. |
    | Can't explain | Accept as an adjustment with a note, flagged for review. |

    Customs' published guidance doesn't cover surpluses. Confirm how Customs treats
    surpluses, and duty-paid stock coming back into the licensed area, before building.
  - As built (!410): Core → Stocktake (`/core/stocktake`, `stocktake_bp`). The stock
    position lists finished goods and work in progress by place and batch with LAL, and
    downloads as CSV together with the lodged entries. The schedule (monthly, quarterly,
    six-monthly, annual; default annual, anchored on the last stocktake or the go-live
    date) raises a reminder 14 days before it's due; "Customs is here" starts an
    on-demand count. Each line's expected quantity is taken when it's counted, so sales
    during a count aren't variances; bulk liquid matches within a tolerance (default
    0.5%), bottles never do. Every difference is resolved into ordinary dated stock
    operations as in the tables above (moves, wastage, adjustments), so excise follows
    on its own; system places "Removed without a sale record" and "Unaccounted loss"
    (outside the licensed area) make those dutiable removals. Unresolved and
    investigating lines stay on the alert list with LAL and duty. Core reaches LAL and
    duty only through a generic stock-measure seam in the Compliant platform, so Core
    names no industry. Surpluses are recorded and flagged to raise with Customs, never
    credited automatically, pending Customs' confirmation of how they treat them.
  - Principles: every resolution is a dated adjustment recording who and why, never an
    overwrite. Bulk liquid can have a configurable measurement tolerance (e.g. ±0.5% of
    volume); packaged units have none.
  - Done when: a Customs officer's count can be recorded during the visit, and every
    variance ends in an explained adjustment that ties back to a lodged period.

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

- [x] **4.2 One design system.** *High · L* (!396)
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
  - [x] a. "Trace" and Source Map links use the single `/core/sourcemap` page
    (`core.sourcemap`). (!391)
  - [ ] b. "Add to inventory" and "+ Receive stock" do the same job; keep one.
  - [ ] c. Pages have three back controls (top-bar arrow, "← Back to …" link, sidebar);
    keep one.
  - [x] d. Old URLs redirect to their intended destinations in
    `app/features/compliant/routes/page_routes.py` and `app/core/backend/backend.py`
    (!390).

- [ ] **4.5 Make the dashboard today's work list.** *High · M*
  - Evidence: a "−100% batch completion vs last week" tile computed against a zero base;
    a sign-in ("Logged in with password from 127.0.0.1") shown as the day's featured
    event; several "n/a" tiles; a "System Issues Detected" banner on Core pages with no
    detail or link.
  - Change: show what needs attention, batches waiting on me, next compliance dates and
    stock alerts. Drop metrics with no meaningful base; filter sign-ins and sync noise out
    of featured activity; banners always name the issue and link to it.

- [x] **4.6 A phone mode for the production floor.** *M* (!397)
  - Change: recording a step, scanning a barcode and attaching photo evidence each work
    one-handed at 390 px, with tests at that width. (The bottom nav on phone is already
    right; keep it.)

- [ ] **4.7 Fix the visual bugs.** *S*
  - [x] a. Sidebar background stops at viewport height on long pages (white below it). (!327)
  - [x] b. The floating blue menu toggle overlaps the sidebar edge. (!327)
  - [x] c. CRM widget control icons render as missing-glyph boxes. (!328)
- [x] d. `/settings` requests a resource that returns 404. (!389)
  - [x] e. Forms asking for raw UUIDs (Customs "Core source references") — pick records
    instead. (!330)
  - [ ] f. The Compliance workspaces page is one card on an empty screen; fold it into
    NZ Alcohol or give it content.

---

## Phase 5: Engineering health

Runs alongside the other phases, roughly a fifth of each. The architecture direction is
already decided in `.agents/plans/feature-slicing-plan.md` (agreed 2026-07-27): 15 slices
plus platform. Code moves into `app/features/<slice>/` through the
`register_routes(core_bp)` seam with no URL changes, then gets real blueprints, then
models, then frontend through an asset registry. Follow that plan; don't invent another
split.

- [ ] **5.1 Resume the feature-slicing carve.** *L, as many small MRs*
  - Evidence: the carve started 2026-07-28, when demo-data moved out, `backend.py` was
    5,763 lines and the feature index was verified. No further slice has moved since.
    `backend.py` is now 6,784 lines, and `.agents/feature-index.md` still says "Last
    verified: 2026-07-28". `create-process-modal.js` is 6,895 lines.
  - Change:
    - [x] a. Refresh `.agents/feature-index.md` against today's code (backend line ranges
      have shifted by about 1,000 lines). Add the staleness check the slicing plan left
      open (§6 item 1): a script that checks every `routes:` entry against the live URL
      map. (!326)
    - [x] b. **Stop the growth first:** a CI ratchet that fails if
      `app/core/backend/backend.py` gets longer. New routes go in the owning slice. (!321)
    - [ ] c. Carve in the slicing plan's Phase 1 order: reconciliation → wastage →
      compliance-checks → traceability → activity-log → dashboard, then inventory →
      process-design → execution. One slice per MR, pure moves with no behaviour change,
      with the e2e suite as the safety net.
      - [x] Reconciliation pure move. (!331)
    - [ ] d. **Carve before you change:** when an item in this plan needs substantial work
      in a slice that still lives in `backend.py`, carve that slice first in its own MR,
      then make the change in its new home. Likely pulls: 1.2, 1.3, 1.6 and 2.6 →
      inventory; 1.4 → traceability; 1.5 → execution; 4.5 → dashboard; 3.2 →
      activity-log.
    - [ ] e. **New work starts in its slice:** roles and permissions (0.4) in
      platform/identity; Customs (2.1, 2.6) and licensing (2.5) in
      `app/features/compliant/modules/nz_alcohol/`; matching modes (1.1) in crm.
    - [ ] f. **Frontend after backend:** the asset registry (slicing plan §3, option 1)
      before any JS moves; split `create-process-modal.js` internally as part of
      process-design.
    - [ ] g. Rename `app/core/` → `app/platform/` last, once the carve has emptied
      `app/core/backend/` (slicing plan decision 3, open item 4).
  - Done when: `backend.py` holds only shell code, and every slice in the feature index
    points at its own directory.

- [ ] **5.2 Run the stock checks as tests.** *S*
  - Change: the 1.7 checks as tests, plus a mock-recall scenario and a Customs stocktake
    scenario (2.6) in the end-to-end suite.

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

## Phase 7: More than one site, making for others, and planning the work

- [ ] **7.2 Contract manufacturing with a customer portal.** *High · L+*
  - Why: many producers make for others (a gin for a bar group, a beer for a brand
    owner). Customers want to see where their order is without emailing or phoning. A
    live, trustworthy view builds the relationship and cuts admin on both sides.
  - Evidence (28 Sep 2026): no customer order in production, no stock owned by someone
    else, no external user; every user belongs to one org with a staff role.
  - Change:
    - [ ] a. **Contract customers and orders.** A contract customer (linked to the CRM
      contact where there is one) and orders: product, quantity, spec or recipe version,
      due date, status. Each order links to the batches (executions) that make it, and
      the scheduler (7.3) plans them.
      - [x] Staff customer/order/line/batch foundation (!426): per-line specification,
        stored recipe version and output reference, linked batch counts, and per-line
        materials/per-order duty declarations. Scheduler integration remains 7.3;
        materials ownership and excise behaviour remain 7.2b/c.
    - [ ] b. **Materials either way.** Per order line: supplied by the customer
      (free-issue: received as lots owned by the customer, kept out of the producer's own
      stock value, usable only for that customer's orders), by the producer, or a mix.
      Lineage stays intact either way, so a recall works across both.
      - [x] Trusted material-scope prerequisite (!437): locked execution/order resolver,
        raw-material owner preflight and consistent batch-link lock ordering, with a
        concurrent-assignment regression. Owner schema/DB guards, production hook,
        receipts, transfer conservation and producer valuation/sales exclusions remain
        open; customer receipts are not enabled by this prerequisite.
    - [ ] c. **Duty either way.** Per order: who is liable for excise (the producer as
      licensee, the customer as licensee, or goods leaving underbond to the customer's
      CCA, 7.1e). The excise module (2.1) counts or skips the removal accordingly and the
      order shows who pays.
    - [ ] d. **Progress without typing it twice.** Milestones (materials received,
      scheduled, in production, QC passed, packed, ready, dispatched) come from the
      batch's own steps and stock movements. The producer chooses which steps show and
      what they're called.
    - [ ] e. **The portal.** Customer users sign in (0.5 Google sign-in works here too) to
      a slim, branded portal of **their** current and past orders only. For each order,
      the ten things that matter most to a brand owner:
      1. **Where it's up to:** the current stage and step, with progress through the
         whole run.
      2. **When it'll be ready:** the planned and forecast ready date from the scheduler
         (7.3), and why it moved if it did.
      3. **How much:** ordered, in production, finished, dispatched and still to come.
      4. **Their batches:** batch IDs and bottling dates made for the order.
      5. **Quality:** actual ABV against spec, QC checks passed, and shared lab
         results or certificates of analysis.
      6. **Their materials:** customer-supplied materials received, used and left.
      7. **Yield:** planned against actual output and losses, if the producer shares it.
      8. **Delivery:** dispatch date, carrier, consignment note, and duty status
         (duty-paid or underbond to their licence).
      9. **Documents:** label proofs, the trace for their batches (recall-ready), and
         compliance certificates.
      10. **What's waiting on them:** approvals (sample, label proof), questions, and a
         timeline of events and messages, one thread per order.
      Past orders keep the same view, with a "reorder" request. Email notifications
      once the app can send email (0.4g still uses invite links).
      - [x] Read-only portal foundation (!436): separate invitations/password sessions,
        branded current/past published orders, shared ABV/batch dates and opt-in document
        copies. Unavailable fields are explicit; Google, scheduler forecasts, stock,
        duty, derived milestones, approvals/messages and reorders remain open.
    - [x] f. **Isolation by design.** (!436) Portal users are a separate kind of user with no
      staff permissions; every portal query is scoped to the customer's orders on the
      server; a test walks every portal route with a second customer and expects 403/404.
      Other customers, recipes, costs and the producer's sales are never reachable.
    - [ ] g. **Later: org to org.** When the customer also uses biz-e, link the two orgs
      with an explicit, revocable grant so contract batches appear in the customer's own
      trace and recall. Cross-tenant, so it needs its own design review first.
  - Done when: a customer signs in, sees their order move from "materials received" to
    "dispatched" with batch IDs, ABV and a ready date that tracks the schedule, approves a
    label proof, and can't see anything else in the producer's org; the same order works
    whether the customer or the producer supplied the materials and paid the duty.

---

## Order

1. **Phase 0.** Require 2FA and get `main` green now; the database split is planned for
   go-live. Add the 5.1b ratchet straight away so `backend.py` stops growing.
2. **0.4 roles and permissions** before a second producer with staff goes live.
3. **1.2 then 1.3.** Whole bottles and Library stock, then the go-live stocktake. They
   decide whether a new producer can start cleanly and whether stock can be trusted from
   day one. Start 1.3 by checking whether Core can start a batch partway through a
   workflow; that sets its size.
4. **1.1 and 1.4.** Matching modes and the recall screen give owners control and turn the
   trace into something to hand to NZFS.
5. **2.1 then 2.6.** Excise per period, then the Customs stocktake. Both depend on 1.2,
   final-step ABV, and stock locations. 2.5 licensing can run in parallel.
6. **Phase 3** alongside the end of Phase 1; the rest of Phase 2 as NZ Alcohol parts are
   finished.
7. **Phase 4** on the corrected data; 4.1 and 4.7 can go first at any time.
8. **Phase 5** throughout, carving each slice before a plan item changes it (5.1d).
9. **Phase 6** once a second producer works. Generalise from two real producers, not one.

## Sources

Official guidance checked 25 Sep 2026. Re-check before building, because rules and rates
change.

- NZ Customs, [Entry lodgement timing](https://www.customs.govt.nz/business/excise/entry-lodgement-timing):
  lodgement periods, thresholds, due dates, nil returns.
- NZ Customs, [Record-keeping obligations for alcohol licensed manufacturing areas and off-site storage](https://www.customs.govt.nz/business/excise/alcohol-and-excise/record-keeping-obligations-for-alcohol-licenced-manufacturing-areas-and-off-site-storage):
  stock register, 7-year retention, NZ storage.
- NZ Customs, [CCA licence holder guide: licensed manufacturing area](https://www.customs.govt.nz/media/vitaw55u/customer-guide-cca-licence-holder-licensed-manufacturing-area-alcohol-products-oct-2018.pdf):
  at-least-annual stocktakes; confirmed losses are dutiable and must be reported. (Oct
  2018 PDF; this link returned 404 on 25 Sep 2026, and the wording was confirmed from
  Customs' own search excerpts. Find the current guide on customs.govt.nz.)
- NZ Customs, [Excise duty remissions](https://www.customs.govt.nz/business/excise/excise-duty/excise-duty-remissions):
  damaged, destroyed, lost, stolen and faulty goods; form NZCS 277.
- NZ Customs, [Pay excise duty and other charges](https://www.customs.govt.nz/business/excise/pay-excise-duty-and-other-charges/).
- [Sale and Supply of Alcohol Act 2012](https://www.legislation.govt.nz/act/public/2012/0120/latest/DLM3339333.html)
  and its regulations, for 2.5.
